"""A night owns its log identity, including after a notes run or interruption."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from school_notes2.flows import context, nightly, operational_report
from school_notes2.state import phase
from tests.operations.test_round import cfg  # noqa: F401


@pytest.mark.parametrize("student", ["benedek", "barna"])
@pytest.mark.parametrize("saved_phase", [None, "reviewing", "waiting_quota", "reviewed"])
def test_nightly_logs_use_own_task_after_notes_and_resume(cfg, monkeypatch, student, saved_phase):
    cfg = replace(cfg, students={student: replace(cfg.students["first"], name=student)})
    ctx = context.make(cfg, student, console=False)
    ctx.mailer = SimpleNamespace(send=lambda n: None, send_once=lambda n: None)
    ctx.log = ctx.log.bind(run_id="previous-notes-run")
    monkeypatch.setattr(nightly.setup, "ensure", lambda c: None)
    monkeypatch.setattr(nightly.cleanup, "old_tasks", lambda c: None)
    monkeypatch.setattr(operational_report, "ended", lambda *a, **kw: None)
    def prepare(c, tasks):
        return phase.create(c.task_root(), c.name, "review", "cron", "prepared")
    monkeypatch.setattr(nightly, "_prepare", prepare)
    if saved_phase:
        task = prepare(ctx, [])
        task.set_phase(saved_phase, quota_phase="reviewing")
    interrupted = []
    def review(c, task):
        task.set_phase("reviewing")
        for role in ("reviewer", "figure-review"):
            c.log.event(f"llm.launch role={role}")
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt()
        task.set_phase("reviewed")
    def close(c, task):
        c.log.event("nightly.close")
        task.set_phase("done")
    monkeypatch.setattr(nightly, "_review", review)
    monkeypatch.setattr(nightly, "_close", close)
    if saved_phase != "reviewed":
        with pytest.raises(KeyboardInterrupt):
            nightly.nightly(ctx)
        ctx.log = ctx.log.bind(run_id="another-notes-run")
    assert nightly.nightly(ctx) == 0
    tasks = phase.all_tasks(ctx.task_root(), student)
    assert len(tasks) == 1 and tasks[0].phase == "done"
    events = [json.loads(line) for line in cfg.log_path.read_text().splitlines()]
    assert {event["run_id"] for event in events} == {tasks[0].run_id}
    assert {event["student"] for event in events} == {student}
    launches = [event["action"] for event in events if event["action"].startswith("llm.launch")]
    expected = ["llm.launch role=reviewer", "llm.launch role=figure-review"] * 2
    assert launches == ([] if saved_phase == "reviewed" else expected)
