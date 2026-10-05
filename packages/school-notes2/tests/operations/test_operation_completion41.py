"""Clock-based retry and visible, assignment-bound stops."""

from datetime import datetime, timedelta

import pytest

from school_notes2.flows import context, policy, run, transient_retry
from school_notes2.state import phase
from school_notes2.state.errors import Transient
from tests.operations.test_round import cfg


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
