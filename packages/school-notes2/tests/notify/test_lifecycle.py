"""One durable, content-free message per closure, including owner-stop resumes."""

import pytest

from school_notes2.flows import clear, operational_report, report, run
from school_notes2.notify import Notice, pending
from school_notes2.state import phase
from school_notes2.state.files import read_json, write_json
from tests.conftest import assert_suppressed, recording_mailer
from tests.notify.test_pending import context


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("kind", ["notes", "review"])
def test_whole_lifecycle_one_mail_despite_45_owner_items(tmp_path, log, monkeypatch, learner, kind):
    ctx = context(tmp_path, log, learner)
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    task = phase.create(tmp_path, learner, kind, "cron", "prepared")
    task.data["created"] = "2026-10-04T23:00:00+02:00"
    task.save()
    monkeypatch.setattr(operational_report, "now_iso", lambda: "2026-10-05T01:05:00+02:00")
    monkeypatch.setattr(operational_report.time, "monotonic", lambda: 0)
    mode = "nightly" if kind == "review" else "run"
    for stage in (("writing", "inspecting", "review_ready") if kind == "notes" else ("reviewing", "reviewed", "closing")):
        task.set_phase(stage)
        operational_report.ended(ctx, mode, 0, {task.run_id: True})
    run.owner_items(ctx, task, [{"file": "docs/review/a.md", "item_id": f"R{i}"} for i in range(45)])
    assert not delivered
    assert_suppressed(log, "review_owner:")
    task.reload()
    task.update(ranges=[], reader_owner_notes=["Titkos tanulói tartalom: wiki/a.md"], base="a", T="b")
    write_json(task.dir / "review.json", {"owner_notes": ["Titkos tanulói tartalom: wiki/a.md"]})
    task.set_phase("done")
    if kind == "notes":
        report.completion(ctx, task)
    for _ in range(2):
        operational_report.ended(ctx, mode, 0, {task.run_id: True})
        pending.retry(context(tmp_path, log, learner))
    assert len(delivered) == 1
    body = delivered[0].get_content().strip()
    assert body == (f"{learner.capitalize()} " + ("éjszakai review-ja" if kind == "review" else "jegyzetfutása") +
                    " 2026-10-04 23:00-kor indult, 2026-10-05 01:05-kor ért véget (0 perc munka), állapota: kész.")
    assert "Titkos" not in body and "wiki/" not in body and "{" not in body
    assert read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("kind", ["notes", "review"])
def test_repeated_owner_stop_resume_has_one_receipt_per_closure(tmp_path, log, monkeypatch, learner, kind):
    ctx = context(tmp_path, log, learner)
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    task = phase.create(tmp_path, learner, kind, "cron", "prepared")
    mode = "nightly" if kind == "review" else "run"
    for n in range(2):
        task.mark_needs_owner('{"content":"Titkos", "path":"/home/private/source.md"}', "chat", "program")
        for _ in range(2):
            operational_report.ended(ctx, mode, 0, {task.run_id: True})
        assert len(delivered) == n + 1
        assert "programhiba" in delivered[-1].get_content()
        assert "folytatható" in clear.clear(ctx, kind, "continue")
        task = phase.load(task.dir)
        assert task.get("completion_generation") == n + 1
    task.set_phase("done")
    for _ in range(2):
        operational_report.ended(ctx, mode, 0, {task.run_id: True})
    assert len(delivered) == 3
    for message in delivered:
        assert not any(token in message.get_content() for token in ("Titkos", "/home", ".md", "{"))


