import stat

import pytest

from school_notes2.notify import Mailer, Notice
from tests.conftest import assert_suppressed


def fake_msmtp(tmp_path, rc=0):
    script = tmp_path / "msmtp"
    out = tmp_path / "sent.eml"
    script.write_text(f"#!/bin/sh\ncat >> {out}\nexit {rc}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, out


def notice(kind="completion:test:done"):
    return Notice("benedek", kind, "20261003-0100-ab12", "finish", "needs_owner",
                  "content conflict while rebasing", "resolve in school-notes chat")


def test_one_mail_per_closure_across_both_entry_points(tmp_path, log):
    script, out = fake_msmtp(tmp_path)
    mailer = Mailer(tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log,
                    msmtp=str(script))
    assert mailer.send(notice())
    assert not mailer.send(notice())
    assert mailer.send_once(notice()) is False
    assert mailer.send(notice("nightly:test:done"))
    text = out.read_text()
    assert text.count("Subject:") == 2


def test_msmtp_failure_is_only_logged(tmp_path, log):
    script, _ = fake_msmtp(tmp_path, rc=75)
    mailer = Mailer(tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log,
                    msmtp=str(script))
    assert not mailer.send(notice())
    assert not (tmp_path / "notify.json").exists()
    assert '"notify.mail"' in log.main.read_text()


def test_send_once_distinguishes_failure_sent_and_already_sent(tmp_path, log):
    script, out = fake_msmtp(tmp_path, rc=75)
    mailer = Mailer(tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log,
                    msmtp=str(script))
    assert mailer.send_once(notice()) is None
    assert not (tmp_path / "notify-once.json").exists()
    fake_msmtp(tmp_path)
    assert mailer.send_once(notice()) is True
    assert mailer.send_once(notice()) is False
    assert out.read_text().count("Subject:") == 2  # one failed attempt, one delivery


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_nightly_owner_items_are_suppressed_after_reload(tmp_path, log, monkeypatch, learner):
    from school_notes2.flows import nightly
    from school_notes2.state import phase
    from school_notes2.state.files import read_json
    from tests.notify.test_pending import context
    task = phase.create(tmp_path / "tasks", learner, "review", "cron", "reviewed")
    task.set_phase("done", notify_owner_items=[
        {"file": "docs/review/a.md", "item_id": f"R{i}"} for i in range(45)])
    attempted = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: attempted.append(msg) or True)
    ctx = context(tmp_path, log, learner)
    nightly._notify_owners(ctx, task)
    assert phase.load(task.dir).get("owners_notified")
    nightly._notify_owners(ctx, phase.load(task.dir))
    assert not attempted
    assert read_json(tmp_path / "state/notify-once.json", []) == []
    for i in range(45):
        assert_suppressed(log, f"review_owner:docs/review/a.md:R{i}")


@pytest.mark.parametrize("method", ["send", "send_once"])
@pytest.mark.parametrize("kind", ["needs_owner:notes", "timeout:writer", "quota:codex",
    "lock_held", "figure-pending-migration", "owner_notes:run", "license:figure",
    "image_exhausted:figure", "review_owner:item", "nightly-empty:today", "nightly-blocked:topic"])
def test_non_completion_notices_never_reach_msmtp(tmp_path, log, method, kind):
    script, out = fake_msmtp(tmp_path)
    mailer = Mailer(tmp_path / "rc", "owner@example.test", tmp_path / "notify.json", log,
                    msmtp=str(script))
    assert getattr(mailer, method)(notice(kind)) is False
    assert not out.exists()
    assert_suppressed(log, kind)
