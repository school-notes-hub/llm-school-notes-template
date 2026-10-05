"""Finite correction rounds use fresh evidence and include the entire backlog."""

import pytest

from school_notes2.flows import correction, correction_round, inspection, recheck, review_phases
from school_notes2.reader import calls, report
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs


def backlog(ctx, page, n=1):
    path = files.write_review(ctx.notes_path, "2026-10-03", {"findings": [
        {"id": f"R{i}", "file": page, "quote": "A test lefelé gyorsul.", "problem": f"Indok {i}.",
         "category": "nyelvezet"} for i in range(1, n + 1)], "verdict": "changes"}, "old", "a", "b")
    return path.relative_to(ctx.notes_path).as_posix()


def test_report_tie_break_uses_complete_finding_content(setup):
    ctx, task, page = setup
    finding = {"id": "F1", "file": page, "quote": "A test lefelé gyorsul.",
               "problem": "Hiányzó indok.", "origin": "reader", "severity": "hiba"}
    findings = [{**finding, "category": category} for category in ("pontosság", "nyelvezet")]
    path = "docs/review/deterministic.md"
    report.write(ctx.notes_path, path, findings, [], "fake", "a", task.data["created"])
    first = (ctx.notes_path / path).read_bytes()
    (ctx.notes_path / path).unlink()
    report.write(ctx.notes_path, path, list(reversed(findings)), [], "fake", "a", task.data["created"])
    assert (ctx.notes_path / path).read_bytes() == first


@pytest.mark.parametrize("stop", [2, 4])
@pytest.mark.parametrize("crash", [False, True])
def test_real_rounds_not_ok_then_ok_or_owner_and_resume(setup, monkeypatch, stop, crash):
    ctx, task, page = setup
    path = backlog(ctx, page)
    task.set_phase("correcting", inspection_report=None, inspection_figures=[], correction_round=1)
    writers, readers, before_text = [], [], []
    def write(ctx, child, handlers):
        writers.append(child.run_id)
        n = int(child.run_id.rsplit("r", 1)[1])
        text = safefs.read_text(ctx.notes_path, page)
        safefs.write_text(ctx.notes_path, page, text + f"\nJavítás {n}.\n")
        safefs.write_json(child.dir, "result-1.json", {"status": "done", "review_closure": [
            {"file": path, "item_id": "R1", "status": "fixed", "note": "Indok."}]})
        return "done"
    monkeypatch.setattr(correction.writer, "run_ranges", write)
    monkeypatch.setattr(correction, "validated", lambda ctx, child, root, items, result, edits:
                        {"status": "done", "result": result})
    def read(repo, view, folder, stage, assigned, configured, **kw):
        readers.append(folder)
        n = int(folder.name.rsplit("r", 1)[1])
        before_text.append(safefs.read_text(correction_round.root(task), "before/" + page))
        return {"status": "reviewed", "model": "fake", "review": {"items": [
            {"key": i["key"], "verdict": "ok" if n >= stop else "not-ok", "answer": "Indok."}
            for i in assigned["items"]], "hits": [], "owner_notes": []}}
    monkeypatch.setattr(calls, "run", read)
    original = recheck.apply
    fired = []
    def interrupted(ctx, task, saved):
        if crash and correction_round.number(task) == 2 and not fired:
            fired.append(True)
            raise KeyboardInterrupt()
        return original(ctx, task, saved)
    monkeypatch.setattr(recheck, "apply", interrupted)
    if crash:
        with pytest.raises(KeyboardInterrupt):
            review_phases.advance(ctx, task, lambda _: None)
        task = phase.load(task.dir)
        assert task.phase == "rechecking" and task.get("correction_round") == 2
    review_phases.advance(ctx, task, lambda _: None)
    rounds = min(stop, 3)
    assert task.phase == "finishing" and task.get("correction_round") == rounds
    assert len(writers) == len(readers) == rounds
    assert len(set(readers)) == rounds
    detail = relations.inventory(ctx.notes_path)["items"][path + "#R1"]
    assert detail["status"] == ("fixed" if stop == 2 else "owner")
    assert detail["repair_attempts"] == rounds
    assert "Javítás 1." in before_text[1]


