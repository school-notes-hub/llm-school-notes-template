"""K-1–K-9: manual admission, isolated scheduling and terminal-only notices."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime

import pytest

from school_notes2 import cli
from school_notes2.flows import chat, context, operation, operational_report, policy, repair, round as scheduler
from school_notes2.llm import launch, quota
from school_notes2.log import TZ
from school_notes2.notify import Mailer
from school_notes2.state import phase
from school_notes2.state.errors import WaitingQuota
from school_notes2.state.files import read_json, write_json
from tests.operations.test_round import cfg  # noqa: F401
from tests.operations.test_quota_timeouts import world  # noqa: F401
from tests.conftest import assert_suppressed


def test_chat_below_two_percent_and_mid_call_quota_resume(world, monkeypatch):
    ctx, task, call, notices = world
    ctx.cfg = replace(ctx.cfg, roles={"writer": call.role}, harnesses={"codex": call.harness})
    task.data["mode"] = "interactive"
    task.update(ranges=[[0, 0]])
    probes, seen = [], []
    monkeypatch.setattr(quota, "probe", lambda *a: probes.append(1) or {"remaining": 1, "reset": "week"})
    monkeypatch.setattr(chat.setup, "ensure", lambda c: None)
    monkeypatch.setattr(chat.writer, "write_inputs", lambda *a: None)
    monkeypatch.setattr(chat.handlers, "build", lambda *a, **kw: None)
    monkeypatch.setattr(chat, "mcp", lambda *a: nullcontext(task.dir))
    def interactive(**kwargs):
        assert operation.CURRENT.get()[1] is True
        seen.append(phase.load(task.dir).phase)
        if len(seen) == 1:
            raise WaitingQuota("weekly limit")
        return 0
    monkeypatch.setattr(launch, "_interactive", interactive)
    assert chat.chat(ctx, None, ask=lambda _: pytest.fail("unexpected question"), say=lambda _: None) == 1
    saved = phase.load(task.dir)
    assert saved.phase == "waiting_quota" and saved.get("quota_phase") == "writing"
    assert not notices
    assert_suppressed(ctx.log, "quota:codex")
    assert chat.chat(ctx, None, ask=lambda _: pytest.fail("unexpected question")) == 0
    assert seen == ["writing", "writing"] and not probes
    assert phase.load(task.dir).data["llm_failures"] == 0


@pytest.mark.parametrize("command", ["fetch", "finish", "repair"])
def test_host_commands_are_manual(world, monkeypatch, command):
    ctx, task, call, _ = world
    seen = []
    monkeypatch.setattr(quota, "probe", lambda *a: pytest.fail("manual command probed quota"))
    monkeypatch.setattr(launch, "_admitted", lambda *a, **kw: seen.append(operation.CURRENT.get()[1]))
    def work(*args, **kwargs):
        launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
        return {}
    if command == "repair":
        task.update(mode="repair", repair_topic="wiki/m/topic.md")
        monkeypatch.setattr(repair.setup, "ensure", lambda c: None)
        monkeypatch.setattr(chat.run_flow, "advance", work)
        args = cli._parser().parse_args([command, ctx.name, "--topic", "wiki/m/topic.md"])
    else:
        monkeypatch.setattr(chat, "session_" + command, work)
        args = cli._parser().parse_args([command, ctx.name])
    assert cli._dispatch(ctx, args) == 0
    assert seen == [True]


@pytest.mark.parametrize("args", [
    ["run", "third", "--manual"], ["nightly", "third", "--manual"],
    ["chat", "third"], ["fetch", "third"], ["finish", "third"],
    ["repair", "third", "--topic", "wiki/m/a.md"],
    ["status", "--clear", "third", "notes", "--continue"],
    ["status", "--clear", "third", "notes", "--discard"],
])
def test_busy_vm_cli_is_tempfail_with_hungarian_message(cfg, monkeypatch, capsys, args):
    monkeypatch.setattr(cli.config, "load", lambda _: cfg)
    lock = operation.vm_lock(cfg)
    assert lock.try_acquire("round")
    since = lock.holder()["since"]
    try:
        assert cli.main(args) == 75
        output = capsys.readouterr()
        assert output.out == ""
        assert "VM-zár foglalt" in output.err and since in output.err
        assert "round" in output.err and "próbáld újra a kör vége után" in output.err
        assert cli.main(["round"]) == 0
    finally:
        lock.release()
    events = [json.loads(line) for line in cfg.log_path.read_text().splitlines()]
    assert all(e["student"] == "VM" for e in events if e["action"] == "round.skip")


@pytest.mark.parametrize("failure", ["due", "before", "action", "report"])
def test_first_learner_exception_does_not_starve_others(cfg, monkeypatch, failure):
    delivered, calls = [], []
    failing = next(iter(cfg.students))
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 8, tzinfo=TZ))
    if failure in ("due", "before"):
        original = scheduler.due if failure == "due" else phase.all_tasks
        def fail(*args):
            name = args[0].name if failure == "due" else args[1]
            if name == failing:
                raise RuntimeError("broken phase")
            return original(*args)
        monkeypatch.setattr(scheduler if failure == "due" else phase,
                            "due" if failure == "due" else "all_tasks", fail)
    if failure == "report":
        def ended(ctx, *args, **kwargs):
            if ctx.name == failing:
                raise TypeError("broken report")
        monkeypatch.setattr(operational_report, "ended", ended)
    def work(ctx, kind):
        calls.append((kind, ctx.name))
        if failure == "action" and ctx.name == failing:
            raise KeyError("broken step")
    @operation.entry("nightly")
    def night(ctx):
        return work(ctx, "nightly")
    @operation.entry("run")
    def run(ctx):
        return work(ctx, "run")
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    monkeypatch.setattr(scheduler.run, "run", run)
    scheduler.round(cfg)
    scheduler.round(cfg)
    assert [(k, n) for k, n in calls if n != "third"][:4] == [
        (k, n) for k in ("nightly", "run") for n in ("first", "second")]
    assert len(delivered) == (2 if failure in ("before", "action") else 1)
    assert read_json(cfg.state_dir / failing / "last-error.json")["class"] in ("program", "round_step", "report_failed")
    if failure in ("due", "before", "action"):
        assert "third" not in read_json(cfg.state_dir / "round.json")["nightly_started"]
    assert operation.TIMING.get() is None


def test_yesterdays_review_finishes_then_todays_review_can_start(cfg, monkeypatch):
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 4, 10, tzinfo=TZ))
    monkeypatch.setattr(scheduler.run, "run", lambda c: None)
    ctx = context.make(cfg, "third", console=False)
    old = phase.create(ctx.task_root(), ctx.name, "review", "cron", "waiting_quota")
    old.data["created"] = "2026-10-03T10:00:00+02:00"
    old.save()
    write_json(cfg.state_dir / "round.json", {"nightly_started": {ctx.name: "2026-10-03"}})
    calls = []
    def night(ctx):
        task = phase.open_task(ctx.task_root(), ctx.name, "review")
        calls.append((ctx.name, task.run_id if task else "new"))
        if task:
            task.set_phase("done")
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    scheduler.round(cfg)
    assert read_json(cfg.state_dir / "round.json")["nightly_started"][ctx.name] == "2026-10-03"
    scheduler.round(cfg)
    assert [r for n, r in calls if n == ctx.name] == [old.run_id, "new"]


@pytest.mark.parametrize("kind", ["notes", "review"])
def test_three_quota_rounds_send_no_mail(world, monkeypatch, kind):
    ctx, task, call, _ = world
    if kind == "review":
        task = phase.create(ctx.task_root(), ctx.name, kind, "cron", "reviewing")
        call = replace(call, run_id=task.run_id, role_name="reviewer")
    task.update(active_seconds=720)
    delivered = []
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": 1, "reset": "week"})
    @operation.entry("nightly" if kind == "review" else "run")
    def work(ctx):
        current = phase.load(task.dir)
        if current.phase == "waiting_quota":
            current.set_phase(current.get("quota_phase"))
        try:
            launch.run_headless(call, log=ctx.log, snapshot=lambda: None)
        except WaitingQuota as exc:
            policy.on_error(exc, task=current, student=ctx.name, step="test", log=ctx.log, mailer=ctx.mailer)
    for _ in range(3):
        work(ctx)
    assert not delivered
    assert_suppressed(ctx.log, "quota:codex")
    task.reload()
    assert task.phase == "waiting_quota" and task.get("active_seconds") >= 720


@pytest.mark.parametrize("kind", ["notes", "review"])
@pytest.mark.parametrize("terminal", ["done", "needs_owner", "closed"])
def test_terminal_summaries_have_stable_receipts(world, monkeypatch, kind, terminal):
    ctx, task, _, _ = world
    if kind == "review":
        task = phase.create(ctx.task_root(), ctx.name, kind, "cron", "reviewing")
    task.update(active_seconds=720)
    delivered = []
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    if terminal == "done":
        task.set_phase("done")
    elif terminal == "needs_owner":
        task.mark_needs_owner("Megállt", "Ellenőrizd", "program")
    else:
        task.data["closed"] = True
        task.save()
    for _ in range(2):
        operational_report.ended(ctx, "nightly" if kind == "review" else "run", 0, {task.run_id: True})
    assert len(delivered) == 1
    if terminal == "closed":
        assert "elvetve; a munkája nem került ki" in delivered[0].get_content()
    if terminal == "needs_owner":
        receipts = read_json(ctx.mailer.state.with_name("notify-once.json"))
        assert len(receipts) == 1 and receipts[0].startswith(ctx.name + ":error:")
        return
    prefix = "nightly" if kind == "review" else "completion"
    assert read_json(ctx.mailer.state.with_name("notify-once.json")) == [
        f"{ctx.name}:{prefix}:{task.run_id}:{terminal}"]


def test_completed_today_task_prevents_duplicate_night_after_state_write_crash(cfg):
    ctx = context.make(cfg, "third", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "review", "cron", "done")
    task.data["created"] = "2026-10-04T08:00:00+02:00"
    task.save()
    assert not scheduler.due(ctx, datetime(2026, 10, 4, 10, tzinfo=TZ), {})
    assert scheduler.due(ctx, datetime(2026, 10, 5, 10, tzinfo=TZ), {})


def test_empty_night_never_sends_mail(cfg, monkeypatch):
    ctx = context.make(cfg, "third", console=False)
    deliveries = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: deliveries.append(msg) or True)
    @operation.entry("nightly")
    def night(ctx, result):
        return result
    for _ in range(3):
        assert night(ctx, 1) == 1
    assert not deliveries
    night(ctx, 0)
    night(ctx, 0)
    assert not deliveries


def test_vm_quota_and_lock_notice_logs_have_vm_identity(world, monkeypatch):
    ctx, _, call, _ = world
    ctx.mailer = context.make(ctx.cfg, ctx.name, console=False).mailer
    monkeypatch.setattr(Mailer, "_deliver", lambda *a: True)
    monkeypatch.setattr(quota, "probe", lambda *a: {"remaining": None, "reset": None})
    quota.check(ctx, call, False, {})
    lock = operation.vm_lock(ctx.cfg)
    assert lock.try_acquire("chat")
    write_json(lock.holder_path, {"kind": "chat", "since": "2020-01-01T00:00:00+01:00"})
    try:
        with operation.admission(ctx, "round") as acquired:
            assert not acquired
    finally:
        lock.release()
    events = [json.loads(line) for line in ctx.cfg.log_path.read_text().splitlines()]
    assert {e["action"] for e in events} >= {"quota.read", "operation.last_error", "round.skip"}
    assert all(e["student"] == "VM" for e in events if e["action"] not in ("operation.last_error", "notify.mail_once"))


@pytest.mark.parametrize("result", [None, 0])
def test_empty_night_claims_today_and_four_oclock_skips_it(cfg, monkeypatch, result):
    clock = datetime(2026, 10, 4, 3, 15, tzinfo=TZ)
    calls = []
    monkeypatch.setattr(scheduler, "now", lambda: clock)
    def night(ctx):
        calls.append(ctx.name)
        return result
    monkeypatch.setattr(scheduler.nightly, "nightly", night)
    monkeypatch.setattr(scheduler.run, "run", lambda c: 0)
    scheduler.round(cfg)
    assert read_json(cfg.state_dir / "round.json")["nightly_started"] == {
        name: "2026-10-04" for name in cfg.students}
    clock = clock.replace(hour=4, minute=0)
    scheduler.round(cfg)
    assert calls == list(cfg.students)
