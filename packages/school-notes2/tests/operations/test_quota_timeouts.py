import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from school_notes2.config import Harness, Role
from school_notes2.flows import context, operation, policy, run as run_flow, clear
from school_notes2.llm import launch, quota, quota_probe, timeouts
from school_notes2.state import phase
from school_notes2.state.errors import WaitingQuota
from tests.operations.test_round import cfg  # noqa: F401
from tests.conftest import assert_suppressed, recording_mailer


@pytest.fixture
def world(cfg, monkeypatch):
    ctx = context.make(cfg, "third", console=False)
    notices = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, notices)
    role = Role("codex", "fake", "high", 7200)
    harness = Harness("codex", [], [], [])
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    run = launch.RoleRun(ctx.name, task.run_id, "writer", role, harness, "image", launch.Mounts(),
                         task.dir / "result.json", "result", task.dir, grade=9)
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 90, "reset": "next-week"})
    return ctx, task, run, notices


@pytest.mark.parametrize("remaining,blocked", [(2, True), (0, True), (2.01, False), (None, False)])
def test_pre_call_gate_once_per_round_manual_and_unknown(world, monkeypatch, remaining, blocked):
    ctx, task, run, notices = world
    probes, calls = [], []
    monkeypatch.setattr(quota, "probe", lambda *a: probes.append(1) or {"remaining": remaining, "reset": "next"})
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: calls.append(1))
    with operation.scope(ctx):
        for _ in range(2):
            if blocked:
                with pytest.raises(WaitingQuota):
                    launch.run_headless(run, log=ctx.log, snapshot=lambda: None)
            else:
                launch.run_headless(run, log=ctx.log, snapshot=lambda: None)
    assert len(probes) == 1 and len(calls) == (0 if blocked else 2)
    with operation.scope(ctx, manual=True):
        launch.run_headless(run, log=ctx.log, snapshot=lambda: None)
    assert len(probes) == 1
    if remaining is None:
        assert_suppressed(ctx.log, "quota_unknown:codex")
    assert not notices


def test_quota_resume_keeps_phase_and_no_bad_work_strike(world, monkeypatch):
    ctx, task, call, _ = world
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 1, "reset": "next"})
    for _ in range(2):
        with operation.scope(ctx):
            with pytest.raises(WaitingQuota) as caught:
                launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
        policy.on_error(caught.value, task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
        task = phase.load(task.dir)
        assert task.phase == "waiting_quota" and task.get("quota_phase") == "writing"
        assert task.data["llm_failures"] == 0 and task.data["retries"] == 0
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 80, "reset": "new-window"})
    monkeypatch.setattr(run_flow.fetch_flow, "advance", lambda *a: None)
    monkeypatch.setattr(run_flow.writer, "run_ranges", lambda *a: "done")
    monkeypatch.setattr(run_flow.handlers, "build", lambda *a: None)
    monkeypatch.setattr(run_flow.finish_flow, "finish", lambda c, t, **kw: t.set_phase("done"))
    with operation.scope(ctx):
        run_flow.advance(ctx, task)
    assert phase.load(task.dir).phase == "done"


def test_mid_call_quota_manual_still_stops_and_blocks_round(world, monkeypatch):
    ctx, task, call, notices = world
    def fail(*a, **kw):
        raise WaitingQuota("exhausted")
    monkeypatch.setattr(launch, "_admitted", fail)
    cache = {}
    with operation.scope(ctx, manual=True, cache=cache), pytest.raises(WaitingQuota):
        launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
    assert cache["codex"]["remaining"] == 0 and not notices
    assert_suppressed(ctx.log, "quota:codex")


def test_timeout_streak_not_bad_work_success_resets_and_clear(world, monkeypatch):
    ctx, task, call, notices = world
    def fail(*a, **kw):
        raise launch.TimedOut("timeout")
    monkeypatch.setattr(launch, "_admitted", fail)
    for count in (1, 2):
        with operation.scope(ctx), pytest.raises(launch.TimedOut) as caught:
            launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
        policy.on_error(caught.value, task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
        task = phase.load(task.dir)
        assert bool(task.data["needs_owner"]) == (count == 2)
        assert task.data["llm_failures"] == 0
        assert timeouts.counter(ctx, call)["count"] == count
    assert len(notices) == 1
    assert "időtúllépés (jegyzetíró)" in notices[0].get_content()
    clear.clear(ctx, "writer", "continue")
    assert not phase.load(task.dir).data["needs_owner"]
    with operation.scope(ctx), pytest.raises(launch.TimedOut):
        launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: None)
    with operation.scope(ctx):
        launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
    assert timeouts.counter(ctx, call)["count"] == 0


