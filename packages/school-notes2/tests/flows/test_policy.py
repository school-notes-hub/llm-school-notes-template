from school_notes2.flows import policy
from school_notes2.state import phase
from school_notes2.state.errors import BadWork, NeedsOwner, Prerequisite, Transient
from tests.conftest import assert_suppressed, recording_mailer


def test_transient_stops_on_third_failed_invocation(tmp_path, log, monkeypatch):
    task = phase.create(tmp_path, "benedek", "notes", "cron", "prepared")
    sent = []
    mailer = recording_mailer(tmp_path, log, monkeypatch, sent)
    for _ in range(2):
        policy.on_error(Transient("net"), task=task, student="benedek", step="fetch", log=log,
                        mailer=mailer)
    assert task.data["needs_owner"] is None and not sent
    policy.on_error(Transient("net"), task=task, student="benedek", step="fetch", log=log,
                    mailer=mailer)
    assert task.data["needs_owner"]["class"] == "transient" and not sent
    assert_suppressed(log, "needs_owner:notes")


def test_success_in_the_second_hour_resets(tmp_path, log):
    task = phase.create(tmp_path, "benedek", "notes", "cron", "prepared")
    policy.on_error(Transient("net"), task=task, student="benedek", step="push", log=log,
                    mailer=None)
    policy.on_success(task)
    assert task.data["retries"] == 0


def test_bad_work_twice_needs_owner_but_not_interactive(tmp_path, log):
    task = phase.create(tmp_path, "barna", "notes", "interactive", "writing")
    policy.on_error(BadWork("x"), task=task, student="barna", step="writer", log=log,
                    mailer=None, interactive=True)
    assert task.data["llm_failures"] == 0
    for _ in range(2):
        policy.on_error(BadWork("x"), task=task, student="barna", step="writer", log=log,
                        mailer=None)
    assert task.data["needs_owner"]


def test_needs_owner_and_program_errors_stop_at_once(tmp_path, log, monkeypatch):
    task = phase.create(tmp_path, "barna", "notes", "cron", "committed")
    sent = []
    mailer = recording_mailer(tmp_path, log, monkeypatch, sent)
    policy.on_error(NeedsOwner("conflict", todo="chat"), task=task, student="barna",
                    step="finish", log=log, mailer=mailer)
    assert task.data["needs_owner"]["todo"] == "chat"
    task2 = phase.create(tmp_path, "barna", "review", "cron", "prepared")
    policy.on_error(KeyError("boom"), task=task2, student="barna", step="nightly", log=log,
                    mailer=mailer)
    assert task2.data["needs_owner"]["class"] == "program"
    assert "traceback" in log.main.read_text()
    assert not sent
    assert_suppressed(log, "needs_owner:notes")
    assert_suppressed(log, "needs_owner:review")


def test_prerequisite_is_suppressed_without_touching_the_task(tmp_path, log, monkeypatch):
    task = phase.create(tmp_path, "barna", "notes", "cron", "prepared")
    sent = []
    mailer = recording_mailer(tmp_path, log, monkeypatch, sent)
    policy.on_error(Prerequisite("login expired", todo="log in"), task=task, student="barna",
                    step="login", log=log, mailer=mailer)
    assert task.data["retries"] == 0 and not sent
    assert_suppressed(log, "prerequisite:login")
