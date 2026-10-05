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
    ctx.cfg.limits = SimpleNamespace(max_agents=3, review_closures_per_run=20, fix_runs_per_day=6)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": page, "problem": "Hiba.", "relates_to": None}]}, "fake", "a", "b")
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
    assert fix.next_task(ctx).get("mode") == "fix"


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


def test_one_pass_per_run_without_correction_rounds(tmp_path, monkeypatch):
    """#9/R1–R7: figures → one independent check → finalize; open findings wait for the next run."""
    task = phase.create(tmp_path, "one", "notes", "cron", "figures")
    task.update(mode="fix")
    seen = []
    monkeypatch.setattr(review_phases.inspection, "prepare", lambda *a: seen.append("figures"))
    monkeypatch.setattr(review_phases.inspection, "inspect", lambda ctx, task: seen.append(("inspect", task.get("recheck_all"))))
    monkeypatch.setattr(review_phases, "finalize", lambda *a: seen.append("finalize"))
    monkeypatch.setattr(review_phases.relations, "inventory", lambda *a: {"items": {}})
    review_phases.advance(SimpleNamespace(notes_path=tmp_path), task, lambda *a: None)
    assert task.phase == "finishing" and seen == ["figures", ("inspect", None), "finalize"]


@pytest.mark.parametrize("saved", ["correcting", "rechecking", "waiting_quota"])
def test_legacy_correction_round_goes_through_the_content_steps_once_more(tmp_path, monkeypatch, saved):
    """Futás-review blocker: a 2.5.1 task stopped in a correction round (also with
    `content_pending`, also waiting for quota) runs the content steps on its kept files –
    closures, lesson notes, stamps, evidence, check – and then rechecks every change once."""
    from school_notes2.flows import finish
    task = phase.create(tmp_path, "one", "notes", "cron", saved)
    task.update(mode="fix", content_pending=True, review_complete=True, writing_k=2, ranges=[[1, 1]],
                quota_phase="correcting" if saved == "waiting_quota" else None)
    seen = []
    monkeypatch.setattr(finish.steps, "content_steps",
                        lambda ctx, task: seen.append(("content", task.phase)) or SimpleNamespace(new_owner=[], question=False, result={}))
    monkeypatch.setattr(review_phases, "advance", lambda ctx, task, *a: seen.append(("check", task.get("recheck_all"))) or task.set_phase("finishing"))
    monkeypatch.setattr(finish, "_snapshot", lambda *a, **kw: {})
    monkeypatch.setattr(finish.git_finish, "run", lambda task, *a: "done")
    monkeypatch.setattr("school_notes2.flows.repair.complete", lambda *a: None)
    monkeypatch.setattr("school_notes2.flows.report.completion", lambda *a: None)
    ctx = SimpleNamespace(notes_path=tmp_path, worktree=lambda _: None, cfg=SimpleNamespace(
        limits=SimpleNamespace(max_agents=3), timeouts=SimpleNamespace(fetch_s=1, push_s=1, ls_remote_s=1)))
    monkeypatch.setattr("school_notes2.figures.licenses.preflight", lambda *a: None)
    finish.finish(ctx, task, notify_owner_items=lambda items: None)
    assert seen == [("content", "writing"), ("check", True)]
    assert task.get("writing_k") == 2  # past the last range: no writer starts


@pytest.mark.parametrize("learner", ["one", "two"])
def test_legacy_owner_migration_runs_in_the_next_run_before_assignment(tmp_path, log, monkeypatch, learner):
    from school_notes2.wiki import frontmatter
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.worktree = lambda _: wt
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3, review_closures_per_run=20, fix_runs_per_day=6)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    path = files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": page, "problem": "Hiba.", "chain": 1}]}, "r", "a", "b")
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": {"R1": "owner"}, "repair_policy": 0}))
    assert fix.next_task(ctx) is None  # R5: a pending migration alone starts no run.
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base=wt.out("rev-parse", "HEAD").strip(), open_review_items=[], pending_figures=[])
    fix.prepare(ctx, task)
    supplied = fetch.fetch_json(task, 1, grade=9)
    assert supplied["open_review_items"][0]["item_id"] == "R1"
    assert supplied["open_review_items"][0]["chain"] == 1
    assert not task.get("skip_writer")
    assert path.relative_to(ctx.notes_path).as_posix() in task.get("tool_writes")
