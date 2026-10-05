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
        assert safefs.read_text(ctx.notes_path, OTHER) == OLD
        assert not safefs.is_file(ctx.notes_path, NEW)
        from school_notes2.wiki.check import check_links
        problems = check_links(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page))
        if problems:
            raise steps.CheckFailed(problems)
    monkeypatch.setattr(steps, "check_changed", check)
    if mode == "fix":
        assert run._write(ctx, task) == "done"
        if not invalid:
            result = writer.merge(writer.results(task))
            files.apply_closure(ctx.notes_path, task.run_id, result["review_closure"], items)
            task.set_phase("figures", inspection_result=result)
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing" and calls == [1]
    assert task.data["llm_failures"] == 0 and not task.data["needs_owner"]
    text = steps._llm_part(safefs.read_text(ctx.notes_path, page))
    assert ("Javított magyarázat." in text) != invalid
    assert relations.inventory(ctx.notes_path)["items"][items[0]["key"]]["status"] == ("open" if invalid else "fixed")
    assert ("recheck" in invoked) != invalid
    # Real completion aggregation includes the tool note even after a full rollback.
    from school_notes2.flows import operational_report
    from school_notes2.repair import failure
    monkeypatch.setattr(operational_report, "at_finish", lambda *a: None)
    monkeypatch.setattr(failure, "notify", lambda *a: None)
    report.completion(ctx, task)
    notes = safefs.read_json(task.dir, "report.json")["owner_notes"]
    assert len(notes) == 1 and NEW in notes[0] and OTHER in notes[0]
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    assert any(e["action"] == "fix.scope_restored" and e["pages"] == [NEW, OTHER] for e in events)
    assert not any(e["action"].startswith("notify.") for e in events)
    review_phases.advance(ctx, phase.load(task.dir), lambda _: None)
    assert calls == [1]


@pytest.mark.parametrize("boundary", ["journal", "restore", "rollback"])
def test_scope_restore_crash_replays_saved_list_and_full_rollback(setup, monkeypatch, boundary):
    ctx, task, page = setup
    root = task.dir / "fix-before"
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    correction.snapshot(ctx.notes_path, root)
    task.set_phase("writing", mode="fix", correction_before=str(root / "before"),
                   retry_link_pages=[page])
    before = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, before + "\nJó javítás.\n")
    safefs.unlink(ctx.notes_path, OTHER)
    safefs.write_text(ctx.notes_path, NEW, "Törlendő.\n")
    task.update(tool_parts={OTHER: "stale", NEW: "new"}, tool_hashes={OTHER: "stale", NEW: "new"})
    fired = []
    original = safefs.write_json if boundary == "journal" else safefs.write_bytes
    def crash(root_, rel, value, *args):
        original(root_, rel, value, *args)
        target = root_ == root and rel == "scope-restores.json" if boundary == "journal" else root_ == ctx.notes_path and rel == OTHER
        if target and not fired:
            fired.append(1)
            raise KeyboardInterrupt()
    if boundary != "rollback":
        monkeypatch.setattr(safefs, "write_json" if boundary == "journal" else "write_bytes", crash)
        with pytest.raises(KeyboardInterrupt):
            fix_scope.recover(ctx, task)
        task = phase.load(task.dir)
    assert fix_scope.recover(ctx, task) == [NEW, OTHER]
    assert safefs.read_text(ctx.notes_path, OTHER) == OLD
    assert not safefs.is_file(ctx.notes_path, NEW)
    assert "Jó javítás." in safefs.read_text(ctx.notes_path, page)
    if boundary == "rollback":
        original_restore = correction.restore
        def stop(repo, root):
            original_restore(repo, root)
            raise KeyboardInterrupt()
        monkeypatch.setattr(correction, "restore", stop)
        with pytest.raises(KeyboardInterrupt):
            fix_scope.rollback(ctx, task, steps.CheckFailed([]))
        monkeypatch.setattr(correction, "restore", original_restore)
        task = phase.load(task.dir)
        fix_scope.resume(ctx, task)
        assert task.phase == "figures" and task.get("fix_scope_rolled_back")
        assert safefs.read_text(ctx.notes_path, page) == before
    assert len(task.get("scope_owner_notes")) == 1
    assert task.get("tool_parts")[OTHER] == guard.parts_hash(OLD)
    assert NEW not in task.get("tool_parts") and NEW not in task.get("tool_hashes")


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
    def content(ctx, task):
        assert not safefs.is_file(ctx.notes_path, NEW)
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
    assert ("Javítás." in safefs.read_text(ctx.notes_path, page)) != invalid
    assert bool(task.get("fix_scope_rolled_back")) == invalid
    assert relations.inventory(ctx.notes_path)["items"][items[0]["key"]]["status"] == "open"
