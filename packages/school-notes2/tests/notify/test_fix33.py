"""Only a stopped situation opens an incident; retries and diagnostics cannot spam."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import last_error, operation, operational_report, policy
from school_notes2.llm import timeouts
from school_notes2.notify import Mailer, incidents, pending
from school_notes2.state import phase
from school_notes2.state.errors import BadWork, Prerequisite, SnError, Transient
from school_notes2.state.files import read_json, write_json
from tests.conftest import recording_mailer
from tests.notify.test_pending import context


@pytest.fixture(params=["benedek", "barna"])
def world(tmp_path, log, monkeypatch, request):
    ctx = context(tmp_path, log, request.param)
    sent = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, sent)
    return ctx, sent


def test_four_hours_of_decreasing_free_space_is_one_incident(world):
    ctx, sent = world
    for free in (3.1, 3.0, 2.9, 2.8):
        last_error.record(ctx, "run", "prerequisite", Prerequisite(f"only {free} GB free under /private"))
    assert len(sent) == 1
    assert "kevés a szabad lemezhely a VM-en: 3.1 GB; teendő: helyet kell felszabadítani" in sent[0].get_content()
    assert "/private" not in sent[0].get_content()
    # A different safe meaning at the same step still gets its own incident.
    last_error.record(ctx, "run", "prerequisite", Prerequisite("Podman failed"))
    assert len(sent) == 2


@pytest.mark.parametrize("error,limit", [(Transient, 3), (BadWork, 2)])
def test_task_retries_survive_restart_and_mail_only_on_stop(world, error, limit):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    for attempt in range(1, limit + 1):
        task = phase.load(task.dir)
        with operation.scope(ctx):
            policy.on_error(error(f"attempt {attempt}"), task=task, student=ctx.name,
                            step="run", log=ctx.log, mailer=ctx.mailer)
        if attempt < limit:
            operational_report.ended(ctx, "run", 0, {task.run_id: True})
            assert not sent and not incidents.active(ctx)
    assert len(sent) == 1 and task.data["needs_owner"]
    message = sent[0].get_content()
    assert "a futás megállt" in message and "a kontroller" in message
    assert "nincs teendőd, a tool újrapróbálja" not in message
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(sent) == 1


def test_taskless_transient_counts_per_step_and_success_resets(world):
    ctx, sent = world
    for attempt in range(1, 4):
        # Both operations failing must not reset each other's consecutive count.
        for step in ("nightly", "run"):
            with operation.scope(ctx):
                policy.on_error(Transient(f"Drive outage {attempt}"), task=None, student=ctx.name,
                                step=step, log=ctx.log, mailer=ctx.mailer)
            if attempt < 3:
                assert not incidents.active(ctx) and not sent
    assert len(sent) == 2
    last_error.clear(ctx, "run")
    last_error.record(ctx, "run", "transient", Transient("new outage"))
    assert len(sent) == 2
    for _ in range(2):
        last_error.record(ctx, "run", "transient", Transient("still down"))
    assert len(sent) == 3


def test_old_retry_incident_is_replaced_by_stopping_class(world, monkeypatch):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    with monkeypatch.context() as patch:
        patch.setattr(Mailer, "_deliver", lambda *a: False)
        incidents.record(ctx, "transient", "run", task=task)
    with operation.scope(ctx):
        policy.on_error(SnError("broken"), task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
    pending.retry(ctx)
    assert len(sent) == 1 and "programhiba" in sent[0].get_content()
    assert [i["class"] for i in incidents.active(ctx)] == ["program"]
    assert any(i.get("resolved_at") for i in read_json(incidents.path(ctx)).values())


def test_legacy_retry_sentence_is_replaced_even_with_same_class(world):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    write_json(incidents.path(ctx), {"old": {"at": "2026-10-05T08:00:00+02:00", "scope": "task:" + task.run_id,
        "class": "transient", "message": "átmeneti hiba; nincs teendőd, a tool újrapróbálja", "generation": 0,
        "run_id": task.run_id, "step": "run"}})
    task.data["retries"] = 2
    task.save()
    with operation.scope(ctx):
        policy.on_error(Transient("outage"), task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
    assert len(sent) == 1 and "a futás megállt" in sent[0].get_content()
    assert read_json(incidents.path(ctx))["old"]["resolved_at"]


def test_four_review_timeouts_share_one_incident_and_other_success_keeps_it(world):
    ctx, sent = world
    def call(label):
        return SimpleNamespace(role_name="reviewer", label=label, run_id="night", role=SimpleNamespace(timeout_s=5400))
    for label in ("a", "b", "c", "d"):
        timeouts.record(ctx, call(label))
    assert not sent
    for label in ("a", "b", "c", "d"):
        timeouts.record(ctx, call(label))
        timeouts.success(ctx, call("other"))
    assert len(sent) == 1
    assert [i["scope"] for i in incidents.active(ctx)] == ["timeout:reviewer"]
    for label in ("a", "b", "c", "d"):
        timeouts.success(ctx, call(label))
    assert not incidents.active(ctx)


@pytest.mark.parametrize("boundary", ["incident", "outbox", "receipt"])
def test_stopping_retry_delivery_survives_crash(world, monkeypatch, boundary):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    task.data["retries"] = 2
    task.save()
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
        with operation.scope(ctx), pytest.raises(KeyboardInterrupt):
            policy.on_error(Transient("outage"), task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
    task = phase.load(task.dir)
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    pending.retry(ctx)
    assert len(sent) == 1 and "a futás megállt" in sent[0].get_content()


def test_taskless_bad_work_also_waits_for_second_failure(world):
    ctx, sent = world
    for count in (1, 2):
        with operation.scope(ctx):
            policy.on_error(BadWork("invalid"), task=None, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
        assert len(sent) == count - 1


def test_changed_stop_reason_at_same_task_gets_new_sentence(world):
    ctx, sent = world
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    for error in (SnError("broken"), SnError("link", details={"items": [{"kind": "browser-link"}]})):
        with operation.scope(ctx):
            policy.on_error(error, task=task, student=ctx.name, step="run", log=ctx.log, mailer=ctx.mailer)
    assert len(sent) == 2
    assert "a kiadás előtti linkellenőrzés" in sent[1].get_content()


def test_taskless_stop_is_durable_before_retry_counter_save(world, monkeypatch):
    ctx, sent = world
    for _ in range(2):
        last_error.record(ctx, "run", "transient", Transient("outage"))
    with monkeypatch.context() as patch:
        patch.setattr(Mailer, "_deliver", lambda *a: False)
        def crash(*args):
            raise KeyboardInterrupt()
        patch.setattr(last_error, "write_json", crash)
        with pytest.raises(KeyboardInterrupt):
            last_error.record(ctx, "run", "transient", Transient("outage"))
    pending.retry(ctx)
    pending.retry(ctx)
    assert len(sent) == 1 and "a futás megállt" in sent[0].get_content()
