"""Daily fix admission and prepared checkpoint; the existing review chain owns P2/P6."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, fix, run, review_phases
from school_notes2.review import files
from school_notes2.state import phase, safefs
from tests.flows.test_repair import context


@pytest.mark.parametrize("learner", ["one", "two"])
def test_daily_fix_prepare_crash_and_subject_assignments(tmp_path, log, monkeypatch, learner):
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original_run = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original_run(*a, **kw)
    ctx.worktree = lambda kind: wt
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3, review_closures_per_run=20)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": page, "problem": "Hiba.", "relates_to": None}]}, "fake", "a", "b")
    task = fix.next_task(ctx)
    assert task.get("mode") == "fix"
    original = task.set_phase
    monkeypatch.setattr(task, "set_phase", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        fix.prepare(ctx, task)
    resumed = phase.load(task.dir)
    fix.prepare(ctx, resumed)
    value = fetch.fetch_json(resumed, 1, grade=9)
    assert value["mode"] == "fix" and value["packages"] == value["pages"] == []
    assert value["open_review_items"][0]["item_id"] == "R1"
    assert value["subject"] == "m"
    resumed.set_phase("done")
    assert fix.next_task(ctx) is None


def test_priority_is_new_packages_then_fix_then_repair(monkeypatch):
    from school_notes2.flows import repair
    ctx, seen = SimpleNamespace(), []
    monkeypatch.setattr(fetch, "drive_client", lambda *a: None)
    monkeypatch.setattr(fetch, "start", lambda *a: None)
    monkeypatch.setattr(fix, "next_task", lambda *a: seen.append("fix") or "fix-task")
    monkeypatch.setattr(repair, "next_task", lambda *a: seen.append("repair"))
    assert run._new_task(ctx) == "fix-task" and seen == ["fix"]
    monkeypatch.setattr(fetch, "start", lambda *a: "new-task")
    assert run._new_task(ctx) == "new-task" and seen == ["fix"]


def test_fix_inspection_goes_directly_to_finalization(tmp_path, monkeypatch):
    task = phase.create(tmp_path, "one", "notes", "cron", "figures")
    task.update(mode="fix")
    seen = []
    monkeypatch.setattr(review_phases.inspection, "prepare", lambda *a: seen.append("figures"))
    monkeypatch.setattr(review_phases.inspection, "inspect", lambda *a: seen.append("inspect"))
    monkeypatch.setattr(review_phases.correction, "all_items", lambda *a: ["finding"])
    monkeypatch.setattr(review_phases, "finalize", lambda *a: seen.append("finalize"))
    monkeypatch.setattr(review_phases.relations, "inventory", lambda *a: {"items": {}})
    review_phases.advance(SimpleNamespace(notes_path=tmp_path), task, lambda *a: None)
    assert task.phase == "finishing" and seen == ["figures", "inspect", "finalize"]
