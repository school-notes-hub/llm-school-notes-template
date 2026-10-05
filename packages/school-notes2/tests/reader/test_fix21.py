"""Fix reviews remain within repaired items and changed lines, also after restart."""

import pytest

from school_notes2.flows import correction, correction_figures, inspection
from school_notes2.reader import notices, report
from school_notes2.review import scope
from school_notes2.state import phase, safefs
from .test_review_fixes import figure


def test_preview_quote_belongs_to_figure_and_has_no_section_notice(setup):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    f = {"file": page, "quote": "![Ábra](<../assets/reader-preview/f.png>)", "problem": "Hibás irány"}
    mapped = report.figure_quote(ctx.notes_path, f)
    assert mapped["figure_id"] == "f" and not report.locate(ctx.notes_path, mapped)["unlocated"]
    text = safefs.read_text(ctx.notes_path, page)
    assert not notices._placements(text, [mapped], [], [], page, False)


def test_target_scope_only_changed_lines():
    old, new = "Untouched.\nBad.\n", "Untouched.\nFixed.\n"
    findings = [{"file": "p", "quote": quote, "problem": quote} for quote in ["Untouched.", "Fixed.", "Missing."]]
    kept, notes = scope.partition(findings, lambda _: old, lambda _: new, ["p"])
    assert [f["quote"] for f in kept] == ["Fixed.", "Missing."] and len(notes) == 1
    assert kept[1]["unlocated"]


def test_p4_figures_outside_item_capacity_and_child_resume(setup):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    task.update(inspection_figures=[{"brief": brief, "candidate": candidate}], inspection_receipts={})
    waiting = correction_figures.waiting(ctx, task)
    task.update(correction_figures=waiting)
    root = inspection.folder(task) / "correction"
    correction.snapshot(ctx.notes_path, root)
    child = correction.child_task(ctx, task, root, [])
    assert child.get("pending_figures") == waiting and len(child.get("calls")) == 1
    assert not safefs.is_file(ctx.notes_path, ".school-notes/figures/f/figure.json")
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", candidate)
    resumed = correction.child_task(ctx, phase.load(task.dir), root, [])
    assert resumed.run_id == child.run_id
    assert safefs.read_json(ctx.notes_path, ".school-notes/figures/f/figure.json") == candidate


@pytest.mark.parametrize("changed", [False, True])
def test_fix_p3_calls_only_recheck_and_resumes_without_second_review(setup, monkeypatch, changed):
    from school_notes2.reader import calls, units, verdicts
    from school_notes2.review import files, relations
    ctx, task, page = setup
    task.update(mode="fix")
    verdicts.record(ctx.notes_path, [{"file": page, "verdict": "changes"}],
                    {page: units.page_key(ctx.notes_path, page)}, "old", task.data["created"])
    before = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, before)
    text = safefs.read_text(ctx.notes_path, page)
    if changed:
        safefs.write_text(ctx.notes_path, page, text.replace("A test lefelé gyorsul.", "A test a gravitáció miatt gyorsul."))
    path = files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": page, "quote": "A test lefelé gyorsul.", "problem": "Miért?", "relates_to": None}]},
        "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    closure = {"file": path, "item_id": "R1", "status": "fixed"}
    files.apply_closure(ctx.notes_path, task.run_id, [closure], [])
    task.update(inspection_result={"status": "done", "review_closure": [closure]})
    stages = []
    def review(repo, view, folder, stage, assigned, configured, **kw):
        stages.append(stage)
        assert stage == "recheck"
        pages = safefs.read_json(folder, "in/pages.json")
        assert all(p["text"] == "" and p["items"] == {} for p in pages)
        assert ("gravitáció" in str(pages[0]["changed_lines"])) == changed
        return {"status": "reviewed", "model": "fake/high", "review": {"items": [
            {"key": path + "#R1", "verdict": "ok", "answer": "Megmagyarázza."}], "hits": [], "owner_notes": []}}
    monkeypatch.setattr(calls, "run", review)
    inspection.prepare(ctx, task)
    original = inspection._apply
    def crash(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(inspection, "_apply", crash)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        inspection.inspect(ctx, task)
    monkeypatch.setattr(inspection, "_apply", original)
    inspection.inspect(ctx, phase.load(task.dir))
    assert stages == ["recheck"]
    assert relations.inventory(ctx.notes_path)["items"][path + "#R1"]["recheck"]["verdict"] == "ok"
    assert verdicts.valid(ctx.notes_path, page)["verdict"] == "ok"


def test_tool_failure_does_not_become_writer_attempt_after_crash(setup, monkeypatch):
    import pytest
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    safefs.unlink(ctx.notes_path, ".school-notes/figures/f/figure.json")
    original = inspection.candidate_state
    fired = []
    def fail(*args):
        result = original(*args)
        if not fired:
            safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", result)
            fired.append(1)
            raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(inspection, "candidate_state", fail)
    with pytest.raises(KeyboardInterrupt):
        inspection.prepare(ctx, task)
    resumed = phase.load(task.dir)
    inspection.prepare(ctx, resumed)
    assert resumed.get("inspection_figures")[0]["attempted"] is False


def test_p4_does_not_count_unassigned_tool_failure_on_resume(setup, monkeypatch):
    import pytest
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", {"state": "failed", "reason": "tool"})
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed", "reason": "tool"}, "attempted": False}])
    root = inspection.folder(task) / "correction"
    original = inspection.candidate_state
    fired = []
    def crash(*args):
        result = original(*args)
        if not fired:
            fired.append(1)
            raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(inspection, "candidate_state", crash)
    monkeypatch.setattr(correction.generation_receipts, "refresh", lambda *a: None)
    saved = {"status": "done", "result": {"status": "done"}}
    with pytest.raises(KeyboardInterrupt):
        correction.apply(ctx, task, root, saved)
    resumed = phase.load(task.dir)
    correction.apply(ctx, resumed, root, saved)
    assert resumed.get("inspection_figures")[0]["attempted"] is False


def test_recheck_optional_findings_contract():
    from school_notes2.reader import contracts
    finding = {"id": "F-1", "file": "/work/m/a.md", "quote": "Text", "category": "olvasói lyuk",
               "problem": "Missing", "suggestion": "Explain", "relates_to": "decision"}
    value = {"items": [], "hits": [], "owner_notes": [], "findings": [finding]}
    assigned = {"items": [], "hits": []}
    known = {"pages": {"wiki/m/a.md": {"decisions": ["decision"]}}}
    with pytest.raises(ValueError, match="new_evidence"):
        contracts.check(value, "recheck", assigned, known, allowed_paths={"wiki/m/a.md"})
    finding["new_evidence"] = "New fact"
    assert contracts.check(value, "recheck", assigned, known)["findings"][0]["file"] == "wiki/m/a.md"
    value["findings"].append(dict(finding))
    with pytest.raises(ValueError, match="duplicate finding"):
        contracts.check(value, "recheck", assigned, known)
