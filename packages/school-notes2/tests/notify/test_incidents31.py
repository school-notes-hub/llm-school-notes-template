import pytest

from school_notes2.flows import clear, last_error, operation, operational_report, policy
from school_notes2.notify import Mailer, incidents, pending
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner, Prerequisite, SnError
from school_notes2.state.files import read_json
from tests.conftest import recording_mailer
from tests.notify.test_pending import context


@pytest.mark.parametrize("learner", ["barna", "benedek"])
def test_immediate_error_repeated_rounds_resume_new_error_and_success(tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    task = phase.create(tmp_path, learner, "notes", "cron", "writing")
    error = SnError('private /home/secrets/source.json: {"tananyag": "SECRET"}',
                    details={"items": [{"kind": "browser-link"}]})
    for _ in range(3):
        with operation.scope(ctx):
            policy.on_error(error, task=task, student=learner, step="build", log=log, mailer=ctx.mailer)
        assert len(delivered) == 1  # Before the end-of-run report.
        operational_report.ended(ctx, "run", 0, {task.run_id: True})
    body = delivered[0].get_content()
    assert "programhiba a toolban (a kiadás előtti linkellenőrzés)" in body
    assert "nincs teendőd, a javítás a kontrolleré" in body
    assert not any(x in body for x in ("SECRET", "source.json", "/home", "{", "rád vár"))
    clear.clear(ctx, "notes", "continue")
    task.reload()
    with operation.scope(ctx):
        policy.on_error(error, task=task, student=learner, step="build", log=log, mailer=ctx.mailer)
    assert len(delivered) == 2
    clear.clear(ctx, "notes", "continue")
    task.reload()
    task.set_phase("done")
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(delivered) == 3 and "folytatódott" in delivered[-1].get_content()
    assert not incidents.active(ctx)


@pytest.mark.parametrize("boundary", ["incident", "outbox", "receipt"])
def test_error_delivery_crash_recovery(tmp_path, log, monkeypatch, boundary):
    ctx = context(tmp_path, log, "barna")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    with monkeypatch.context() as patch:
        if boundary == "incident":
            original = incidents.write_json
            def crash(path, value):
                original(path, value)
                raise KeyboardInterrupt()
            patch.setattr(incidents, "write_json", crash)
        else:
            original = Mailer.send_once
            def crash(self, notice):
                if boundary == "receipt":
                    original(self, notice)
                raise KeyboardInterrupt()
            patch.setattr(Mailer, "send_once", crash)
        with pytest.raises(KeyboardInterrupt):
            incidents.record(ctx, "program", "check")
    restarted = context(tmp_path, log, "barna")
    pending.retry(restarted)
    pending.retry(restarted)
    assert len(delivered) == 1
    assert read_json(pending.path(ctx)) == {}


def test_taskless_error_dedup_and_recovery(tmp_path, log, monkeypatch):
    ctx = context(tmp_path, log, "benedek")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    for _ in range(3):
        last_error.record(ctx, "run", "prerequisite", Prerequisite("login expired", todo="school-notes login benedek writer"))
    assert len(delivered) == 1
    assert "teendőd: school-notes login benedek writer" in delivered[0].get_content()
    last_error.clear(ctx)
    last_error.record(ctx, "run", "prerequisite", Prerequisite("login expired", todo="school-notes login benedek writer"))
    assert len(delivered) == 2


def test_question_conflict_and_timeout_are_private_safe(tmp_path):
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    question = NeedsOwner("question", details={"questions": [{"text": "Folytathatom a feldolgozást? SECRET /work/source.md"}]})
    assert "Folytathatom a feldolgozást?; válasz kell" in incidents.wording("barna", "needs_owner", "run", task=task, exc=question)
    unsafe = NeedsOwner("question", details={"questions": [{"text": "SECRET a tananyag és az osztálytárs neve?"}]})
    assert "SECRET" not in incidents.wording("barna", "needs_owner", "run", task=task, exc=unsafe)
    task.update(rebase="conflict", conflict_files=["wiki/m/naplo.md"])
    text = incidents.wording("barna", "needs_owner", "finish", task=task)
    assert "(naplo.md); döntés kell" in text and "wiki/" not in text
    assert "időtúllépés (olvasó-lektor)" in incidents.wording("barna", "timeout", "reader", role="reader")


def test_different_error_same_step_is_not_suppressed(tmp_path, log, monkeypatch):
    ctx = context(tmp_path, log, "barna")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    for error in (SnError("first"), SnError("second"), SnError("first")):
        incidents.record(ctx, "program", "run", exc=error)
    assert len(delivered) == 2


def test_unresolved_role_failure_has_no_duplicate_success_mail(tmp_path, log, monkeypatch):
    ctx = context(tmp_path, log, "barna")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "inspecting")
    incidents.record(ctx, "timeout", "reader", role="reader", scope="timeout:reader", run_id=task.run_id)
    task.set_phase("done")
    for _ in range(2):
        operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(delivered) == 1 and "időtúllépés" in delivered[0].get_content()
