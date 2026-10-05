"""Immediate draining, version-bound stops and independent completion states."""
from datetime import datetime
from pathlib import Path
import pytest
from school_notes2.flows import context, run, work_pending
from school_notes2.flows import round as scheduler
from school_notes2.state import phase
from school_notes2.review import files
from tests.operations.test_round import cfg
from tests.conftest import recording_mailer


@pytest.mark.parametrize("failure", [None, "program", "owner", "aside"])
def test_success_drains_and_failure_waits_for_next_cron(cfg, monkeypatch, failure):
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 5, 1, tzinfo=scheduler.TZ))
    calls = []
    selected = list(cfg.students)[1]
    def fake(ctx):
        calls.append(ctx.name)
        if phase.all_tasks(ctx.task_root(), ctx.name):
            return 0
        task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
        if ctx.name == selected and failure:
            if failure == "program":
                raise RuntimeError("tool")
            if failure == "owner":
                task.mark_needs_owner("tool", "controller", "program")
            else:
                task.set_phase("done", set_aside=True)
            return 1
        task.set_phase("done")
        return 0
    monkeypatch.setattr(scheduler.run, "run", fake)
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda _: pytest.fail("not due"))
    scheduler.round(cfg)
    assert calls.count("third") == calls.count("second") == 2
    assert calls.count("first") == (1 if failure else 2)


def test_night_waits_for_all_students_until_six(cfg, monkeypatch):
    contexts = [context.make(cfg, n, console=False) for n in cfg.students]
    selected = list(cfg.students)[2]
    monkeypatch.setattr(work_pending, "ready", lambda ctx: ctx.name == selected)
    assert not scheduler._night_ready(contexts, datetime(2026, 10, 5, 4, tzinfo=scheduler.TZ))
    assert scheduler._night_ready(contexts, datetime(2026, 10, 5, 6, tzinfo=scheduler.TZ))
    monkeypatch.setattr(work_pending, "ready", lambda _: False)
    assert scheduler._night_ready(contexts, datetime(2026, 10, 5, 4, tzinfo=scheduler.TZ))


def test_package_stop_resumes_on_new_release(cfg, monkeypatch):
    ctx = context.make(cfg, "first", console=False)
    version = ["2.4.3"]
    monkeypatch.setattr(ctx.__class__, "release", lambda _: Path(version[0]))
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    task.mark_needs_owner("bug", "controller", "program")
    task.data["needs_owner"]["release"] = version[0]
    task.save()
    assert not run._may_run(ctx, task)
    version[0] = "2.5.0"
    assert run._may_run(ctx, task) and not task.data["needs_owner"]


def test_two_completion_states_distinguish_owner_work(cfg):
    ctx = context.make(cfg, "first", console=False)
    ctx.notes_path.mkdir(parents=True)
    assert work_pending.completion(ctx) == ["Automatikus feldolgozás: lezárult",
        "Tanulásra kész: igen – 0 nyitott tétel, 0 tulajdonosi tétel, 0 hiányzó kép"]
    path = files.write_review(ctx.notes_path, "2026-10-05", {"findings": [
        {"id": "R1", "file": "wiki/a/topic.md", "problem": "Hiba."}], "verdict": "changes"}, "test", "a", "b")
    assert "vár (indítható munka)" in work_pending.completion(ctx)[0]
    from school_notes2.wiki import frontmatter
    path.write_text(frontmatter.set_keys(path.read_text(), {"items": {"R1": "owner"}}))
    assert work_pending.completion(ctx)[0].endswith("lezárult")
    assert "nem – 0 nyitott tétel, 1 tulajdonosi tétel" in work_pending.completion(ctx)[1]


def test_archived_completion_mail_recovers_after_task_checkpoint(cfg, monkeypatch):
    from school_notes2.notify import pending
    from school_notes2.flows import operational_report
    ctx = context.make(cfg, "first", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
    task.update(mode="fix", set_aside=True, ranges=[[0, 0]])
    # The failed writer/ledger must not prevent the operational stop message.
    (task.dir / "result-1.json").write_text("broken json")
    monkeypatch.setattr(ctx.__class__, "image_settings", lambda _: (_ for _ in ()).throw(ValueError("broken ledger")))
    delivered = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, delivered)
    pending.retry(ctx)
    operational_report.completed(ctx, task, {}, 0)
    pending.retry(ctx)
    assert len(delivered) == 1 and "félretéve" in delivered[0].get_content()


def test_night_owner_stop_does_not_block_successful_notes_draining(cfg, monkeypatch):
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 5, 8, tzinfo=scheduler.TZ))
    contexts = [context.make(cfg, n, console=False) for n in cfg.students]
    for ctx in contexts:
        task = phase.create(ctx.task_root(), ctx.name, "review", "cron", "reviewing")
        task.mark_needs_owner("night", "controller", "program")
    counts = {}
    def success(ctx):
        counts[ctx.name] = counts.get(ctx.name, 0) + 1
        if counts[ctx.name] == 1:
            phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
        return 0
    monkeypatch.setattr(scheduler.run, "run", success)
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda _: pytest.fail("night is stopped"))
    scheduler.round(cfg)
    assert set(counts.values()) == {2}


def test_failed_night_is_not_retried_while_notes_keep_draining(cfg, monkeypatch):
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 5, 8, tzinfo=scheduler.TZ))
    monkeypatch.setattr(scheduler, "_night_ready", lambda *args: True)
    counts, nights = {}, []
    def success(ctx):
        counts[ctx.name] = counts.get(ctx.name, 0) + 1
        if counts[ctx.name] < 3:
            phase.create(ctx.task_root(), ctx.name, "notes", "cron", "done")
        return 0
    monkeypatch.setattr(scheduler.run, "run", success)
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda ctx: nights.append(ctx.name) or 1)
    scheduler.round(cfg)
    assert set(counts.values()) == {3}
    assert sorted(nights) == sorted(cfg.students)
