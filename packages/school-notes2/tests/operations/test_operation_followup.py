"""Fix 11: daily empty nights, precise quota notices and build-time CLI version."""

import io
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from school_notes2.flows import context, round as scheduler
from school_notes2.llm import quota, quota_probe
from school_notes2.log import TZ
from school_notes2.review import nightly as review
from school_notes2.state import phase
from school_notes2.state.files import read_json
from tests.operations.test_round import cfg  # noqa: F401
from tests.operations.test_quota_timeouts import world  # noqa: F401
from tests.review.conftest import repos  # noqa: F401


def test_empty_night_then_daytime_commit_waits_until_next_day(cfg, repos, monkeypatch):
    clock = datetime(2026, 10, 4, 3, 15, tzinfo=TZ)
    calls = []
    monkeypatch.setattr(scheduler, "now", lambda: clock)
    monkeypatch.setattr(scheduler.run, "run", lambda c: 0)
    def night(ctx):
        selected = review.select(repos.repo, fetch_timeout=10)
        calls.append((ctx.name, selected))
        return 0
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    scheduler.round(cfg)
    assert calls == [(name, None) for name in cfg.students]
    head = repos.commit({"wiki/index.md": "# Új tananyag\n"})
    clock = clock.replace(hour=17, minute=0)
    scheduler.round(cfg)
    assert calls == [(name, None) for name in cfg.students]
    clock = clock.replace(day=5, hour=4)
    scheduler.round(cfg)
    assert [(name, selected.head) for name, selected in calls[3:]] == [
        (name, head) for name in cfg.students]


def test_same_day_continuation_consumes_today(cfg, monkeypatch):
    clock = datetime(2026, 10, 4, 4, tzinfo=TZ)
    monkeypatch.setattr(scheduler, "now", lambda: clock)
    monkeypatch.setattr(scheduler.run, "run", lambda c: 0)
    for name in cfg.students:
        ctx = context.make(cfg, name, console=False)
        task = phase.create(ctx.task_root(), name, "review", "cron", "prepared")
        task.data["created"] = "2026-10-04T03:15:00+02:00"
        task.save()
    calls = []
    def night(ctx):
        calls.append(ctx.name)
        phase.open_task(ctx.task_root(), ctx.name, "review").set_phase("done")
        return 0
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    scheduler.round(cfg)
    assert read_json(cfg.state_dir / "round.json")["nightly_started"] == {
        name: "2026-10-04" for name in cfg.students}
    scheduler.round(cfg)
    assert calls == list(cfg.students)


@pytest.mark.parametrize("role,work", [
    ("reviewer", "az éjszakai review"), ("writer", "a jegyzetírás"),
    ("fix", "a jegyzetírás"), ("figure", "a jegyzetírás"),
    ("reader", "a jegyzet lektorálása"), ("reader-1", "a jegyzet lektorálása"),
    ("reader-2", "a jegyzet lektorálása"), ("recheck", "a jegyzet lektorálása"),
    ("figure-review", "a jegyzet lektorálása"),
])
def test_quota_notice_names_the_work_with_correct_article(world, role, work):
    ctx, _, call, notices = world
    call = replace(call, role_name=role)
    with pytest.raises(quota.WaitingQuota) as caught:
        quota.wait(ctx, call, {"codex": {"remaining": 1, "reset": "week"}})
    assert notices[0].message == (
        f"third: codex, maradék: 1%. {work.capitalize()} áll. "
        "Visszatöltődés után onnan folytatódik.")
    assert str(caught.value) == f"codex: {work} vár. Visszatöltődés után onnan folytatódik."


@pytest.mark.parametrize("version,expected", [("2.1.7", "2.1.7"), (None, "unknown"), ("", "unknown")])
def test_claude_probe_needs_no_cli_and_preserves_quota(monkeypatch, version, expected):
    if version is None:
        monkeypatch.delenv("CLAUDE_CODE_VERSION", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_VERSION", version)
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: '{"claudeAiOauth":{"accessToken":"test-token"}}')
    monkeypatch.setattr(quota_probe.subprocess, "check_output",
                        lambda *a, **kw: pytest.fail("quota probe must not launch the CLI"))
    def respond(request, timeout):
        assert request.get_header("User-agent") == "claude-code/" + expected
        assert timeout == 25
        return io.StringIO(json.dumps({"seven_day": {"utilization": 12, "resets_at": "next-week"}}))
    monkeypatch.setattr(quota_probe.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=respond))
    assert quota_probe.weekly("claude", quota_probe.claude()) == {"remaining": 88, "reset": "next-week"}
