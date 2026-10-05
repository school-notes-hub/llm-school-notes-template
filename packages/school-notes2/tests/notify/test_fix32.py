"""Explicit discard/retry outcomes are distinct from an incident and survive crashes."""

from datetime import datetime

import pytest

from school_notes2.flows import clear, operational_report, status_text
from school_notes2.notify import Mailer, pending
from school_notes2.review import files
from school_notes2.state import phase, safefs
from school_notes2.state.lock import StudentLock
from tests.conftest import recording_mailer
from tests.notify.test_pending import context


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("with_bundle", [True, False])
def test_discard_outcome_crash_before_mail_and_delivery_retry(tmp_path, log, monkeypatch, learner, with_bundle):
    ctx = context(tmp_path, log, learner)
    ctx.cfg.root = tmp_path
    ctx.lock = lambda: StudentLock(ctx.cfg.state_dir, learner)
    task = phase.create(tmp_path, learner, "notes", "cron", "writing")
    task.update(mode="fix")
    bundle = tmp_path / "private" / f"{task.run_id}.bundle" if with_bundle else None
    monkeypatch.setattr(clear.git_discard, "discard", lambda *a: bundle)
    # Direct helper models process death before the entry wrapper sends the notice.
    clear.discard(ctx, task)
    task = phase.load(task.dir)
    assert operational_report.terminal(task) == "closed"
    monkeypatch.setattr(Mailer, "_deliver", lambda *a: False)
    pending.retry(ctx)
    queued = pending.path(ctx).read_bytes()
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    pending.retry(ctx)
    pending.retry(ctx)
    operational_report.ended(ctx, "clear", 0, {task.run_id: True})
    assert len(delivered) == 1
    message = delivered[0].get_content()
    assert "elvetve; a munkája nem került ki" in message
    assert "elvetve" in delivered[0]["Subject"]
    assert str(tmp_path) not in message and "állapota: lezárva" not in message
    if with_bundle:
        assert f", archívumban van ({bundle.name})" in message
    else:
        assert "archívumban" not in message
    assert task.get("ended_at")[:16].replace("T", " ") + "-kor elvetve" in message
    assert b"closed" in queued


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_stuck_night_continue_names_retry_not_discard(tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    task = phase.create(tmp_path, learner, "review", "cron", "reviewing")
    task.update(stuck=True)
    task.mark_needs_owner("timeout", "continue", "timeout")
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, log, monkeypatch, delivered)
    clear.clear(ctx, "review", "continue")
    pending.retry(ctx)
    assert len(delivered) == 1
    assert "éjszaka újrapróbálja" in delivered[0].get_content()
    assert "elvetve" not in delivered[0].get_content()


def test_status_separates_owner_items_from_automatic_queue(tmp_path, log):
    ctx = context(tmp_path, log, "barna")
    ctx.notes_path.mkdir(parents=True, exist_ok=True)
    ctx.lock = lambda: StudentLock(ctx.cfg.state_dir, "barna")
    files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": "wiki/a.md", "problem": "Hiba.", "chain": 1},
        {"severity": "hiba", "id": "R2", "file": "wiki/a.md", "problem": "Döntés.", "category": "forrásellentmondás"},
    ]}, "r", "a", "b")
    data = status_text.collect(ctx, datetime.fromisoformat("2026-10-05T10:00:00+02:00"))
    assert data["items"] == data["owner_items"] == 1
    text = status_text.render(data)
    assert "Sorok: 1 nyitott tétel" in text
    assert "Tulajdonosi döntésre vár: 1 review-tétel." in text


def test_discard_resume_keeps_existing_bundle_receipt(tmp_path, log, monkeypatch):
    ctx = context(tmp_path, log, "barna")
    ctx.cfg.root = tmp_path
    task = phase.create(tmp_path, "barna", "notes", "cron", "writing")
    task.update(bundle=str(tmp_path / "saved.bundle"))
    monkeypatch.setattr(clear.git_discard, "discard", lambda *a: None)
    clear.discard(ctx, task)
    assert phase.load(task.dir).get("bundle") == str(tmp_path / "saved.bundle")
