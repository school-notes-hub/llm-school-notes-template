"""Operational boundaries survive a controller restart without losing work."""

from dataclasses import replace
from datetime import datetime
import json

import pytest

from school_notes2.flows import chat, clear, nightly, operation, policy, round as scheduler, writer
from school_notes2.llm import launch, quota, timeouts
from school_notes2.log import TZ
from school_notes2.state import phase, safefs
from school_notes2.state.errors import WaitingQuota
from school_notes2.state.files import read_json
from tests.operations.test_round import cfg  # noqa: F401
from tests.operations.test_quota_timeouts import world  # noqa: F401


@pytest.mark.parametrize("error", [WaitingQuota, launch.TimedOut])
def test_fix_wait_never_consumes_crash_budget_or_reuses_failed_output(world, monkeypatch, error):
    ctx, task, call, _ = world
    task.update(mode="fix")
    ctx.notes_path.mkdir(parents=True)
    def fail(*args):
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
        raise error("interrupted")
    monkeypatch.setattr(writer, "_call", fail)
    for _ in range(3):
        assert writer._fix_resume(ctx, task, 1) is None
        with pytest.raises(error):
            writer._invoke(ctx, task, 1, call.role, call.harness, None)
        task = phase.load(task.dir)
        assert task.get("fix_calls") == {"1": 0}
        assert not safefs.exists(ctx.notes_path, ".school-notes/result.json")


@pytest.mark.parametrize("saved_phase", ["writing", "inspecting", "correcting", "rechecking"])
def test_t095_chat_finish_wait_and_restart(world, monkeypatch, saved_phase):
    ctx, task, _, _ = world
    task.data["mode"] = "interactive"
    task.set_phase(saved_phase, ranges=[])
    def stop(ctx, task, **kw):
        raise WaitingQuota("weekly limit")
    monkeypatch.setattr(chat.finish_flow, "finish", stop)
    assert chat.session_finish(ctx)["state"] == "waiting_quota"
    task = phase.load(task.dir)
    assert task.phase == "waiting_quota" and task.get("quota_phase") == saved_phase
    resumed = []
    def finish(ctx, task, **kw):
        resumed.append(task.phase)
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(chat.finish_flow, "finish", finish)
    assert chat.session_finish(ctx)["state"] == "done"
    assert resumed == [saved_phase]


def test_role_clear_does_not_unlock_a_different_timeout(world):
    ctx, task, _, _ = world
    task.mark_needs_owner("writer timeout", "adjust", "timeout")
    clear.clear(ctx, "reader", "continue")
    assert phase.load(task.dir).data["needs_owner"]
    clear.clear(ctx, "writer", "continue")
    assert not phase.load(task.dir).data["needs_owner"]


@pytest.mark.parametrize("stage,expected", [("reader-1", 1800), ("reader-2", 600), ("recheck", 1200)])
def test_configured_reader_keeps_stage_limits(world, monkeypatch, stage, expected):
    ctx, task, call, _ = world
    configured = replace(call.role, timeout_s=1800)
    ctx.cfg = replace(ctx.cfg, roles={"reader": configured}, harnesses={"codex": call.harness})
    seen = []
    monkeypatch.setattr(launch, "_admitted", lambda run, **kw: seen.append(run.role.timeout_s))
    with operation.scope(ctx):
        launch.run_headless(replace(call, role_name=stage), log=ctx.log, snapshot=lambda: None)
    assert seen == [expected]
    ctx.cfg = replace(ctx.cfg, roles={"reader": replace(configured, timeout_s=1900,
                                                       list_timeout_s=700, recheck_timeout_s=1300)})
    with operation.scope(ctx):
        launch.run_headless(replace(call, role_name=stage), log=ctx.log, snapshot=lambda: None)
    assert seen[-1] == expected + 100


