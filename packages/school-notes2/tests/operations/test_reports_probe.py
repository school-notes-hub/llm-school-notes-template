import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from school_notes2.flows import context, operational_report, status
from school_notes2.llm import quota
from school_notes2.llm.quota import probe as real_probe
from school_notes2.notify import Mailer, Notice, render
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.operations.test_round import cfg  # noqa: F401
from tests.operations.test_quota_timeouts import world  # noqa: F401


def test_probe_uses_correct_home_no_model_or_secret_logging(world, monkeypatch):
    ctx, task, call, _ = world
    commands = []
    monkeypatch.setattr("school_notes2.llm.launch.remove_stale", lambda *a: None)
    def execute(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(returncode=0, stdout=b'{"remaining":12,"reset":"next"}')
    monkeypatch.setattr(subprocess, "run", execute)
    assert real_probe(ctx, call)["remaining"] == 12
    argv = commands[0]
    assert "sn-agent-home-third-writer:/home/agent" in argv
    assert argv[-4:-2] == ["python3", "-c"]
    assert argv[-1] == "codex"
    assert "account/rateLimits/read" in argv[-2]
    assert "thread/start" not in argv[-2]
    reviewer = replace(call, role_name="reader-1", harness=replace(call.harness, name="claude-review"))
    real_probe(ctx, reviewer)
    assert "sn-agent-home-third-reviewer:/home/agent" in commands[-1]


@pytest.mark.parametrize("response", [b'not json token-secret', b'{}', b'{"remaining":0}', b'{"remaining":true,"reset":"x"}'])
def test_probe_failures_unknown_never_zero(world, monkeypatch, response):
    ctx, task, call, _ = world
    monkeypatch.setattr("school_notes2.llm.launch.remove_stale", lambda *a: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=response))
    assert real_probe(ctx, call) == {"remaining": None, "reset": None}


def test_probe_timeout_cleanup_unknown(world, monkeypatch):
    ctx, task, call, _ = world
    cleaned = []
    monkeypatch.setattr("school_notes2.llm.launch.remove_stale", lambda name: cleaned.append(name))
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("probe", 70)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert real_probe(ctx, call)["remaining"] is None
    assert len(cleaned) == 2


def test_mail_dedup_across_learners_windows_and_days(world, monkeypatch):
    ctx, task, call, _ = world
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    cache = {"codex": {"remaining": 1, "reset": "week-1"}}
    for name in ctx.cfg.students:
        other = context.make(ctx.cfg, name, console=False)
        with pytest.raises(quota.WaitingQuota):
            quota.wait(other, replace(call, learner=name), cache)
    assert len(deliveries) == 1
    cache["codex"]["reset"] = "week-2"
    with pytest.raises(quota.WaitingQuota):
        quota.wait(ctx, call, cache)
    assert len(deliveries) == 2


def test_completion_full_body_threshold_and_resume(world, monkeypatch):
    ctx, task, _, notices = world
    task.update(packages=[{"id": "package"}], active_seconds=590, inspection_units=[])
    write_json(task.dir / "report.json", {"mode": "repair", "owner_notes": ["magyarázat " * 100]})
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: 10)
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert not notices  # exactly 600 is not longer than ten minutes
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: 11)
    operational_report.ended(ctx, "run", 10, {task.run_id: True})
    assert not notices  # an unfinished invocation never sends a summary
    task = phase.load(task.dir)
    task.set_phase("done")
    operational_report.ended(ctx, "run", 10, {task.run_id: True})
    assert len(notices) == 1
    assert read_json(task.dir / "report.json")["időtartam_s"] == 602
    body = render(notices[0], "owner@example.test").get_content()
    assert len(body) > 1000 and "keretállapot" in body and "owner_notes" in body
    assert "⏳-jelzések" in body and "időtúllépések" in body
    assert notices[0].kind == f"completion:{task.run_id}:done"


def test_status_only_reads_operations_and_quota(world):
    ctx, task, call, _ = world
    task.set_phase("waiting_quota", quota_phase="writing")
    write_json(ctx.cfg.state_dir / "quota.json", {"codex": {"remaining": 1, "last_known": {"remaining": 1}}})
    write_json(ctx.cfg.state_dir / "round.json", {"status": "running"})
    summary = status.summary(ctx)
    assert summary["open"][0]["quota_phase"] == "writing"
    assert summary["quota"]["codex"]["remaining"] == 1
    assert "waiting_quota" in status.render(summary)
    assert summary["round"]["status"] == "interrupted"
    assert read_json(ctx.cfg.state_dir / "round.json")["status"] == "running"


def test_unknown_preserves_last_known_and_daily_mail(world, monkeypatch):
    ctx, task, call, _ = world
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    quota.check(ctx, call, False, {})
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": None, "reset": None})
    quota.check(ctx, call, False, {})
    quota.check(ctx, call, False, {})
    state = read_json(ctx.cfg.state_dir / "quota.json")["codex"]
    assert state["remaining"] is None and state["last_known"]["remaining"] == 90
    assert len(deliveries) == 1


def test_claude_401_never_emits_token(monkeypatch):
    import urllib.error
    from school_notes2.llm import quota_probe
    from pathlib import Path
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: '{"claudeAiOauth":{"accessToken":"private-test-token"}}')
    monkeypatch.setattr(quota_probe.subprocess, "check_output", lambda *a, **kw: "2.1.7 (Claude Code)")
    def fail(request, timeout):
        assert request.get_header("User-agent") == "claude-code/2.1.7"
        assert request.get_header("Anthropic-beta") == "oauth-2025-04-20"
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
    monkeypatch.setattr(quota_probe.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=fail))
    with pytest.raises(urllib.error.HTTPError) as caught:
        quota_probe.claude()
    assert "private-test-token" not in str(caught.value)


