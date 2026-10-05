"""K-1/K-2/K-5/K-6/K-7/K-9 regression cases, without sockets or a model."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import chat, repair, run, status
from school_notes2.repair import failure, preflight, queue
from school_notes2.state import phase, safefs
from school_notes2.state.errors import NeedsOwner
from tests.flows.test_repair import context
from tests.flows.test_repair_queue import page
from tests.conftest import assert_suppressed


@pytest.mark.parametrize("mode,blocked", [("cron", False), ("repair", False), ("repair", True)])
@pytest.mark.parametrize("build_queue", [False, True])
def test_rejected_command_preserves_existing_run(tmp_path, log, monkeypatch, mode, blocked, build_queue):
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    ctx.lock = lambda: SimpleNamespace(acquire=lambda *a: None, release=lambda: None)
    monkeypatch.setattr(repair.setup, "ensure", lambda _: None)
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "writing")
    task.update(mode=mode, repair_topic=topic if blocked else "wiki/m/other.md",
                repair_request_queue=build_queue, no_push=True)
    if blocked:
        task.mark_needs_owner("decision", "continue", "needs_owner")
    before = task.path.read_bytes()
    assert repair.repair(ctx, topic=topic, build_queue=build_queue) == 1
    assert task.path.read_bytes() == before and len(mailed) == 1


@pytest.mark.parametrize("target", ["missing", "lesson", "summary"])
def test_invalid_target_creates_no_task(tmp_path, log, monkeypatch, target):
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    page(ctx.notes_path, "lesson", "lesson-notes", lessons=[{"topics": ["a.md"]}])
    page(ctx.notes_path, "summary", "chapter-summary")
    ctx.lock = lambda: SimpleNamespace(acquire=lambda *a: None, release=lambda: None)
    monkeypatch.setattr(repair.setup, "ensure", lambda _: None)
    assert repair.repair(ctx, topic=f"wiki/m/{target}.md") == 1
    assert phase.all_tasks(tmp_path, ctx.name) == [] and len(mailed) == 1
    assert run._may_run(ctx, None)


def test_preflight_reads_pinned_commit_not_worktree(tmp_path, log, git_factory):
    from tests.conftest import make_origin
    origin = make_origin(tmp_path, {"wiki/m/a.md": "---\ntype: topic\n---\nA\n"})
    wt = git_factory(origin)
    preflight.require_ready(wt, "main", "wiki/m/a.md")
    with pytest.raises(NeedsOwner):
        preflight.require_ready(wt, "main", "wiki/m/missing.md")


@pytest.mark.parametrize("has_queue", [False, True])
def test_pre_upgrade_failed_handoff_hold_can_finish_without_creating_absent_queue(tmp_path, log, monkeypatch, has_queue):
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    ctx.lock = lambda: SimpleNamespace(note=lambda _: None)
    if has_queue:
        safefs.write_json(ctx.notes_path, queue.PATH, queue.build(ctx.notes_path))
    task = repair.start(ctx, topic=topic, no_push=True)
    repair.prepare(ctx, task)
    # Persisted pre-upgrade handoffs still resume through their original queue path.
    task.set_phase("moved", repair_failed=True)
    monkeypatch.setattr(failure.discard, "discard", lambda *a: None)
    real = failure.write_item
    def crash(ctx, task):
        real(ctx, task)
        raise RuntimeError("handoff interrupted")
    monkeypatch.setattr(failure, "write_item", crash)
    with pytest.raises(RuntimeError):
        repair.prepare(ctx, task)
    monkeypatch.setattr(failure, "write_item", real)
    task = phase.load(task.dir)
    repair.prepare(ctx, task)
    assert safefs.is_file(ctx.notes_path, queue.PATH) == has_queue
    assert (queue.PATH in task.get("tool_writes", {})) == has_queue
    assert safefs.is_file(ctx.notes_path, task.get("repair_owner_item"))
    task.set_phase("committed")
    def finish(ctx, task, **kwargs):
        assert not task.get("no_push") and task.get("skip_writer")
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(chat.finish_flow, "finish", finish)
    assert chat.session_finish(ctx)["state"] == "done"
    assert phase.open_task(tmp_path, ctx.name, "notes") is None


def test_queue_hold_can_finish_without_writer(tmp_path, log, monkeypatch):
    ctx, _, _ = context(tmp_path, log, monkeypatch)
    ctx.lock = lambda: SimpleNamespace(note=lambda _: None)
    task = repair.start(ctx, build_queue=True, no_push=True)
    repair.prepare(ctx, task)
    task.set_phase("committed")
    def finish(ctx, task, **kw):
        assert not task.get("no_push")
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(chat.finish_flow, "finish", finish)
    assert chat.session_finish(ctx)["state"] == "done"


def test_trial_dependencies_use_finished_queue_state(tmp_path):
    a = page(tmp_path, "a")
    b = page(tmp_path, "b")
    lesson = page(tmp_path, "lesson", "lesson-notes", lessons=[{"topics": ["a.md"]}])
    summary = page(tmp_path, "summary", "chapter-summary")
    data, book = queue.build(tmp_path), queue.inventory(tmp_path)
    with pytest.raises(NeedsOwner):
        queue.require_ready(lesson, data, book)
    next(i for i in data["items"] if i["page"] == a)["status"] = "done"
    queue.require_ready(lesson, data, book)
    with pytest.raises(NeedsOwner):
        queue.require_ready(summary, data, book)
    next(i for i in data["items"] if i["page"] == b)["status"] = "done"
    queue.require_ready(summary, data, book)


@pytest.mark.parametrize("stage", ["writing", "committed"])
def test_held_trial_suppression_and_phase_text(tmp_path, log, monkeypatch, stage):
    ctx, topic, mailed = context(tmp_path, log, monkeypatch)
    task = repair.start(ctx, topic=topic, no_push=True)
    task.set_phase(stage)
    assert not run._may_run(ctx, task)
    assert not mailed
    assert_suppressed(log, "no_push")
    data = {"learner": ctx.name, "lock": {"held": False}, "open": [{
        "kind": "notes", "mode": "cron", "run_id": task.run_id, "phase": stage,
        "age_h": 1, "packages": 0, "retries": 0, "llm_failures": 0, "no_push": True}],
        "needs_owner": [], "worktree_dirty_outside_run": False, "drive": None,
        "images": {}, "review_items": {"open": 0, "owner": 0}, "last_review": None,
        "wiki_open_questions": [], "references_without_map": [], "pack_mb": 0, "log": "log"}
    text = status.render(data)
    assert ("commit után megállt" in text) == (stage == "committed")


def test_hold_reminder_is_suppressed_across_resume(tmp_path, log, monkeypatch):
    from school_notes2.notify import Mailer
    ctx, topic, _ = context(tmp_path, log, monkeypatch)
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: delivered.append(message) or True)
    ctx.mailer = Mailer(tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log)
    task = repair.start(ctx, topic=topic, no_push=True)
    assert not run._may_run(ctx, task)
    assert not run._may_run(ctx, phase.load(task.dir))
    assert not delivered
    assert_suppressed(log)
    assert not run._may_run(ctx, phase.load(task.dir))
    assert not delivered
    assert_suppressed(log)
