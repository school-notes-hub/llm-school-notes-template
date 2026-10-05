"""Only completion mail survives task completion and process interruption."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from school_notes2.flows import finish, report, run, steps
from school_notes2.notify import Mailer, Notice, pending
from school_notes2.review import files
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.conftest import assert_suppressed


def context(tmp_path, log, learner):
    (tmp_path / "repo").mkdir(exist_ok=True)
    return SimpleNamespace(
        name=learner, notes_path=tmp_path / "repo", log=log,
        cfg=SimpleNamespace(state_dir=tmp_path / "state", limits=SimpleNamespace(max_agents=3),
                            timeouts=SimpleNamespace(fetch_s=1, push_s=1, ls_remote_s=1)),
        mailer=Mailer(tmp_path / "rc", "o@example.com", tmp_path / "state/notify.json", log),
        worktree=lambda _: None, task_root=lambda: tmp_path,
        lock=lambda: SimpleNamespace(try_acquire=lambda _: True, release=lambda: None))


def next_run(ctx, monkeypatch):
    monkeypatch.setattr(run.setup, "ensure", lambda _: None)
    monkeypatch.setattr(run, "_settle_images", lambda _: None)
    monkeypatch.setattr(run, "_may_run", lambda *a: False)
    monkeypatch.setattr(run.publish, "catch_up", lambda _: None)
    assert run.run(ctx) == 0


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_finish_only_retries_completion_not_owner_item(tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "notes", "cron", "finishing")
    task.update(ranges=[[0, 0]])
    rel = files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": "wiki/a/topic.md", "problem": "Hiba."}]}, "r", "a", "b")
    listed = files.open_items(ctx.notes_path, "cron")
    for n in range(4):
        files.apply_closure(ctx.notes_path, f"old-{n}", [], listed)
    def content(ctx, task):
        outcome = files.apply_closure(ctx.notes_path, task.run_id, [], listed)
        return SimpleNamespace(new_owner=outcome.new_owner, question=False, result={"status": "done"})
    monkeypatch.setattr(steps, "content_steps", content)
    from school_notes2.flows import review_phases
    monkeypatch.setattr(review_phases, "advance", lambda ctx, task, notify, edits=None:
                        task.set_phase("finishing", review_complete=True))
    def git_finish(task, *args):
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(finish.git_finish, "run", git_finish)
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or False)
    assert finish.finish(ctx, task, notify_owner_items=lambda items: run.owner_items(ctx, task, items)) == "done"
    assert files.read_items(ctx.notes_path, rel) == {"R1": "owner"}
    assert list(read_json(pending.path(ctx))) == [f"completion:{task.run_id}:done"]
    assert len(deliveries) == 1
    assert_suppressed(log, "review_owner:")
    # A fresh context and no open task: the next run still retries the notice.
    ctx = context(tmp_path, log, learner)
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    next_run(ctx, monkeypatch)
    next_run(ctx, monkeypatch)
    assert len(deliveries) == 2 and read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_failed_completion_notices_retry_after_done(tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "notes", "cron", "done")
    task.update(ranges=[[0, 0]], repair_owner_item="docs/review/run-repair.md",
                repair_topic="wiki/a/topic.md")
    write_json(task.dir / "result-1.json", {"status": "done", "owner_notes": ["Indok és javaslat."]})
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: False)
    report.completion(ctx, task)
    assert len(read_json(pending.path(ctx))) == 1
    assert_suppressed(log, "repair_owner:")
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    next_run(context(tmp_path, log, learner), monkeypatch)
    next_run(context(tmp_path, log, learner), monkeypatch)
    assert len(deliveries) == 1 and read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("after_receipt", [False, True])
def test_pending_notice_resumes_across_delivery_boundaries(tmp_path, log, monkeypatch, after_receipt):
    ctx = context(tmp_path, log, "barna")
    notice = Notice(ctx.name, "completion:test:done", "run", "finish", "kész", "A futás elkészült.", "")
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    original = Mailer.send_once
    def crash(self, notice):
        if after_receipt:
            original(self, notice)
        raise RuntimeError("interrupted")
    monkeypatch.setattr(Mailer, "send_once", crash)
    with pytest.raises(RuntimeError):
        pending.send(ctx, notice)
    assert read_json(pending.path(ctx))
    monkeypatch.setattr(Mailer, "send_once", original)
    next_run(context(tmp_path, log, "barna"), monkeypatch)
    assert len(delivered) == 1 and read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_legacy_scope_owner_queue_is_drained_without_item_mail(tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    owner = Notice(learner, "scope_owner:report:R1", "run", "finish", "owner", "Tétel.", "")
    completion = Notice(learner, "completion:run:done", "run", "finish", "kész", "Kész.", "")
    write_json(pending.path(ctx), {n.kind: asdict(n) for n in (owner, completion)})
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    next_run(ctx, monkeypatch)
    next_run(ctx, monkeypatch)
    assert len(delivered) == 1 and "Kész." in delivered[0].get_content()
    assert read_json(pending.path(ctx)) == {}
    assert_suppressed(log, owner.kind)