def test_clean_package_p4_includes_old_style_items_and_other_subject_figure(setup):
    from school_notes2.flows import correction_figures
    from school_notes2.figures import pending
    ctx, task, page = setup
    path = backlog(ctx, page, 2)
    brief = {"id": "other", "page": "wiki/other/topic.md", "kind": "figure", "anchor": "Téma",
             "purpose": "Tanulás", "must_show": [], "avoid_misreading": "Irány", "taught_conventions": [],
             "text_complete_without_figure": True}
    pending.record(ctx.notes_path, brief, "old", [], attempted=False)
    task.update(inspection_report=None, inspection_figures=[], inspection_units=[])
    assert [i["key"] for i in correction.all_items(ctx, task)] == [path + "#R1", path + "#R2"]
    assert correction.assigned(ctx, task) == correction.all_items(ctx, task)
    assert correction_figures.waiting(ctx, task)[0]["commission"] == brief


@pytest.mark.parametrize("bound", [False, True])
def test_p5_new_error_has_own_item_or_reopens_exact_key(setup, bound):
    ctx, task, page = setup
    path = backlog(ctx, page, 2)
    listed = files.open_items(ctx.notes_path, "cron")
    closures = [{"file": path, "item_id": i["item_id"], "status": "fixed"} for i in listed]
    files.apply_closure(ctx.notes_path, "first", closures, listed, automatic=True)
    before = task.dir / "before"
    before.mkdir()
    safefs.write_text(before, page, "Old.\n")
    safefs.write_text(ctx.notes_path, page, "Changed.\n")
    task.update(inspection_report=path)
    error = {"file": page, "quote": "Changed.", "problem": "Új hiba.", "category": "pontosság",
             "severity": "hiba", "relates_to": None, "item_key": path + "#R2" if bound else None}
    saved = {"receipts": {}, "units": [{"status": "reviewed", "model": "fake", "unit": {"pages": [page]},
        "before": str(before), "items": [{**c, "key": c["file"] + "#" + c["item_id"]} for c in closures],
        "hits": [], "review": {"items": [], "hits": [], "owner_notes": [], "findings": [error]}}]}
    recheck.apply(ctx, task, saved)
    recheck.apply(ctx, task, saved)
    known = relations.inventory(ctx.notes_path)["items"]
    assert known[path + "#R1"]["status"] == "fixed"
    assert known[path + "#R1"]["repair_attempts"] == 1
    assert known[path + "#R2"]["repair_attempts"] == 1
    key = path + ("#R2" if bound else "#R3")
    assert known[key]["status"] == "open" and known[key]["origin"] == "recheck"
    assert len(known) == (2 if bound else 3)
    if not bound:
        assert known[key].get("repair_attempts", 0) == 0


@pytest.mark.parametrize("retry_ok", [False, True])
def test_rollback_retries_once_without_consuming_attempts(setup, monkeypatch, retry_ok):
    from school_notes2.flows import set_aside
    from school_notes2.state.errors import BadWork
    ctx, task, page = setup
    path = backlog(ctx, page)
    task.update(inspection_report=path, inspection_figures=[])
    writes, mail = [], []
    original = safefs.read_text(ctx.notes_path, page)
    def write(ctx, child, handlers):
        writes.append(child.run_id)
        safefs.write_text(ctx.notes_path, page, original + "\nJavított.\n")
        if not retry_ok or len(writes) == 1:
            raise BadWork("invalid whole round")
        safefs.write_json(child.dir, "result-1.json", {"status": "done", "review_closure": [
            {"file": path, "item_id": "R1", "status": "fixed"}]})
        return "done"
    monkeypatch.setattr(correction.writer, "run_ranges", write)
    monkeypatch.setattr(correction, "validated", lambda ctx, child, root, items, result, edits:
                        {"status": "done", "result": result})
    monkeypatch.setattr(set_aside, "rollback_notice", lambda *a: mail.append(1))
    with pytest.raises(BadWork):
        correction.run(ctx, task)
    assert len(writes) == 1
    if retry_ok:
        correction.run(ctx, phase.load(task.dir))
    detail = relations.inventory(ctx.notes_path)["items"][path + "#R1"]
    assert detail.get("repair_attempts", 0) == int(retry_ok)
    assert detail["status"] == ("fixed" if retry_ok else "open")
    assert mail == []
    assert "Javított." in safefs.read_text(ctx.notes_path, page)


