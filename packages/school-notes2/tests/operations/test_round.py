from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from school_notes2.config import Config, Student, ConfigError
from school_notes2.flows import context, operation, round as scheduler
from school_notes2.log import TZ
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.conftest import assert_suppressed, recording_mailer


@pytest.fixture
def cfg(tmp_path):
    students = {n: Student(n, "repo", tmp_path / "key", "site", tmp_path / "key", "drive", 9)
                for n in ("third", "first", "second")}
    return Config(tmp_path, tmp_path / "secrets", tmp_path / "known", "owner@example.test",
                  "Owner", "owner@example.test", students, {}, {})


def test_round_three_students_nightly_first_table_order(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 8, tzinfo=TZ))
    def night(ctx):
        calls.append(("night", ctx.name))
        phase.create(ctx.task_root(), ctx.name, "review", "cron", "done")
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    monkeypatch.setattr(scheduler.run, "run", lambda c: calls.append(("run", c.name)))
    scheduler.round(cfg)
    assert calls == [(k, n) for k in ("night", "run") for n in cfg.students]
    calls.clear()
    scheduler.round(cfg)
    assert calls == [("run", n) for n in cfg.students]


def test_owner_example_0800_0930_0940_no_backlog(cfg, monkeypatch):
    clock = [datetime(2026, 10, 4, 8, tzinfo=TZ)]
    monkeypatch.setattr(scheduler, "now", lambda: clock[0])
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda c: None)
    calls = []
    durations = iter([45, 45, 0, 5, 5, 0])
    def run(ctx):
        calls.append((ctx.name, clock[0].strftime("%H:%M")))
        clock[0] += timedelta(minutes=next(durations))
        token = operation.VM_HELD.set(False)  # competing process
        try:
            assert scheduler.round(cfg) == 0
        finally:
            operation.VM_HELD.reset(token)
    monkeypatch.setattr(scheduler.run, "run", run)
    scheduler.round(cfg)
    assert [t for _, t in calls] == ["08:00", "08:45", "09:30", "09:30", "09:35", "09:40"]
    assert clock[0].strftime("%H:%M") == "09:40"


def test_crossing_hour_not_elapsed_sixty_minutes(cfg, monkeypatch):
    times = iter([datetime(2026, 10, 4, 8, 59, tzinfo=TZ), datetime(2026, 10, 4, 9, 1, tzinfo=TZ),
                  datetime(2026, 10, 4, 9, 1, tzinfo=TZ), datetime(2026, 10, 4, 9, 2, tzinfo=TZ)])
    monkeypatch.setattr(scheduler, "now", lambda: next(times))
    cycles = []
    monkeypatch.setattr(scheduler, "_cycle", lambda *a: cycles.append(a[-1]))
    scheduler.round(cfg)
    assert len(cycles) == 2


def test_crash_resumes_review_before_other_steps(cfg, monkeypatch):
    from school_notes2.notify import Mailer
    monkeypatch.setattr(Mailer, "_deliver", lambda *a: True)
    calls = []
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 8, tzinfo=TZ))
    def night(ctx):
        task = phase.open_task(ctx.task_root(), ctx.name, "review")
        if task is None:
            phase.create(ctx.task_root(), ctx.name, "review", "cron", "prepared")
            raise RuntimeError("power loss")
        calls.append(ctx.name)
        task.set_phase("done")
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    monkeypatch.setattr(scheduler.run, "run", lambda c: None)
    scheduler.round(cfg)
    assert not read_json(cfg.state_dir / "round.json")["nightly_started"]
    scheduler.round(cfg)
    assert calls == list(cfg.students)
    assert read_json(cfg.state_dir / "round.json")["status"] == "done"


def test_quota_review_due_before_nightly_time_and_timeout_waits(cfg):
    ctx = context.make(cfg, "third", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "review", "cron", "waiting_quota")
    task.update(quota_phase="reviewing")
    now = datetime(2026, 10, 4, 1, tzinfo=TZ)
    assert scheduler.due(ctx, now, {ctx.name: "2026-10-04"})
    task.update(timeout_day="2026-10-04")
    assert not scheduler.due(ctx, now, {})


def test_vm_lock_shared_with_direct_entries_and_alert(cfg, monkeypatch):
    ctx = context.make(cfg, "third", console=False)
    messages = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, messages)
    lock = operation.vm_lock(cfg)
    assert lock.try_acquire("chat")
    write_json(lock.holder_path, {"kind": "chat", "since": "2020-01-01T00:00:00+01:00"})
    called = []
    @operation.entry("run")
    def run(ctx):
        called.append(1)
    assert run(ctx) == 0
    assert not called and len(messages) == 1
    from school_notes2.notify import incidents
    assert incidents.active(operation.vm_context(ctx))[0]["class"] == "lock_held"
    lock.release()
    assert operation.vm_lock(cfg).probe()


def test_nightly_time_validation(cfg):
    for value in ("24:00", "3:15", "03:99", None, 315):
        with pytest.raises(ConfigError):
            replace(cfg, nightly_after=value)


def test_skipped_learner_stays_due_and_owner_stop_is_not_restarted(cfg, monkeypatch):
    ctx = context.make(cfg, "third", console=False)
    clock = datetime(2026, 10, 4, 8, tzinfo=TZ)
    monkeypatch.setattr(scheduler, "now", lambda: clock)
    calls = []
    def night(ctx):
        calls.append(ctx.name)
        phase.create(ctx.task_root(), ctx.name, "review", "cron", "done")
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    monkeypatch.setattr(scheduler.run, "run", lambda c: None)
    monkeypatch.setattr(scheduler.run, "_lock_alert", lambda *a: None)
    lock = ctx.lock()
    assert lock.try_acquire("finish")
    try:
        scheduler.round(cfg)
        assert calls == ["first", "second"]
        assert "third" not in read_json(cfg.state_dir / "round.json")["nightly_started"]
    finally:
        lock.release()
    scheduler.round(cfg)
    assert calls == ["first", "second", "third"]
    task = phase.create(ctx.task_root(), ctx.name, "review", "cron", "reviewing")
    task.mark_needs_owner("timeout", "adjust", "timeout")
    assert not scheduler.due(ctx, clock + timedelta(days=1), {})


def test_vm_lock_inherited_by_detached_child_and_no_learner_name_collision(cfg):
    import os
    from school_notes2.state.lock import StudentLock
    lock = operation.vm_lock(cfg)
    assert lock.try_acquire("chat")
    learner_lock = StudentLock(cfg.state_dir, "vm")
    assert learner_lock.try_acquire("run")
    learner_lock.release()
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(write_end)
        os.read(read_end, 1)
        os._exit(0)
    os.close(read_end)
    lock.release()
    try:
        assert not operation.vm_lock(cfg).probe()
    finally:
        os.close(write_end)
        os.waitpid(pid, 0)
    assert operation.vm_lock(cfg).probe()
