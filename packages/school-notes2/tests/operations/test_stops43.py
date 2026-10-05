"""Failure attribution and retirement of no-progress incidents."""

from pathlib import Path

import pytest

from school_notes2.flows import context, policy, operation, set_aside, steps
from school_notes2.notify import incidents, pending
from school_notes2.review import files
from school_notes2.state import phase
from school_notes2.state.files import read_json
from school_notes2.wiki import frontmatter
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["first", "second"])
def test_bad_finish_blocks_only_the_failing_call(cfg, monkeypatch, learner):
    ctx = context.make(cfg, learner, console=False)
    ctx.notes_path.mkdir(parents=True)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "finishing")
    report = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{k}", "file": f"wiki/{subject}/topic.md", "problem": "Hiba."}
        for k, subject in enumerate(("a", "b", "c"), 1)]}, "test", "a", "b").relative_to(ctx.notes_path).as_posix()
    assigned = [{"file": report, "item_id": f"R{k}"} for k in range(1, 4)]
    task.update(mode="fix", calls=[{"subject": subject, "open_review_items": [item]}
                for subject, item in zip(("a", "b", "c"), assigned)],
                writing_k=4, assigned_work=[report + f"#R{k}" for k in range(1, 4)])
    monkeypatch.setattr(set_aside.discard, "discard", lambda *a: None)
    failure = steps.CheckFailed([{"file": "wiki/b/topic.md", "line": 1, "message": "bad finish"}])
    for output in ("first", "retry"):
        task.update(writer_output_key=output)
        with operation.scope(ctx):
            policy.on_error(failure, task=task, student=ctx.name, step="finish", log=ctx.log, mailer=None)
    assert task.get("set_aside")
    assert read_json(set_aside.path(ctx))[task.run_id]["work"] == [report + "#R2"]


@pytest.mark.parametrize("recovery", ["release", "closed"])
def test_no_progress_incident_resolves_and_stays_resolved(cfg, monkeypatch, recovery):
    ctx = context.make(cfg, "first", console=False)
    ctx.notes_path.mkdir(parents=True)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "finishing")
    version = ["2.5.0"]
    monkeypatch.setattr(type(ctx), "release", lambda _: Path(version[0]))
    report = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/a/topic.md", "problem": "Hiba."}]}, "test", "a", "b")
    task.update(mode="fix", assigned_work=[report.relative_to(ctx.notes_path).as_posix() + "#R1"], no_progress=True)
    sent = []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, sent)
    set_aside.record(ctx, task, "no-progress")
    set_aside.no_progress_notice(ctx, task)
    task.set_phase("done")
    assert len(incidents.active(ctx)) == 1
    if recovery == "release":
        version[0] = "2.5.1"
    else:
        report.write_text(frontmatter.set_keys(report.read_text(), {"items": {"R1": "fixed"}}))
    pending.retry(ctx)
    pending.retry(ctx)
    assert not incidents.active(ctx)
    assert not set_aside.blocked(ctx)
    assert not phase.load(task.dir).get("no_progress")


def test_error_log_uses_shared_check_order(cfg):
    import json
    from school_notes2.flows import checks
    ctx = context.make(cfg, "first", console=False)
    values = [
        {"file": "a", "line": 1, "message": "first warning", "severity": "warning"},
        {"file": "z", "line": 1, "message": "error", "id": "b"},
        {"file": "z", "line": 1, "message": "error", "id": "a"},
    ]
    ctx.log.error("check", steps.CheckFailed(values))
    row = json.loads(ctx.log.main.read_text().splitlines()[-1])
    assert row["problems"] == [{k: i.get(k) for k in ("file", "line", "message")}
                               for i in checks.ordered(values)]