def test_reader_streak_shared_between_passes_isolated_from_learner_and_writer(world, monkeypatch):
    ctx, task, call, _ = world
    reader = replace(call, role_name="reader-1")
    timeouts.record(ctx, reader)
    timeouts.record(ctx, replace(reader, role_name="recheck"))
    assert timeouts.blocked(ctx, reader) and not timeouts.blocked(ctx, call)
    other = context.make(ctx.cfg, "first", console=False)
    assert not timeouts.blocked(other, reader)
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: pytest.fail("suspended role launched"))
    with operation.scope(ctx), pytest.raises(launch.Suspended):
        launch.run_headless(reader, log=ctx.log, snapshot=lambda: None)
    assert timeouts.counter(ctx, reader)["count"] == 2


@pytest.mark.parametrize("stage,role,word", [("reader-1", "reader", "olvasó-lektor"),
                                             ("recheck", "reader", "olvasó-lektor"),
                                             ("figure-review", "figure-review", "ábraellenőr")])
def test_suspended_checking_role_stops_the_run_with_one_mail(world, monkeypatch, stage, role, word):
    """Fix-49/2 (REJT-16): the second timeout of a checking role stops the run for the owner,
    like the writer's; the run does not go on with every page unchecked."""
    ctx, task, call, notices = world
    check = replace(call, role_name=stage)
    def fail(*a, **kw):
        raise launch.TimedOut("timeout")
    monkeypatch.setattr(launch, "_admitted", fail)
    with operation.scope(ctx), pytest.raises(launch.TimedOut):
        launch.run_headless(check, log=ctx.log, snapshot=lambda: None)
    with operation.scope(ctx), pytest.raises(launch.Suspended) as caught:
        launch.run_headless(check, log=ctx.log, snapshot=lambda: None)
    assert not isinstance(caught.value, launch.TimedOut)   # the check calls do not catch it
    policy.on_error(caught.value, task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
    task = phase.load(task.dir)
    assert task.data["needs_owner"]["class"] == "timeout"
    assert f"status --clear {ctx.name} {role} --continue" in task.data["needs_owner"]["todo"]
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: pytest.fail("suspended role launched"))
    with operation.scope(ctx), pytest.raises(launch.Suspended):
        launch.run_headless(check, log=ctx.log, snapshot=lambda: None)
    assert len(notices) == 1 and f"időtúllépés ({word})" in notices[0].get_content()
    assert f"status --clear {ctx.name} {role} --continue" in notices[0].get_content()
    clear.clear(ctx, role, "continue")
    assert not phase.load(task.dir).data["needs_owner"] and not timeouts.blocked(ctx, check)


@pytest.mark.parametrize("data,expected", [
    ({"seven_day": {"utilization": 98, "resets_at": "next"}}, 2),
    ({"limits": [{"kind": "weekly_all", "percent": 90, "resets_at": "next"}]}, 10),
    ({"five_hour": {"utilization": 100}}, None), ({}, None),
    ({"seven_day": {"utilization": True, "resets_at": "next"}}, None)])
def test_claude_weekly_only(data, expected):
    assert quota_probe.weekly("claude", data)["remaining"] == expected


def test_codex_weekly_only():
    data = {"rateLimits": {"primary": {"windowDurationMins": 300, "usedPercent": 100, "resetsAt": 1},
                           "secondary": {"windowDurationMins": 10080, "usedPercent": 33, "resetsAt": 2}}}
    assert quota_probe.weekly("codex", data) == {"remaining": 67, "reset": "2"}


def test_error_detection_ignores_quoted_model_content(tmp_path):
    path = tmp_path / "transcript"
    path.write_text(json.dumps({"type": "assistant", "message": "hit your usage limit"}))
    assert not quota.exhausted(path)
    path.write_text(json.dumps({"type": "turn.failed", "error": {"code": "usage_limit_reached"}}))
    assert quota.exhausted(path)


def test_nightly_timeout_blocks_unit_not_other_topics(world):
    ctx, task, call, _ = world
    first = replace(call, role_name="reviewer", label="topic-a")
    other = replace(first, label="topic-b")
    timeouts.record(ctx, first)
    timeouts.record(ctx, first)
    assert timeouts.blocked(ctx, first) and not timeouts.blocked(ctx, other)
    timeouts.success(ctx, other)
    assert timeouts.blocked(ctx, first)


def test_suspension_saved_before_notice_recovers_on_blocked_call(world, monkeypatch):
    ctx, task, call, notices = world
    timeouts.record(ctx, call)
    with monkeypatch.context() as patch:
        original = timeouts.write_json
        def crash(path, value):
            original(path, value)
            raise KeyboardInterrupt()
        patch.setattr(timeouts, "write_json", crash)
        with pytest.raises(KeyboardInterrupt):
            timeouts.record(ctx, call)
    assert not notices and timeouts.blocked(ctx, call)
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: pytest.fail("suspended role launched"))
    for _ in range(2):
        with operation.scope(ctx), pytest.raises(launch.TimedOut):
            launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
    assert len(notices) == 1 and "a futás megállt" in notices[0].get_content()
