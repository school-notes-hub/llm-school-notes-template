"""Second rejected fix/repair output is archived, version-blocked and mailed once."""

import json
from pathlib import Path

import pytest

from school_notes2.flows import context, fix_progress, operation, policy, set_aside, steps
from school_notes2.notify import pending
from school_notes2.state import phase
from school_notes2.state.files import read_json
from school_notes2.wiki.check import item
from tests.conftest import recording_mailer
from tests.operations.test_round import cfg


@pytest.mark.parametrize("learner", ["first", "second"])
@pytest.mark.parametrize("mode", ["fix", "repair", "run"])
@pytest.mark.parametrize("crash", [False, True])
def test_second_bad_output_stops_only_its_work(cfg, monkeypatch, learner, mode, crash):
    ctx = context.make(cfg, learner, console=False)
    ctx.notes_path.mkdir(parents=True)
    version = ["2.5.0"]
    monkeypatch.setattr(type(ctx), "release", lambda _: Path(version[0]))
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    work = {"file": "docs/review/a.md", "item_id": "R1"}
    task.update(mode=mode, open_review_items=[work], repair_topic="wiki/a/topic.md" if mode == "repair" else None)
    mail, archived = [], []
    ctx.mailer = recording_mailer(cfg.state_dir, ctx.log, monkeypatch, mail)
    monkeypatch.setattr(set_aside.discard, "discard", lambda *a: archived.append(a[1]))
    failure = steps.CheckFailed([item("wiki/a/topic.md", 42, "new error")])
    def reject(task):
        with operation.scope(ctx):
            policy.on_error(failure, task=task, student=ctx.name, step="writer", log=ctx.log, mailer=ctx.mailer)
    task.update(writer_output_key="one")
    reject(task)
    reject(task)  # The same persisted bad output counts once.
    assert task.data["llm_failures"] == 1 and not mail and not archived
    task.update(writer_output_key="two")
    resume = set_aside.resume
    if crash and mode != "run":
        monkeypatch.setattr(set_aside, "resume", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            reject(task)
        assert read_json(set_aside.path(ctx))[task.run_id]["reason"] == "bad_work"
        monkeypatch.setattr(set_aside, "resume", resume)
        assert resume(ctx, phase.load(task.dir))
        pending.retry(ctx)
    else:
        reject(task)
    pending.retry(ctx)
    pending.retry(ctx)
    task = phase.load(task.dir)
    assert task.data["llm_failures"] == 2 and len(mail) == 1
    assert task.get("last_check_problems") == failure.items
    if mode == "run":
        assert task.data["needs_owner"] and not archived and not task.get("set_aside")
        return
    assert not task.data["needs_owner"] and task.get("set_aside") and task.phase == "done"
    assert archived == [task.run_id]
    assert phase.open_task(ctx.task_root(), ctx.name, "notes") is None
    row = read_json(set_aside.path(ctx))[task.run_id]
    assert row["archive"] and row["release"] == "2.5.0" and row["work"]
    assert fix_progress.available(ctx, [work], [])[0] == []
    assert "kétszer hibás kimenetet adott" in mail[0].get_content()
    assert "a kontroller ellenőrzi; a többi munka megy" in mail[0].get_content()
    assert "toolhiba" not in str(mail[0]).lower() and "kész" not in mail[0].get_content()
    version[0] = "2.5.1"
    assert fix_progress.available(ctx, [work], [])[0] == [work]


def test_check_failure_log_has_sorted_twenty_problems_and_state_keeps_all(cfg):
    ctx = context.make(cfg, "first", console=False)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "writing")
    log_path = task.dir / "run.log"
    log = ctx.log.bind(run_log=log_path)
    problems = [item(f"wiki/a/{n:02}.md", n, f"Hiba {n}") for n in range(25, 0, -1)]
    failure = steps.CheckFailed(problems)
    policy.on_error(failure, task=task, student=ctx.name, step="writer", log=log, mailer=None)
    error = next(json.loads(line) for line in log_path.read_text().splitlines()
                 if json.loads(line).get("error_class") == "bad_work")
    expected = [{k: i[k] for k in ("file", "line", "message")} for i in problems[::-1][:20]]
    assert error["problems"] == expected
    assert phase.load(task.dir).get("last_check_problems") == problems[::-1]