def test_detached_finish_uses_inherited_timing_without_double_count(world, monkeypatch):
    from school_notes2.flows.operation import TIMING
    ctx, task, _, notices = world
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: 650)
    token = TIMING.set((0, {}))
    try:
        task.set_phase("done")
        operational_report.at_finish(ctx, task, {"mode": "chat"})
        operational_report.ended(ctx, "chat", 0, {task.run_id: True})
    finally:
        TIMING.reset(token)
    assert phase.load(task.dir).get("active_seconds") == 650
    assert all(n.kind.endswith(":done") for n in notices)


def test_report_distinguishes_changed_pages_context_and_historical_findings(world, monkeypatch):
    ctx, task, call, _ = world
    ctx.notes_path.mkdir(parents=True)
    task.update(inspection_report="docs/review/current.md",
                inspection_changed=["wiki/m/topic.md", "wiki/assets/a.png"],
                inspection_all_units=[{"topic": "wiki/m/topic.md", "pages": ["wiki/m/topic.md", "wiki/m/lesson.md"]}],
                open_review_items=[{"file": "docs/review/previous.md", "item_id": "R1"}],
                reader_owner_notes=["Lektori észrevétel."])
    monkeypatch.setattr(operational_report.relations, "inventory", lambda repo: {"items": {
        "docs/review/current.md#R1": {"file": "wiki/m/topic.md", "status": "open"},
        "docs/review/current.md#R2": {"file": "wiki/m/topic.md", "status": "disagree"},
        "docs/review/previous.md#R1": {"file": "wiki/m/topic.md", "status": "fixed"},
        "docs/review/previous.md#R2": {"file": "wiki/m/topic.md", "status": "fixed"}}})
    write_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", [
        {"run_id": task.run_id + "-fix-a1", "role": "writer"}, {"run_id": "other", "role": "writer"}])
    result = operational_report.completed(ctx, task, {"mode": "run"}, 60)
    assert result["változott oldalak"] == ["wiki/m/topic.md"]
    topic = result["témák"][0]
    assert (topic["leletek"], topic["lezárt"], topic["vitatott"], topic["nyitott"]) == (3, 1, 1, 1)
    assert result["owner_notes"] == ["Lektori észrevétel."]
    assert len(result["időtúllépések"]) == 1


def test_vm_alert_only_once_daily(world, monkeypatch):
    from school_notes2.flows import operation
    ctx, task, _, _ = world
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    lock = operation.vm_lock(ctx.cfg)
    assert lock.try_acquire("chat")
    write_json(lock.holder_path, {"kind": "chat", "since": "2020-01-01T00:00:00+01:00"})
    try:
        for _ in range(2):
            with operation.admission(ctx, "round") as acquired:
                assert not acquired
        assert len(deliveries) == 1
        monkeypatch.setattr("school_notes2.notify.today", lambda: "2099-01-02")
        with operation.admission(ctx, "round") as acquired:
            assert not acquired
        assert len(deliveries) == 2
    finally:
        lock.release()


def test_report_metrics_group_passes_and_fix_by_role(world):
    ctx, task, _, _ = world
    for role in ("writer", "fix", "reader-1", "reader-2", "recheck"):
        (task.dir / f"transcript-{role}-1.log").write_text(json.dumps({
            "type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}))
    assert operational_report._metrics(task) == {
        "writer": {"input_tokens": 20, "output_tokens": 4},
        "reader": {"input_tokens": 30, "output_tokens": 6}}


def test_report_figure_outcomes_excludes_no_figure(world):
    ctx, task, _, _ = world
    task.update(inspection_units=[{"topic": "wiki/a.md", "pages": ["wiki/a.md"]}],
                inspection_figures=[{"brief": {"id": fid, "page": "wiki/a.md"},
                                     "candidate": {"state": "no-figure" if fid == "none" else "candidate"}}
                                    for fid in ("accepted", "rejected", "pending", "none")],
                inspection_receipts={fid: {"review": {"figures": [{"id": fid, "verdict": verdict}]}}
                                     for fid, verdict in (("accepted", "accept"), ("rejected", "reject"))})
    assert operational_report.details(ctx, task)["témák"][0]["ábrák"] == {
        "elfogadva": 1, "elutasítva": 1, "függő": 1}


def test_claude_helper_401_returns_only_unknown(monkeypatch, capsys):
    import runpy
    import sys
    import urllib.error
    from pathlib import Path
    from school_notes2.llm import quota_probe
    monkeypatch.setattr(sys, "argv", ["quota_probe.py", "claude"])
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: '{"claudeAiOauth":{"accessToken":"secret-test-value"}}')
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "2.1.7 (Claude Code)")
    def fail(request, timeout):
        assert request.get_header("User-agent") == "claude-code/2.1.7"
        raise urllib.error.HTTPError(request.full_url, 401, "secret-test-value", {}, None)
    monkeypatch.setattr(quota_probe.urllib.request, "build_opener", lambda *a: SimpleNamespace(open=fail))
    runpy.run_path(quota_probe.__file__, run_name="__main__")
    output = capsys.readouterr()
    assert json.loads(output.out) == {"remaining": None, "reset": None}
    assert "secret-test-value" not in output.out + output.err
