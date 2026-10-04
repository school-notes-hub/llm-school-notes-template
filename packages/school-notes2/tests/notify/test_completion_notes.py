"""Owner notes share the summary; short runs retain one durable notes notice."""

import pytest

from school_notes2.flows import operation, operational_report, report
from school_notes2.notify import Mailer, pending
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.notify.test_pending import context


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("duration", [599, 600, 601])
@pytest.mark.parametrize("timed", [False, True])
def test_completion_sends_one_notice_with_all_notes(tmp_path, log, monkeypatch, learner, duration, timed):
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "notes", "cron", "done")
    task.update(ranges=[[0, 0]], active_seconds=duration,
                reader_owner_notes=["Lektori megjegyzés."], recheck_owner_notes=["Visszaellenőrzés."],
                correction_result={"owner_notes": ["Javítói megjegyzés."]})
    write_json(task.dir / "result-1.json", {"status": "done", "owner_notes": ["Írói megjegyzés."]})
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: duration)
    token = operation.TIMING.set((0, {}) if timed else None)
    try:
        result = report.completion(ctx, task)
        operational_report.ended(ctx, "run", duration, {task.run_id: True})
    finally:
        operation.TIMING.reset(token)
    assert len(delivered) == 1
    body = delivered[0].get_content()
    assert all(note in body for note in result["owner_notes"])
    assert len(result["owner_notes"]) == 4
    if duration > 600:
        assert "keretállapot" in body
    else:
        assert "keretállapot" not in body
    assert read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("duration", [599, 601])
def test_no_push_finish_without_summary_still_sends_notes(tmp_path, log, monkeypatch, duration):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "committed")
    task.update(ranges=[[0, 0]], no_push=True, active_seconds=duration)
    write_json(task.dir / "result-1.json", {"status": "done", "owner_notes": ["Indok és javaslat."]})
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    report.completion(ctx, task)
    report.completion(ctx, phase.load(task.dir))
    assert len(delivered) == 1
    assert "Indok és javaslat." in delivered[0].get_content()
    assert "keretállapot" not in delivered[0].get_content()


@pytest.mark.parametrize("duration", [599, 601])
@pytest.mark.parametrize("crash", ["before-queue", "delivery"])
def test_completion_choice_survives_crash_and_threshold_crossing(tmp_path, log, monkeypatch, duration, crash):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "done")
    task.update(ranges=[[0, 0]], active_seconds=duration)
    write_json(task.dir / "result-1.json", {"status": "done", "owner_notes": ["Indok; jobb javaslat."]})
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    def stop(*args, **kwargs):
        raise KeyboardInterrupt
    with monkeypatch.context() as patch:
        patch.setattr(pending if crash == "before-queue" else Mailer,
                      "send" if crash == "before-queue" else "send_once", stop)
        with pytest.raises(KeyboardInterrupt):
            report.completion(ctx, task)
    task = phase.load(task.dir)
    assert task.get("completion_notices")["done"] == ("completion" if duration > 600 else "owner_notes")
    task.update(active_seconds=650)
    pending.retry(ctx)
    report.completion(ctx, task)
    report.completion(ctx, phase.load(task.dir))
    assert len(delivered) == 1
    assert ("keretállapot" in delivered[0].get_content()) == (duration > 600)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("ending", ["done", "closed", "finish"])
def test_owner_stop_defers_all_notes_until_final_completion(tmp_path, log, monkeypatch, learner, ending):
    from school_notes2.flows import clear, policy
    from school_notes2.state.errors import NeedsOwner
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "notes", "cron", "review_ready")
    task.update(ranges=[], active_seconds=30, reader_owner_notes=["N1: első megjegyzés."])
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: 0)
    policy.on_error(NeedsOwner("Hiba; tulajdonosi döntés kell."), task=task, student=learner,
                    step="finish", log=log, mailer=ctx.mailer)
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(delivered) == 1
    assert "N1" not in delivered[0].get_content()
    assert read_json(task.dir / "report.json")["owner_notes"] == ["N1: első megjegyzés."]
    assert "review_ready" in clear.clear(ctx, "notes", "continue")
    task = phase.load(task.dir)
    # The first stage no longer supplies N1; the saved report must retain it.
    task.update(reader_owner_notes=[], recheck_owner_notes=["N2: új megjegyzés."])
    if ending == "closed":
        task.data["closed"] = True
        task.save()
    else:
        task.set_phase("committed" if ending == "finish" else "done")
    if ending in ("finish", "done"):
        report.completion(ctx, task)
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(delivered) == 2
    assert all(note in delivered[1].get_content() for note in ("N1", "N2"))


@pytest.mark.parametrize("state,duration,notes", [
    ("done", 60, []), ("done", 60, ["Megjegyzés."]),
    ("needs_owner", 60, []), ("needs_owner", 60, ["Megjegyzés."]),
    ("writing", 700, ["Megjegyzés."])])
def test_details_are_not_computed_without_a_summary(tmp_path, log, monkeypatch, state, duration, notes):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "done" if state == "done" else "writing")
    task.update(reader_owner_notes=notes)
    if state == "needs_owner":
        task.mark_needs_owner("Hiba", "Folytatás", "program")
    calls, delivered = [], []
    monkeypatch.setattr(operational_report, "details", lambda *args: calls.append(args) or {})
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    operational_report.completed(ctx, task, {}, duration)
    assert not calls
    assert len(delivered) == int(state == "done" and bool(notes))


@pytest.mark.parametrize("state", ["done", "needs_owner"])
def test_broken_details_fall_back_to_basic_summary(tmp_path, log, monkeypatch, state):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "done" if state == "done" else "writing")
    task.update(reader_owner_notes=["Megőrzött megjegyzés."])
    if state == "needs_owner":
        task.mark_needs_owner("Hiba", "Folytatás", "program")
    def broken(*args):
        raise ValueError("unfinished frontmatter")
    monkeypatch.setattr(operational_report, "details", broken)
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    result = operational_report.completed(ctx, task, {"mode": "run", "témák": ["stale"]}, 601)
    assert len(delivered) == 1
    assert "Megőrzött megjegyzés." in delivered[0].get_content()
    assert "601" in delivered[0].get_content()
    assert result["fázis"] == task.phase and "témák" not in result
