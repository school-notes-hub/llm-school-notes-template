from dataclasses import replace
from datetime import datetime

import pytest

from school_notes2.flows import context, operation, status_text
from school_notes2.flows import round as scheduler
from school_notes2.log import TZ
from school_notes2.state import phase
from school_notes2.state.files import write_json
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_running_clock_and_minutes_use_current_invocation(cfg, learner):
    cfg = replace(cfg, students={learner: replace(cfg.students["first"], name=learner)})
    ctx = context.make(cfg, learner, console=False)
    now = datetime(2026, 10, 5, 11, 33, tzinfo=TZ)
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "writing")
    task.data["created"] = now.replace(hour=8).isoformat()
    task.update(active_seconds=7200, active_at_resume=3600,
                resumed_at=now.replace(hour=10).isoformat())
    write_json(cfg.state_dir / learner / "active.json", {"kind": "run",
               "started": now.replace(minute=30).isoformat(), "baseline": {task.run_id: 7200}})
    lock = ctx.lock()
    lock.acquire("run")
    try:
        text = status_text.overview(ctx, now)
        assert "fut 11:30 óta, írás fázis, 3. perc" in text
    finally:
        lock.release()


def test_round_pending_matches_actual_order_including_nightly(cfg, monkeypatch):
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 5, 8, tzinfo=TZ))
    seen = []
    def check(ctx):
        pending = [name for name in cfg.students if status_text.round_pending(context.make(cfg, name, console=False))]
        seen.append((ctx.name, pending))
        for name in pending:
            other = context.make(cfg, name, console=False)
            assert "szabad, a most futó körben következik" in status_text.overview(other)
    monkeypatch.setattr(scheduler.nightly, "nightly", check)
    monkeypatch.setattr(scheduler.run, "run", check)
    scheduler.round(cfg)
    names = list(cfg.students)
    assert [p for _, p in seen] == [names, names, names, names, names[1:], names[2:]]
    for name in names:
        assert "szabad, következő kör" in status_text.overview(context.make(cfg, name, console=False))


@pytest.mark.parametrize("held, kind, state", [(False, "round", "running"),
                                              (True, "chat", "running"), (True, "round", "done")])
def test_stale_or_nonround_lock_does_not_claim_pending(cfg, held, kind, state):
    ctx = context.make(cfg, "second", console=False)
    write_json(cfg.state_dir / "round.json", {"status": state, "pending_learners": ["second"]})
    lock = operation.vm_lock(cfg)
    if held:
        lock.acquire(kind)
    try:
        assert not status_text.round_pending(ctx)
    finally:
        lock.release()
