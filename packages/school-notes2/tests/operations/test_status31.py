from dataclasses import replace
from datetime import datetime

import pytest

from school_notes2.flows import context, status_text
from school_notes2.flows import round as scheduler
from school_notes2.log import TZ
from school_notes2.notify import incidents
from school_notes2.state import phase, safefs
from school_notes2.state.files import write_json
from school_notes2.wiki import frontmatter
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_hungarian_running_idle_today_queues_and_budget(cfg, monkeypatch, learner):
    cfg = replace(cfg, students={learner: replace(cfg.students["first"], name=learner)})
    ctx = context.make(cfg, learner, console=False)
    now = datetime(2026, 10, 5, 9, 26, tzinfo=TZ)
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "writing")
    task.data["created"] = now.replace(hour=1).isoformat()
    task.update(mode="fix", active_seconds=120, active_at_resume=120, resumed_at=now.replace(minute=12).isoformat())
    ctx.notes_path.mkdir(parents=True)
    safefs.write_text(ctx.notes_path, "docs/review/a.md", frontmatter.set_keys("# Review\n", {"items": {"R1": "open", "R2": "owner"}}))
    write_json(cfg.state_dir / learner / "last-run.json", {"ready": [1, 2], "waiting": [3]})
    write_json(cfg.state_dir / learner / "active.json", {"kind": "run", "started": now.replace(minute=12).isoformat(), "baseline": {task.run_id: 120}})
    lock = ctx.lock()
    lock.acquire("run")
    try:
        text = status_text.overview(ctx, now)
        assert f"{learner.capitalize()}: javító futás fut 09:12 óta, írás fázis, 14. perc" in text
        assert "1 nyitott tétel, 0 függő ábra, 3 Drive-csomag" in text
        assert "havi 10.00 USD" in text
        assert "Mai futások: 09:12–" in text
    finally:
        lock.release()
    task.set_phase("done", ended_at=now.isoformat(), active_seconds=120 + 14 * 60)
    text = status_text.overview(ctx, now)
    assert "szabad, a következő kört a cron indítja" in text and "10:00" not in text
    assert "09:12–09:26 14 p kész" in text
    assert len(text.splitlines()) == 9
    assert f"school-notes status --reopen {learner} <…>; újranyitható: docs/review/a.md#R2." in text
    assert "Automatikus feldolgozás:" in text
    assert "Tanulásra kész: nem" in text
    assert "Tulajdonosi döntésre vár: 1 review-tétel." in text


def test_round_snapshot_keeps_other_learner_on_corrupt_state(cfg, monkeypatch, capsys):
    fixed = datetime.now(TZ).replace(minute=10)
    monkeypatch.setattr(scheduler, "now", lambda: fixed)
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda c: None)
    monkeypatch.setattr(scheduler.run, "run", lambda c: None)
    scheduler.round(cfg)
    saved = (cfg.state_dir / "allapot.txt").read_text()
    assert saved == status_text.snapshot(cfg)
    assert saved.splitlines()[0] == f"Készült: {datetime.now(TZ):%Y-%m-%d %H:%M}"
    ctx = context.make(cfg, "third", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    task.path.write_text("broken json")
    text = status_text.snapshot(cfg)
    assert "Third: az állapot egy része nem olvasható" in text
    assert "First: szabad" in text and "Second: szabad" in text


def test_error_since_and_responsibility_visible_without_private_content(cfg, monkeypatch):
    ctx = context.make(cfg, "first", console=False)
    delivered = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, delivered)
    incidents.record(ctx, "program", "build")
    text = status_text.overview(ctx)
    assert "Hiba " in text and " óta: a futás megállt: programhiba" in text and "a javítás a kontrolleré" in text
    assert "{" not in text and str(cfg.root) not in text


def test_drive_snapshot_subtracts_only_packages_moved_since_scan(tmp_path):
    task = phase.create(tmp_path, "barna", "notes", "cron", "downloaded")
    task.update(selected=[{"package": {"id": "one"}}])
    snapshot = {"at": task.data["created"], "ready_ids": ["one", "two"], "waiting": ["three"]}
    assert status_text.drive_count(snapshot, [task]) == 3
    task.set_phase("moved")
    assert status_text.drive_count(snapshot, [phase.load(task.dir)]) == 2
    snapshot["at"] = "9999-01-01"
    assert status_text.drive_count(snapshot, [task]) == 3
