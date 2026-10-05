"""Installer admission and recoverable operational reporting."""

from dataclasses import replace
from datetime import datetime, timedelta
import os

import pytest

from school_notes2.flows import context, last_error, operation, run, status_text
from school_notes2.flows import round as scheduler
from school_notes2.log import TZ
from school_notes2.notify import incidents
from school_notes2.review import files
from school_notes2.state import phase
from school_notes2.state.errors import Prerequisite
from school_notes2.state.files import read_json, write_json
from school_notes2.wiki import lesson_log
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg  # noqa: F401


@pytest.mark.parametrize("before_first", [True, False])
def test_round_yields_vm_lock_to_pending_install(cfg, monkeypatch, before_first):
    marker = cfg.state_dir / "operations/install-pending"
    marker.parent.mkdir(parents=True)
    def mark():
        write_json(marker, {"pid": os.getpid(), "since": datetime.now(TZ).isoformat()})
    if before_first:
        mark()
    clock = [datetime(2026, 10, 5, 8, tzinfo=TZ)]
    monkeypatch.setattr(scheduler, "now", lambda: clock[0])
    cycles = []
    def cycle(*args):
        cycles.append(1)
        clock[0] += timedelta(hours=2)
        mark()
    monkeypatch.setattr(scheduler, "_cycle", cycle)
    assert scheduler.round(cfg) == 0
    assert len(cycles) == (0 if before_first else 1)
    assert operation.vm_lock(cfg).probe()
    marker.unlink()
    monkeypatch.setattr(scheduler, "_cycle", lambda *a: cycles.append(1))
    assert scheduler.round(cfg) == 0
    assert len(cycles) == (1 if before_first else 2)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_recovered_prerequisite_clears_even_when_task_needs_owner(cfg, monkeypatch, learner):
    cfg = replace(cfg, students={learner: replace(cfg.students["first"], name=learner)})
    ctx = context.make(cfg, learner, console=False)
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "writing")
    # An owner decision (a pre-2.6 bad-work stop would be released by the new release).
    task.mark_needs_owner("the writer asked a blocking question", "answer it", "needs_owner")
    last_error.record(ctx, "run", "prerequisite", Prerequisite("Podman failed"))
    monkeypatch.setattr(run.setup, "ensure", lambda _: None)
    monkeypatch.setattr(run, "_settle_images", lambda _: None)
    monkeypatch.setattr(run, "_prerequisites", lambda *a: None)
    monkeypatch.setattr(run.publish, "catch_up", lambda _: None)
    assert run.run(ctx) == 0
    assert not read_json(cfg.state_dir / learner / "last-error.json", {})
    assert not incidents.active(ctx)
    assert phase.load(task.dir).data["needs_owner"]


def test_context_failure_does_not_hide_other_learners(cfg, monkeypatch):
    make = context.make
    def broken(cfg, name, **kwargs):
        if name == "third":
            raise RuntimeError("broken context")
        return make(cfg, name, **kwargs)
    sent = []
    ctx = make(cfg, "first", console=False)
    recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    monkeypatch.setattr(context, "make", broken)
    monkeypatch.setattr(scheduler, "now", lambda: datetime(2026, 10, 5, 8, tzinfo=TZ))
    calls = []
    monkeypatch.setattr(scheduler.nightly, "nightly", lambda c: None)
    monkeypatch.setattr(scheduler.run, "run", lambda c: calls.append(c.name))
    assert scheduler.round(cfg) == 0
    assert calls == ["first", "second"] and len(sent) == 1
    text = status_text.snapshot(cfg)
    assert text.startswith("Készült: ") and "Third: az állapot nem olvasható" in text
    assert "First: szabad" in text and "Second: szabad" in text


def test_report_cache_keeps_more_than_thirty_two_content_keys():
    files._parsed_report.cache_clear()
    reports = [f"---\nitems: {{R1: open}}\n---\n# Report {n}\n" for n in range(100)]
    for text in reports:
        files.parse_report(text)
    for text in reports:
        files.parse_report(text)
    assert files._parsed_report.cache_info().hits == 100
    files.parse_report(reports[0]).meta["items"]["R1"] = "fixed"
    assert files.parse_report(reports[0]).meta["items"]["R1"] == "open"
    assert files.parse_report(reports[0].replace("open", "owner")).meta["items"]["R1"] == "owner"


def test_multiple_lesson_heading_error_lists_plural(tmp_path):
    error = lesson_log.form_problems(tmp_path, "wiki/m/a.md", "# Wrong\n", {"lessons": [{}, {}]})[0]
    assert lesson_log.TITLE in error and lesson_log.PLURAL_TITLE in error
