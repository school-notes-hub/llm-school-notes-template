"""Fix-46 end to end: no 2.5.x state discards finished notes work; a build failure on
content holds the publication and becomes an item, the notes commit is kept and pushed."""

import json
import subprocess

import pytest

from school_notes2.flows import finish as finish_flow, inspection, nightly as nightly_flow, run as run_flow
from school_notes2.git import discard
from school_notes2.state import phase
from school_notes2.state.files import write_json
from tests.e2e.test_run_e2e import show, world  # noqa: F401 - shared fixture

NOTE = "wiki/proba/2026-10-02-teszt-jegyzet.md"
REAL_BUILD = finish_flow._build  # The world fixture replaces it with a stub.


def no_discard(monkeypatch):
    monkeypatch.setattr(discard, "discard", lambda *a: pytest.fail("finished work discarded"))


def interrupted_run(ctx, monkeypatch, target, name):
    real = getattr(target, name)
    fired = []
    def once(*args, **kwargs):
        if not fired:
            fired.append(1)
            raise KeyboardInterrupt("power loss")
        return real(*args, **kwargs)
    monkeypatch.setattr(target, name, once)
    with pytest.raises(KeyboardInterrupt):
        run_flow.run(ctx)
    return phase.open_task(ctx.task_root(), "benedek", "notes")


def test_build_failure_holds_publication_and_becomes_an_item(world, monkeypatch):
    """Point 1/I10: no new attempt, no reread, no attribution; the commit is pushed."""
    from school_notes2.site import build as site_build
    ctx, origin, drive, package = world
    monkeypatch.setattr(finish_flow, "_build", REAL_BUILD)
    monkeypatch.setattr(finish_flow.site_publish, "fetch_gh_pages", lambda *a, **kw: None)
    monkeypatch.setattr(finish_flow.site_publish, "changed_since_publish", lambda *a: None)
    problem = {"file": NOTE, "line": None, "message": "Missing cross-page fragment: elso.md#nincs"}
    calls = []
    def build(*args, **kwargs):
        calls.append(1)
        raise site_build.BuildContentError([problem])
    monkeypatch.setattr(site_build, "build", build)
    no_discard(monkeypatch)
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    task = phase.all_tasks(ctx.task_root(), "benedek")[-1]
    assert task.phase == "done" and task.get("attempt", 1) == 1 and len(calls) == 1
    assert task.get("build")["held"] and not task.get("published")
    assert "Mit tanultunk" in show(origin, f"main:{NOTE}")
    report = show(origin, f"main:{task.get('inspection_report')}")
    assert "Missing cross-page fragment" in report and "origin: check" in report
    assert "site.build_held" in ctx.cfg.log_path.read_text()


@pytest.mark.parametrize("reason", ["program", "bad_work", "no-progress"])
def test_25x_set_aside_record_never_discards_and_the_run_finishes(world, monkeypatch, reason):
    ctx, origin, drive, package = world
    task = interrupted_run(ctx, monkeypatch, finish_flow, "finish")
    assert (ctx.notes_path / NOTE).exists()
    write_json(ctx.cfg.state_dir / "benedek" / "set-aside.json", {task.run_id: {
        "work": ["docs/review/x.md#R1"], "release": "2.5.0", "reason": reason, "mode": "fix", "archive": True}})
    no_discard(monkeypatch)
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    assert phase.load(task.dir).phase == "done" and not phase.load(task.dir).get("set_aside")
    assert "Mit tanultunk" in show(origin, f"main:{NOTE}")


def test_25x_correction_round_with_rollback_receipts_continues_without_undoing(world, monkeypatch):
    """Point 7: a task in a 2.5.x correction round, with round folders, a saved round
    rollback and a scope rollback receipt, continues; every change is rechecked once."""
    ctx, origin, drive, package = world
    task = interrupted_run(ctx, monkeypatch, inspection, "inspect")
    folder = task.dir / "attempt-1"
    for name in ("correction-r2", "correction-r2-retry"):
        (folder / name).mkdir(parents=True, exist_ok=True)
        write_json(folder / name / "receipt.json", {"status": "rollback", "reason": "bad work"})
    (task.dir / "fix-before").mkdir(exist_ok=True)
    write_json(task.dir / "fix-before" / "rollback.json", {"reason": "scope"})
    write_json(task.dir / "fix-before" / "snapshot.json", [])
    task.set_phase("correcting", correction_round=2)
    no_discard(monkeypatch)
    assert run_flow.run(ctx) == 0, ctx.cfg.log_path.read_text()[-3000:]
    done = phase.load(task.dir)
    assert done.phase == "done" and done.get("recheck_all")
    assert "Mit tanultunk" in show(origin, f"main:{NOTE}")
    assert list((done.dir / "attempt-1" / "recheck").iterdir())  # every change rechecked once


def test_25x_topic_review_is_retired_and_the_diff_review_covers_its_range(world, monkeypatch, tmp_path):
    from tests.e2e.test_nightly_e2e import laptop_commit
    ctx, origin, drive, package = world
    seed = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", f"--git-dir={origin}", "update-ref", "refs/heads/claude-reviewed", seed], check=True)
    laptop_commit(tmp_path, origin, "wiki/proba/elso.md", show(origin, "main:wiki/proba/elso.md") + "\nÚj bekezdés.\n")
    legacy = phase.create(ctx.task_root(), "benedek", "review", "cron", "reviewing")
    legacy.update(topic_review=True, units=[], base=seed, H=seed)
    assert nightly_flow.nightly(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    assert phase.load(legacy.dir).data.get("closed")
    reviews = [t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review" and t.get("diff_review")]
    assert len(reviews) == 1 and reviews[0].phase == "done" and reviews[0].get("base") == seed
    assert json.loads((reviews[0].dir / "in/commits.json").read_text())
