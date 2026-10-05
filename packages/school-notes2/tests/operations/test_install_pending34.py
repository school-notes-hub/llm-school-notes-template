"""A dead or stale installer cannot silently stop every later hourly round."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from school_notes2.flows import context, install_pending, operation, round as scheduler
from school_notes2.log import TZ
from school_notes2.notify import Mailer, incidents
from school_notes2.state.files import read_json, write_json
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg  # noqa: F401


@pytest.mark.parametrize("state", ["dead", "stale", "invalid", "live"])
def test_install_marker_recovery_and_live_yield(cfg, monkeypatch, state):
    ctx = operation.vm_context(context.make(cfg, "first", console=False))
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    monkeypatch.setattr(scheduler, "_contexts", lambda _: [ctx])
    marker = cfg.state_dir / "operations/install-pending"
    since = datetime.now(TZ) - timedelta(seconds=7201 if state == "stale" else 0)
    write_json(marker, {"pid": os.getpid(), "since": since.isoformat()})
    if state == "invalid":
        marker.write_text("")  # Old installers wrote an empty flag.
    monkeypatch.setattr(install_pending, "_alive", lambda _: state != "dead")
    cycles = []
    monkeypatch.setattr(scheduler, "_cycle", lambda *a: cycles.append(1))
    for _ in range(2):
        assert scheduler.round(cfg) == 0
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    if state == "live":
        assert marker.exists() and not cycles and not sent
        assert any(e["action"] == "round.skip" and e["outcome"] == "install_pending" for e in events)
    else:
        assert not marker.exists() and len(cycles) == 2 and len(sent) == 1
        assert any(e["action"] == "round.install_pending" for e in events)
        error = read_json(cfg.state_dir / "VM/last-error.json")
        assert error["step"] == "install" and error["class"] == "program"
        assert "beragadt telepítési jelző" in error["message"]
        assert "a kör folytatódik" in sent[0].get_content() and "kontroller" in sent[0].get_content()


def test_crash_before_marker_removal_replays_one_notice(cfg, monkeypatch):
    ctx = operation.vm_context(context.make(cfg, "first", console=False))
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    marker = cfg.state_dir / "operations/install-pending"
    write_json(marker, {"pid": 0, "since": datetime.now(TZ).isoformat()})
    original = Path.unlink
    def crash(path, **kwargs):
        if path == marker:
            raise KeyboardInterrupt()
        return original(path, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", crash)
        with pytest.raises(KeyboardInterrupt):
            install_pending.waiting(ctx)
    assert marker.exists()
    assert not install_pending.waiting(ctx)
    assert len(sent) == 1 and len(incidents.active(ctx)) == 1
    assert not marker.exists()


def test_pid_liveness_checks_without_sending_a_signal(monkeypatch):
    assert install_pending._alive(os.getpid())
    def gone(pid, signal):
        assert signal == 0
        raise ProcessLookupError()
    monkeypatch.setattr(os, "kill", gone)
    assert not install_pending._alive(123)
    def inaccessible(pid, signal):
        raise PermissionError()
    monkeypatch.setattr(os, "kill", inaccessible)
    assert install_pending._alive(123)


def test_mail_failure_retries_after_marker_has_been_removed(cfg, monkeypatch):
    ctx = operation.vm_context(context.make(cfg, "first", console=False))
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    marker = cfg.state_dir / "operations/install-pending"
    write_json(marker, {"pid": 0, "since": datetime.now(TZ).isoformat()})
    with monkeypatch.context() as patch:
        patch.setattr(Mailer, "_deliver", lambda *a: False)
        assert not install_pending.waiting(ctx)
    assert not marker.exists() and not sent
    assert not install_pending.waiting(ctx)
    assert not install_pending.waiting(ctx)
    assert len(sent) == 1