@pytest.mark.parametrize("kind", ["completion", "nightly"])
def test_legacy_suppressed_pending_items_are_drained_without_delivery(tmp_path, log, monkeypatch, kind):
    from dataclasses import asdict
    ctx = context(tmp_path, log, "barna")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    old = Notice("barna", "owner_notes:old", "old", "finish", "owner", "Tananyag", "")
    current = Notice("barna", f"{kind}:new:done", "new", "finish", "kész", "A futás elkészült.", "")
    write_json(pending.path(ctx), {n.kind: asdict(n) for n in (old, current)})
    pending.retry(ctx)
    pending.retry(ctx)
    assert len(delivered) == 1 and "Tananyag" not in delivered[0].get_content()
    assert_suppressed(log, "owner_notes:old")
    assert read_json(pending.path(ctx)) == {}


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_nightly_delivery_failure_retries_after_task_done(tmp_path, log, monkeypatch, learner):
    from school_notes2.notify import Mailer
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "review", "cron", "done")
    monkeypatch.setattr(Mailer, "_deliver", lambda *args: False)
    operational_report.ended(ctx, "nightly", 0, {task.run_id: True})
    queued = read_json(pending.path(ctx))
    assert list(queued) == [f"nightly:{task.run_id}:done"]
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    pending.retry(context(tmp_path, log, learner))
    operational_report.ended(ctx, "nightly", 0, {task.run_id: True})
    assert len(delivered) == 1 and read_json(pending.path(ctx)) == {}
    assert delivered[0].get_content().strip() == next(iter(queued.values()))["message"]


@pytest.mark.parametrize("kind", ["notes", "review"])
def test_legacy_json_summary_is_rebuilt_before_retry(tmp_path, log, monkeypatch, kind):
    import json
    from dataclasses import asdict
    ctx = context(tmp_path, log, "barna")
    task = phase.create(tmp_path, "barna", kind, "cron", "done")
    task.data["created"] = "2026-10-04T23:00:00+02:00"
    task.save()
    prefix = "nightly" if kind == "review" else "completion"
    old = Notice("barna", f"{prefix}:{task.run_id}:done", task.run_id, "finish", "feldolgozás",
                 json.dumps({"időpont": "2026-10-05T01:05:00+02:00", "owner_notes": ["wiki/a.md: tananyag"]}), "")
    write_json(pending.path(ctx), {old.kind: asdict(old)})
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    pending.retry(ctx)
    pending.retry(ctx)
    assert len(delivered) == 1
    body = delivered[0].get_content()
    assert "2026-10-04 23:00" in body and "2026-10-05 01:05" in body
    assert "{" not in body and "wiki/" not in body and "tananyag" not in body


def test_legacy_json_without_task_is_suppressed(tmp_path, log, monkeypatch):
    from dataclasses import asdict
    ctx = context(tmp_path, log, "barna")
    old = Notice("barna", "completion:old:done", "old", "finish", "feldolgozás", '{"notes":"tananyag"}', "")
    write_json(pending.path(ctx), {old.kind: asdict(old)})
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    pending.retry(ctx)
    assert not delivered and read_json(pending.path(ctx)) == {}
    assert_suppressed(log, old.kind)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_discarded_owner_stopped_night_gets_one_new_closure(tmp_path, log, monkeypatch, learner):
    from school_notes2.state.lock import StudentLock
    ctx = context(tmp_path, log, learner)
    ctx.lock = lambda: StudentLock(ctx.cfg.state_dir, learner)
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    task = phase.create(tmp_path, learner, "review", "cron", "prepared")
    task.mark_needs_owner("Hiba", "Dönts", "program")
    operational_report.ended(ctx, "nightly", 0, {task.run_id: True})
    assert len(delivered) == 1
    assert "eldobva" in clear.clear(ctx, "review", "discard")
    assert "nincs nyitott" in clear.clear(ctx, "review", "discard")
    assert len(delivered) == 2  # The discard explains a different terminal outcome.
    assert "elvetve; a munkája nem került ki" in delivered[-1].get_content()


def test_resumed_run_mail_reports_only_the_resumed_segment(tmp_path):
    """Owner 2026-10-05: a run stopped at 00:03 and resumed at 08:57 is not a 10-hour run."""
    from school_notes2.flows import operational_report
    from school_notes2.state import phase as phase_mod
    task = phase_mod.create(tmp_path, "benedek", "notes", "cron", "prepared")
    task.update(mode="repair", active_seconds=3833)
    task.mark_needs_owner("check failed", "repair the tool", "program")
    task.clear_needs_owner()
    task.update(active_seconds=3833 + 120)
    text = operational_report.sentence("benedek", operational_report.MODES["repair"], task, "done",
                                       ended="2026-10-05T09:01:00+02:00")
    assert "-kor folytatódott, 2026-10-05 09:01-kor ért véget (2 perc munka), állapota: kész." in text