def test_t095_nightly_quota_then_timeout_preserves_range_until_owner_clears(world, monkeypatch):
    ctx, notes, call, notices = world
    task = phase.create(ctx.task_root(), ctx.name, "review", "cron", "reviewing")
    task.update(T="pinned-head", base="pinned-base", commits=["pinned-head"])
    ctx.cfg = replace(ctx.cfg, roles={"reviewer": call.role}, harnesses={"codex": call.harness})
    monkeypatch.setattr(nightly.setup, "ensure", lambda c: None)
    monkeypatch.setattr(nightly.cleanup, "old_tasks", lambda c: None)
    monkeypatch.setattr(nightly, "_prerequisites", lambda c: None)
    monkeypatch.setattr(nightly.review, "resume_prepared", lambda *a: None)
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 2, "reset": "week"})
    assert nightly.nightly(ctx) == 1
    task = phase.load(task.dir)
    assert task.phase == "waiting_quota" and task.get("quota_phase") == "reviewing"
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 20, "reset": "next"})
    def timeout(*a, **kw):
        raise launch.TimedOut("timeout")
    monkeypatch.setattr(launch, "_admitted", timeout)
    for count in (1, 2):
        assert nightly.nightly(ctx, manual=True) == 0
        task = phase.load(task.dir)
        assert task.phase == "reviewing" and task.get("T") == "pinned-head"
        assert bool(task.data["needs_owner"]) == (count == 2)
        state = read_json(timeouts.path(ctx))
        assert state["reviewer_units"]["pinned-head"]["count"] == count
    clear.clear(ctx, "reviewer", "continue")
    assert scheduler.due(ctx, datetime(2026, 10, 4, 1, tzinfo=TZ), {})
    assert phase.load(task.dir).get("base") == "pinned-base"


def test_timeout_state_survives_crash_before_task_error_policy(world, monkeypatch):
    ctx, task, call, _ = world
    timeouts.record(ctx, call)
    timeouts.record(ctx, call)
    # Simulate power loss before policy marked the task: launch still cannot run.
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: pytest.fail("third timeout call"))
    with operation.scope(ctx), pytest.raises(launch.TimedOut) as caught:
        launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
    policy.on_error(caught.value, task=phase.load(task.dir), student=ctx.name,
                    step="run", log=ctx.log, mailer=ctx.mailer)
    assert phase.load(task.dir).data["needs_owner"]["class"] == "timeout"


def test_claude_rate_limit_error_message_is_quota_but_ordinary_text_is_not(tmp_path):
    path = tmp_path / "transcript"
    event = {"type": "assistant", "message": {"content": [{"text": "You've hit your limit"}]}}
    path.write_text(json.dumps(event))
    assert not quota.exhausted(path)
    path.write_text(json.dumps({**event, "error": "rate_limit"}))
    assert quota.exhausted(path)


def test_round_quota_cache_shared_across_three_learners_and_refreshed(world, monkeypatch):
    ctx, task, call, _ = world
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 8, tzinfo=TZ))
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda c: None)
    seen = []
    monkeypatch.setattr(quota, "probe", lambda c, r: seen.append(launch.family(r.harness))
                        or {"remaining": 80, "reset": "week"})
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: None)
    @operation.entry("run")
    def run(ctx):
        for family in ("codex", "claude-review"):
            launch.run_headless(replace(call, learner=ctx.name, harness=replace(call.harness, name=family)),
                                log=ctx.log, snapshot=lambda: None)
    monkeypatch.setattr(scheduler.run, "run", run)
    scheduler.round(ctx.cfg)
    scheduler.round(ctx.cfg)
    assert seen == ["codex", "claude", "codex", "claude"]


def test_new_night_does_not_inherit_legacy_d85_range_halving(world, monkeypatch):
    ctx, task, _, _ = world
    task.update(timed_out=True, commits=["one", "two"])
    options = []
    monkeypatch.setattr(nightly.review, "prepare", lambda *a, **kw: options.append(kw))
    nightly._prepare(ctx, [task])
    assert "previous" not in options[0]


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("stage,field", [("reader-1", "timeout_s"), ("reader-2", "list_timeout_s"),
                                         ("recheck", "recheck_timeout_s")])
def test_reader_call_timeout_comes_only_from_role(world, monkeypatch, configured, stage, field):
    from school_notes2.config import Role
    from school_notes2.flows import inspection
    from school_notes2.reader import calls
    from types import SimpleNamespace
    ctx, task, call, _ = world
    roles = {"reviewer": replace(call.role, timeout_s=5400)}
    if configured:
        roles["reader"] = replace(call.role, timeout_s=1901, list_timeout_s=701, recheck_timeout_s=1301)
    ctx.cfg = replace(ctx.cfg, roles=roles, harnesses={"codex": call.harness})
    expected = getattr(roles["reader"], field) if configured else getattr(Role, field)
    seen = []
    monkeypatch.setattr(calls.contracts, "check", lambda *a, **kw: {})
    def invoke(run, **kw):
        seen.append(run.role.timeout_s)
        return SimpleNamespace(output={})
    calls.run(ctx.notes_path, ctx.notes_path, task.dir / stage, stage, {}, inspection.role(ctx, task),
              log=ctx.log, invoke=invoke)
    assert seen == [expected]
