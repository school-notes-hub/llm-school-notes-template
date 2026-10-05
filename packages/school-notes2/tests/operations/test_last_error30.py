"""Pre-task failures survive restart, remain visible and send one incident mail."""

from dataclasses import replace
from datetime import datetime

import pytest

from school_notes2.flows import context, last_error, nightly, operation, operational_report, run, status
from school_notes2.flows import round as scheduler
from school_notes2.log import TZ
from school_notes2.state import phase
from school_notes2.state.errors import Prerequisite
from school_notes2.state.files import read_json
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("failure", [Prerequisite, RuntimeError])
def test_setup_failure_survives_restart_and_success_clears(cfg, monkeypatch, learner, failure):
    cfg = replace(cfg, students={learner: replace(cfg.students["first"], name=learner)})
    ctx = context.make(cfg, learner, console=False)
    delivered = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, delivered)
    def broken(c):
        raise failure("private-token-must-not-appear")
    monkeypatch.setattr(run.setup, "ensure", broken)
    assert run.run(ctx) == 1
    assert not phase.all_tasks(ctx.task_root(), learner)
    restarted = context.make(cfg, learner, console=False)
    data = status.summary(restarted)
    assert data["last_error"]["at"]
    assert "utolsó hiba" in status.render(data)
    assert "private-token" not in str(data["last_error"])
    assert len(delivered) == 1
    monkeypatch.setattr(operational_report, "ended", lambda *a, **kw: None)
    @operation.entry("run")
    def skipped(c):
        return 0
    skipped(restarted)
    assert status.summary(restarted)["last_error"]
    @operation.entry("run")
    def success(c):
        phase.create(c.task_root(), c.name, "notes", "cron", "done")
        return 0
    success(restarted)
    assert status.summary(restarted)["last_error"] is None


def test_report_failure_and_round_step_are_durable_without_mail(cfg, monkeypatch):
    ctx = context.make(cfg, "first", console=False)
    delivered = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, delivered)
    def broken(*a, **kw):
        raise RuntimeError("private failure")
    monkeypatch.setattr(operational_report, "ended", broken)
    @operation.entry("run")
    def success(c):
        return 0
    success(ctx)
    assert status.summary(ctx)["last_error"]["class"] == "report_failed"
    monkeypatch.setattr(scheduler, "_step", broken)
    scheduler._cycle(cfg, [ctx], datetime(2026, 10, 5, 8, tzinfo=TZ))
    assert status.summary(ctx)["last_error"]["class"] == "round_step"
    assert len(delivered) == 2  # report failure and run failure; no nightly retry


def test_last_error_write_is_replay_safe_after_crash(cfg, monkeypatch):
    ctx = context.make(cfg, "first", console=False)
    original = last_error.write_json
    def crash(path, data):
        original(path, data)
        raise KeyboardInterrupt()
    monkeypatch.setattr(last_error, "write_json", crash)
    with pytest.raises(KeyboardInterrupt):
        last_error.record(ctx, "run", "prerequisite")
    assert read_json(cfg.state_dir / ctx.name / "last-error.json")["class"] == "prerequisite"
    monkeypatch.setattr(last_error, "write_json", original)
    last_error.record(ctx, "run", "prerequisite")
    assert status.summary(context.make(cfg, ctx.name, console=False))["last_error"]
