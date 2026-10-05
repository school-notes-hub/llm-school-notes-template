"""Scope repair keeps good work and resumes without another writer invocation."""

import json

import pytest

from school_notes2.flows import (correction, fix_scope, inspection, report,
                                 review_phases, run, steps, writer)
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import guard
from .test_phases import finding, install_reader

OTHER = "wiki/m/other.md"
NEW = "wiki/m/new.md"
OLD = "---\ntitle: Másik\ntype: topic\n---\n# Másik\n\nEredeti.\n"


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["p4", "fix"])
@pytest.mark.parametrize("invalid", [False, True])
def test_scope_recovery_continues_and_reports(setup, monkeypatch, learner, mode, invalid):
    ctx, task, page = setup
    ctx.name = learner
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    before = safefs.read_text(ctx.notes_path, page)
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    if mode == "fix":
        files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [{**finding(page), "id": "R1"}]},
                           "fake", "a", "b")
        items = files.open_items(ctx.notes_path, "cron")
        root = task.dir / "fix-before"
        correction.snapshot(ctx.notes_path, root)
        task.set_phase("writing", mode="fix", correction_before=str(root / "before"),
                       open_review_items=items)
    else:
        inspection.prepare(ctx, task)
        inspection.inspect(ctx, task)
        items = correction.assigned(ctx, task)
        task.set_phase("correcting")
    monkeypatch.setattr(writer, "write_changes", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    monkeypatch.setattr(steps, "order_step", lambda *a: [])
    calls = []
    def write(ctx, child, k, *args):
        calls.append(k)
        text = before + "\nJavított magyarázat.\n" + ("[Bővebben](new.md)\n" if invalid else "")
        safefs.write_text(ctx.notes_path, page, text)
        safefs.write_text(ctx.notes_path, OTHER, OLD + "\nNem kiosztott javítás.\n")
        safefs.write_text(ctx.notes_path, NEW, "Új, nem kiosztott oldal.\n")
        result = {"status": "done", "infographic_decisions": [{"page": page, "reason": "Szöveggel érthető."}],
                  "review_closure": [{"file": items[0]["file"], "item_id": "R1", "status": "fixed"}]}
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
        return result
    monkeypatch.setattr(writer, "_call", write)
    def check(*args, **kwargs):
        assert "Nem kiosztott javítás." in safefs.read_text(ctx.notes_path, OTHER)
        assert safefs.is_file(ctx.notes_path, NEW)
        from school_notes2.wiki.check import check_links
        problems = check_links(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page))
        if problems:
            raise steps.CheckFailed(problems)
    monkeypatch.setattr(steps, "check_changed", check)
    if mode == "fix":
        assert run._write(ctx, task) == "done"
        result = writer.merge(writer.results(task))
        files.apply_closure(ctx.notes_path, task.run_id, result["review_closure"], items)
        task.set_phase("figures", inspection_result=result)
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and calls == [1]
    assert task.data["llm_failures"] == 0 and not task.data["needs_owner"]
    text = steps._llm_part(safefs.read_text(ctx.notes_path, page))
    assert "Javított magyarázat." in text
    assert relations.inventory(ctx.notes_path)["items"][items[0]["key"]]["status"] == "fixed"
    assert "recheck" in invoked
    # Real completion aggregation includes the tool note even after a full rollback.
    from school_notes2.flows import operational_report
    from school_notes2.repair import failure
    monkeypatch.setattr(operational_report, "at_finish", lambda *a: None)
    monkeypatch.setattr(failure, "notify", lambda *a: None)
    report.completion(ctx, task)
    notes = safefs.read_json(task.dir, "report.json")["owner_notes"]
    assert notes == []
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    assert not any(e["action"] == "fix.scope_restored" for e in events)
    assert not any(e["action"].startswith("notify.") for e in events)
    review_phases.advance(ctx, phase.load(task.dir), lambda _: None)
    assert calls == [1]


@pytest.mark.parametrize("boundary", ["journal", "restore", "rollback"])
def test_scope_restore_crash_replays_saved_list_and_full_rollback(setup, monkeypatch, boundary):
    # A 2.5.0 rollback must finish even when the new release has page freedom.
    ctx, task, page = setup
    root = task.dir / "fix-before"
    before = safefs.read_text(ctx.notes_path, page)
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix", calls=[{"subject": "m"}], correction_before=str(root / "before"))
    safefs.write_text(ctx.notes_path, page, "Interrupted old work.\n")
    safefs.write_json(root, "scope-restores.json", [page])
    safefs.write_json(root, "rollback.json", {"reason": "2.5.0 rollback"})
    module, name = (correction, "restore") if boundary == "restore" else (phase.Task, "set_phase")
    original = getattr(module, name)
    def crash(*args, **kwargs):
        if boundary != "journal":
            original(*args, **kwargs)
        raise KeyboardInterrupt
    monkeypatch.setattr(module, name, crash)
    with pytest.raises(KeyboardInterrupt):
        fix_scope.resume(ctx, task)
    monkeypatch.setattr(module, name, original)
    task = phase.load(task.dir)
    fix_scope.resume(ctx, task)
    assert safefs.read_text(ctx.notes_path, page) == before
    assert task.phase == "figures" and task.get("fix_scope_rolled_back")


def test_p1_scope_is_not_repaired(setup):
    ctx, task, page = setup
    root = task.dir / "before"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="run", correction_before=str(root / "before"))
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    assert fix_scope.recover(ctx, task) == []
    assert safefs.read_text(ctx.notes_path, OTHER) == OLD


@pytest.mark.parametrize("invalid", [False, True])
def test_cached_fix_result_restores_scope_before_finish_without_llm(setup, monkeypatch, invalid):
    from school_notes2.flows import finish
    from school_notes2.wiki.check import check_links
    ctx, task, page = setup
    install_reader(monkeypatch, page)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {**finding(page), "id": "R1"}]}, "fake", "a", "b")
    items = files.open_items(ctx.notes_path, "cron")
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    before = safefs.read_text(ctx.notes_path, page)
    task.set_phase("writing", mode="fix", writing_k=2, open_review_items=items,
                   correction_before=str(root / "before"))
    safefs.write_text(ctx.notes_path, page, before + "\nJavítás.\n" + ("[Új](new.md)\n" if invalid else ""))
    safefs.write_text(ctx.notes_path, NEW, "Nem kiosztott oldal.\n")
    safefs.write_json(task.dir, "result-1.json", {"status": "done"})
    monkeypatch.setattr(writer, "_call", lambda *a: pytest.fail("replayed writer"))
    # This test isolates cached P1 recovery; P4 retries have separate coverage.
    monkeypatch.setattr(correction, "run", lambda ctx, task, *a: task.update(correction_rolled_back=True))
    def content(ctx, task):
        assert safefs.is_file(ctx.notes_path, NEW)
        errors = check_links(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page))
        if errors:
            raise steps.CheckFailed(errors)
        return steps.Prepared({"status": "done"}, False)
    monkeypatch.setattr(steps, "content_steps", content)
    monkeypatch.setattr(report, "completion", lambda *a: None)
    monkeypatch.setattr(steps, "check_changed", lambda *a, **kw: None)
    monkeypatch.setattr(finish.git_finish, "run", lambda task, *a: task.set_phase("done") or "done")
    run.advance(ctx, task)
    assert task.phase == "done" and not task.data["llm_failures"]
    assert "Javítás." in safefs.read_text(ctx.notes_path, page)
    assert not task.get("fix_scope_rolled_back")
    assert relations.inventory(ctx.notes_path)["items"][items[0]["key"]]["status"] == "open"
