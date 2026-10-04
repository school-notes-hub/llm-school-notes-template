import stat

import pytest

from school_notes2.notify import Mailer, Notice


def fake_msmtp(tmp_path, rc=0):
    script = tmp_path / "msmtp"
    out = tmp_path / "sent.eml"
    script.write_text(f"#!/bin/sh\ncat >> {out}\nexit {rc}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, out


def notice(kind="needs_owner:notes"):
    return Notice("benedek", kind, "20261003-0100-ab12", "finish", "needs_owner",
                  "content conflict while rebasing", "resolve in school-notes chat")


def test_one_mail_per_learner_and_kind_per_day(tmp_path, log):
    script, out = fake_msmtp(tmp_path)
    mailer = Mailer(tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log,
                    msmtp=str(script))
    assert mailer.send(notice())
    assert not mailer.send(notice())
    assert mailer.send(notice("prerequisite:login"))
    text = out.read_text()
    assert text.count("Subject:") == 2 and "school-notes status benedek" in text


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
def test_nightly_retries_only_failed_owner_items_after_reload(tmp_path, log, monkeypatch, learner):
    from types import SimpleNamespace
    from school_notes2.flows import nightly
    from school_notes2.state import phase
    from school_notes2.state.files import read_json
    task = phase.create(tmp_path / "tasks", learner, "review", "cron", "reviewed")
    task.set_phase("done", notify_owner_items=[
        {"file": "docs/review/a.md", "item_id": key} for key in ("R2", "R1")])
    attempted = []
    def deliver(self, message):
        attempted.append(message.get_content())
        return len(attempted) != 2
    monkeypatch.setattr(Mailer, "_deliver", deliver)
    def context():
        return SimpleNamespace(name=learner, cfg=SimpleNamespace(state_dir=tmp_path), mailer=Mailer(
            tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", log))
    nightly._notify_owners(context(), task)
    assert not phase.load(task.dir).get("owners_notified")
    assert read_json(tmp_path / "notify-once.json") == [f"{learner}:review_owner:docs/review/a.md:R1"]
    nightly._notify_owners(context(), phase.load(task.dir))
    assert phase.load(task.dir).get("owners_notified")
    nightly._notify_owners(context(), phase.load(task.dir))
    assert len(attempted) == 3
    assert "R1" in attempted[0] and "R2" in attempted[1] and "R2" in attempted[2]
    assert read_json(tmp_path / "notify-once.json") == [
        f"{learner}:review_owner:docs/review/a.md:{key}" for key in ("R1", "R2")]
