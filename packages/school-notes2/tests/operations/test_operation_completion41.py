"""Clock-based retry and visible, assignment-bound stops."""

from datetime import datetime, timedelta

import pytest

from school_notes2.flows import context, fix_progress, operational_report, policy, run, set_aside, transient_retry
from school_notes2.notify import incidents, pending
from school_notes2.review import files
from school_notes2.state import phase
from school_notes2.state.errors import Transient
from school_notes2.state.files import read_json
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["first", "second"])
@pytest.mark.parametrize("crash", [False, True])
def test_stalled_mail_status_and_actual_assignment(cfg, monkeypatch, learner, crash):
    ctx = context.make(cfg, learner, console=False)
    ctx.notes_path.mkdir(parents=True)
    path = files.write_review(ctx.notes_path, "2026-10-05", {"findings": [
        {"id": f"R{i}", "file": "wiki/a/topic.md", "problem": "Hiba."} for i in range(1, 4)],
        "verdict": "changes"}, "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    items = files.open_items(ctx.notes_path, "cron")
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "review_ready")
    task.update(mode="fix", open_review_items=items, fix_work=[path + "#R3"],
                assigned_work=[path + "#R1"], correction_work=[path + "#R2"])
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    original = set_aside.no_progress_notice
    if crash:
        monkeypatch.setattr(set_aside, "no_progress_notice", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            fix_progress.record(ctx, task)
        monkeypatch.setattr(set_aside, "no_progress_notice", original)
        task = phase.load(task.dir)
    fix_progress.record(ctx, task)
    assert set_aside.blocked(ctx) == {path + "#R1", path + "#R2"}
    task.set_phase("done")
    operational_report.completed(ctx, task, {}, 10)
    policy.on_success(task)
    pending.retry(ctx)
    pending.retry(ctx)
    assert len(sent) == 2
    assert all("nem haladt" in m.get_content() and "félretéve" in m.get_content() for m in sent)
    assert all("kész" not in m.get_content() for m in sent)
    assert len(incidents.active(ctx)) == 1
    from school_notes2.flows import status_text, work_pending
    assert "vár" in work_pending.completion(ctx)[0]
    assert operational_report.terminal(task) == "no_progress"


@pytest.mark.parametrize("kind", ["program", "bad_work"])
def test_done_task_never_archived(cfg, monkeypatch, kind):
    from school_notes2.flows import operation
    from school_notes2.state.errors import BadWork
    ctx = context.make(cfg, "first", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
    task.update(mode="repair", repair_topic="wiki/a/topic.md")
    task.data["llm_failures"] = 1
    monkeypatch.setattr(set_aside, "stop", lambda *a, **kw: pytest.fail("already done"))
    with operation.scope(ctx):
        policy.on_error(RuntimeError("after done") if kind == "program" else BadWork("after done"),
                        task=task, student=ctx.name, step="run", log=ctx.log, mailer=None)
    assert not read_json(set_aside.path(ctx), {})


@pytest.mark.parametrize("learner", ["first", "second"])
def test_ten_minute_cron_waits_and_hourly_owner_probe(cfg, monkeypatch, learner):
    ctx = context.make(cfg, learner, console=False)
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "writing")
    at = datetime(2026, 10, 5, 10, tzinfo=transient_retry.TZ)
    monkeypatch.setattr(transient_retry, "now", lambda: at)
    monkeypatch.setattr(phase, "now_iso", lambda: at.isoformat())
    def fail():
        policy.on_error(Transient("GitHub"), task=task, student=learner, step="run", log=ctx.log, mailer=None)
    fail()
    for minutes in (10, 20):
        at = at.replace(minute=minutes)
        assert not run._may_run(ctx, phase.load(task.dir))
        fail()  # Even duplicate error handling within the interval cannot spend a try.
        assert task.data["retries"] == 1
    at = at.replace(minute=30)
    assert run._may_run(ctx, task)
    fail()
    assert task.data["retries"] == 2 and task.data["needs_owner"] is None
    at += timedelta(minutes=30)
    assert run._may_run(ctx, task)
    fail()
    assert task.data["needs_owner"]["class"] == "transient"
    at += timedelta(minutes=10)
    assert not run._may_run(ctx, phase.load(task.dir))
    at = at.replace(hour=12, minute=0)
    task = phase.load(task.dir)
    assert run._may_run(ctx, task)
    fail()
    assert task.data["needs_owner"]["class"] == "transient"
    at += timedelta(minutes=10)
    assert not run._may_run(ctx, phase.load(task.dir))
    at = at.replace(hour=13, minute=0)
    assert run._may_run(ctx, task)
    policy.on_success(task)
    assert task.data["needs_owner"] is None and task.data["retries"] == 0
    assert task.get("transient_after") is None


def test_progress_clears_brake_even_after_interrupted_receipt_removal(cfg, monkeypatch):
    ctx = context.make(cfg, "first", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "review_ready")
    task.update(mode="fix", no_progress=True, assigned_work=["docs/review/a.md#R1"])
    set_aside.record(ctx, task, "no-progress")
    original = set_aside.write_json
    def interrupted(*args):
        original(*args)
        raise KeyboardInterrupt
    with monkeypatch.context() as patch:
        patch.setattr(set_aside, "write_json", interrupted)
        with pytest.raises(KeyboardInterrupt):
            set_aside.progressed(ctx, task)
    task = phase.load(task.dir)
    set_aside.progressed(ctx, task)
    assert not task.get("no_progress") and not set_aside.blocked(ctx)