def test_243_checkpoint_paths_remain_round_one(setup):
    ctx, task, _ = setup
    root = inspection.folder(task)
    safefs.write_json(root, "correction/receipt.json", {"status": "done", "result": {"status": "done"}})
    safefs.write_json(root, "p5.json", {"units": [], "receipts": {}})
    safefs.write_json(root, "reader/topic/recheck/receipt.json", {"status": "not_checked"})
    assert correction_round.root(task) == root / "correction"
    assert correction_round.p5(task) == "p5.json"
    assert correction_round.reader(task, "topic") == root / "reader/topic/recheck"
    task.set_phase("rechecking")
    recheck.run(ctx, phase.load(task.dir))
    task.update(correction_round=2)
    assert correction_round.root(task) == root / "correction-r2"
    assert correction_round.p5(task) == "p5-r2.json"
    assert correction_round.reader(task, "topic") != root / "reader/topic/recheck"


def test_suggestion_is_owner_note_old_backlog_is_not_reclassified(setup):
    ctx, task, page = setup
    path = backlog(ctx, page)
    findings, notes, _ = report.prepare(ctx.notes_path, [{"file": page, "severity": "javaslat", "problem": "Rövidíthető."}], [])
    assert not findings and notes == [page + ": Rövidíthető."]
    assert files.open_items(ctx.notes_path, "cron")[0]["key"] == path + "#R1"
    assert not safefs.exists(ctx.notes_path, "docs/review/javaslatok.md")


def test_243_p4_checkpoint_continues_without_replaying_writer(setup, monkeypatch):
    ctx, task, page = setup
    path = backlog(ctx, page)
    task.set_phase("correcting", inspection_figures=[], correction_items=files.open_items(ctx.notes_path, "cron"))
    root = inspection.folder(task) / "correction"
    correction.snapshot(ctx.notes_path, root)
    safefs.write_json(root, "receipt.json", {"status": "done", "result": {"status": "done", "review_closure": [
        {"file": path, "item_id": "R1", "status": "fixed"}]}})
    monkeypatch.setattr(correction.writer, "run_ranges", lambda *a: pytest.fail("replayed 2.4.3 P4"))
    correction.run(ctx, phase.load(task.dir))
    correction.run(ctx, phase.load(task.dir))
    detail = relations.inventory(ctx.notes_path)["items"][path + "#R1"]
    assert detail["repair_attempts"] == 1 and detail["status"] == "fixed"


def test_package_material_is_pinned_before_p4_and_finish_retry(setup, monkeypatch):
    ctx, task, page = setup
    inspection.prepare(ctx, task)
    original = task.get("inspection_changed")
    safefs.write_text(ctx.notes_path, "wiki/other/old.md", "---\ntype: topic\ntitle: Régi\n---\n# Régi\n")
    monkeypatch.setattr(inspection.steps, "llm_snapshot", lambda *a: {page: "new", "wiki/other/old.md": "repair"})
    inspection.prepare(ctx, task)
    assert task.get("inspection_changed") == original


def test_child_writer_never_inherits_parent_call_receipt(setup):
    ctx, task, page = setup
    backlog(ctx, page)
    task.update(mode="fix", correction_round=2, fix_calls={"1": 1}, fix_crash_retries=[1],
                writer_invocation=8, writer_output_key="old", counted_bad_outputs=["old"],
                retry_calls=[1], retry_items={"1": []}, writer_check={"count": 3, "warnings": ["old"]})
    child = correction.child_task(ctx, task, correction_round.root(task), correction.assigned(ctx, task))
    assert child.get("fix_calls") == {} and child.get("fix_crash_retries") == []
    assert child.get("writer_output_key") is None and child.get("retry_calls") == []
    assert child.get("writer_check") == {"count": 0, "warnings": []}


def test_full_rollback_keeps_figure_attempts_and_sends_one_tool_error(setup, monkeypatch):
    from school_notes2.figures import pending
    from school_notes2.state.errors import BadWork
    from tests.conftest import recording_mailer
    from .test_review_fixes import figure
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    pending.record(ctx.notes_path, brief, "previous", [], attempted=True)
    task.set_phase("correcting", correction_round=1, inspection_figures=[{
        "brief": brief, "candidate": {"state": "failed", "reason": "Elutasítva."}, "attempted": False}])
    delivered, calls = [], []
    ctx.mailer = recording_mailer(task.dir, ctx.log, monkeypatch, delivered)
    def fail(*args):
        calls.append(1)
        raise BadWork("whole round invalid")
    monkeypatch.setattr(correction.writer, "run_ranges", fail)
    with pytest.raises(BadWork):
        review_phases.advance(ctx, task, lambda _: None)
    with pytest.raises(BadWork):
        review_phases.advance(ctx, phase.load(task.dir), lambda _: None)
    assert task.phase == "correcting" and len(calls) == 2
    assert pending.load(ctx.notes_path)[0]["run_ids"] == ["previous"]
    assert delivered == []
