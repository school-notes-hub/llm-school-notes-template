"""Every closure sends one short summary; details stay in the private report."""

import pytest

from school_notes2.flows import operation, operational_report, report
from school_notes2.notify import Mailer, pending
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.notify.test_pending import context


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("duration", [599, 600, 601])
@pytest.mark.parametrize("timed", [False, True])
def test_completion_sends_one_sentence_and_keeps_all_notes_in_report(tmp_path, log, monkeypatch, learner, duration, timed):
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
    assert all(note not in body for note in result["owner_notes"])
    assert "indult" in body and "ért véget" in body and "kész" in body
    assert len(result["owner_notes"]) == 4
    assert "keretállapot" not in body and "{" not in body
    assert read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("duration", [599, 601])
def test_no_push_unfinished_task_keeps_notes_without_mail(tmp_path, log, monkeypatch, duration):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "committed")
    task.update(ranges=[[0, 0]], no_push=True, active_seconds=duration)
    write_json(task.dir / "result-1.json", {"status": "done", "owner_notes": ["Indok és javaslat."]})
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    report.completion(ctx, task)
    report.completion(ctx, phase.load(task.dir))
    assert not delivered
    assert read_json(task.dir / "report.json")["owner_notes"] == ["Indok és javaslat."]


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
    assert task.get("completion_notices")["done"] == "completion"
    task.update(active_seconds=650)
    pending.retry(ctx)
    report.completion(ctx, task)
    report.completion(ctx, phase.load(task.dir))
    assert len(delivered) == 1
    assert "keretállapot" not in delivered[0].get_content()


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("ending", ["done", "closed", "finish"])
def test_owner_stop_and_resumed_completion_each_send_one_short_mail(tmp_path, log, monkeypatch, learner, ending):
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
    if ending != "closed":
        assert "review_ready" in clear.clear(ctx, "notes", "continue")
    task = phase.load(task.dir)
    # The first stage no longer supplies N1; the saved report must retain it.
    task.update(reader_owner_notes=[], recheck_owner_notes=["N2: új megjegyzés."])
    if ending == "closed":
        from school_notes2.state.lock import StudentLock
        ctx.cfg.root = tmp_path
        ctx.lock = lambda: StudentLock(ctx.cfg.state_dir, learner)
        monkeypatch.setattr(clear.git_discard, "discard", lambda *a: None)
        assert "eldobva" in clear.clear(ctx, "notes", "discard")
        assert len(delivered) == 2  # Explicit discard has its own outcome notice.
        assert "elvetve; a munkája nem került ki" in delivered[-1].get_content()
        assert "nincs nyitott" in clear.clear(ctx, "notes", "discard")
    else:
        task.set_phase("committed" if ending == "finish" else "done")
    if ending in ("finish", "done"):
        report.completion(ctx, task)
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    operational_report.ended(ctx, "run", 0, {task.run_id: True})
    assert len(delivered) == (2 if ending in ("done", "closed") else 1)
    assert all(note not in msg.get_content() for msg in delivered for note in ("N1", "N2"))
    assert read_json(task.dir / "report.json")["owner_notes"] == ["N2: új megjegyzés.", "N1: első megjegyzés."]


@pytest.mark.parametrize("state,duration,notes", [
    ("done", 60, []), ("done", 60, ["Megjegyzés."]),
    ("needs_owner", 60, []), ("needs_owner", 60, ["Megjegyzés."]),
    ("writing", 700, ["Megjegyzés."])])
def test_details_only_computed_for_terminal_runs(tmp_path, log, monkeypatch, state, duration, notes):
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, ctx.name, "notes", "cron", "done" if state == "done" else "writing")
    task.update(reader_owner_notes=notes)
    if state == "needs_owner":
        task.mark_needs_owner("Hiba", "Folytatás", "program")
    calls, delivered = [], []
    monkeypatch.setattr(operational_report, "details", lambda *args: calls.append(args) or {})
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    operational_report.completed(ctx, task, {}, duration)
    assert bool(calls) == (state != "writing")
    assert len(delivered) == int(state != "writing")


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
    assert "Megőrzött megjegyzés." not in delivered[0].get_content()
    assert result["owner_notes"] == ["Megőrzött megjegyzés."]
    assert result["időtartam_s"] == 601
    assert result["fázis"] == task.phase and "témák" not in result
