"""The session path (plan 5.8) and a crash between commit and push (S3, T11)."""

import subprocess
import sys

from school_notes2.flows import chat, finish as finish_flow, run as run_flow
from school_notes2.state import phase
from tests.e2e.test_run_e2e import HERE, show, world  # noqa: F401 - shared fixture


def test_session_fetch_edit_finish(world):
    ctx, origin, drive, package = world
    answer = chat.session_fetch(ctx)
    assert answer["pages"] == 2
    task = phase.open_task(ctx.task_root(), "benedek", "notes")
    assert task.mode == "interactive"
    subprocess.run([sys.executable, str(HERE / "fake_writer.py"), str(ctx.notes_path)], check=True)
    result = chat.session_finish(ctx)
    assert result["state"] == "done", result
    assert f"Run-Id: {task.run_id}" in show(origin, "main")


def test_session_check_failure_is_reported_not_counted(world, monkeypatch):
    ctx, origin, drive, package = world
    chat.session_fetch(ctx)
    subprocess.run([sys.executable, str(HERE / "fake_writer.py"), str(ctx.notes_path), "badlink"],
                   check=True)
    result = chat.session_finish(ctx)
    assert result["state"] == "check_failed" and "nincs-ilyen" in str(result["problems"])
    task = phase.open_task(ctx.task_root(), "benedek", "notes")
    assert task.data["llm_failures"] == 0 and task.data["needs_owner"] is None


def test_crash_after_commit_resumes_with_one_commit(world, monkeypatch):
    ctx, origin, drive, package = world
    calls = []

    def crashing_build(ctx_, task, commit):
        calls.append(commit)
        if len(calls) == 1:
            raise KeyboardInterrupt("simulated SIGKILL after the commit")
        return {"commit": commit, "output": "/nonexistent"}

    monkeypatch.setattr(finish_flow, "_build", crashing_build)
    try:
        run_flow.run(ctx)
    except KeyboardInterrupt:
        pass
    task = phase.open_task(ctx.task_root(), "benedek", "notes")
    assert task.phase == "committed"
    assert run_flow.run(ctx) == 0
    log = show(origin, "main")
    assert log.count(f"Run-Id: {task.run_id}") == 1


def test_session_reader_findings_become_items_without_a_handoff(world, monkeypatch):
    """KISS (fix-46): one pass per run, also in a session. The reader's finding is an item
    for the next run; there is no in-run correction round and no second writer."""
    from school_notes2.flows import writer
    from school_notes2.reader import calls
    from school_notes2.review import files
    ctx, origin, drive, package = world
    chat.session_fetch(ctx)
    subprocess.run([sys.executable, str(HERE / "fake_writer.py"), str(ctx.notes_path)], check=True)
    page = "wiki/proba/2026-10-02-teszt-jegyzet.md"
    invoked = []
    def reader(repo, view, folder, stage, assigned, configured, **kwargs):
        invoked.append(stage)
        findings = [{"severity": "hiba", "id": "F-1", "file": page, "line": 9, "quote": "Mit tanultunk ezen az órán",
                     "category": "nyelvezet", "problem": "Pontatlan cím", "suggestion": "Pontosítsd",
                     "relates_to": None}] if page in [p["file"] for p in assigned["pages"]] else []
        review = {"pages": [{"file": p["file"], "verdict": "changes" if p["file"] == page else "ok",
                              "first_glance": "Téma"} for p in assigned["pages"]],
                  "findings": findings, "owner_notes": []}
        return {"status": "reviewed", "model": "fake/high", "review": review}
    monkeypatch.setattr(calls, "run", reader)
    monkeypatch.setattr(writer, "run_ranges", lambda *a: (_ for _ in ()).throw(AssertionError("second writer")))
    answer = chat.session_finish(ctx)
    assert answer["state"] == "done", answer
    assert invoked == ["reader-1"]
    items = files.open_items(ctx.notes_path, "cron")
    assert len(items) == 1 and "Pontatlan cím" in show(origin, "main:" + items[0]["file"])


def test_session_build_failure_rechecks_edits_before_amending(world, monkeypatch):
    from school_notes2.flows import steps
    from school_notes2.state import safefs
    ctx, origin, drive, package = world
    chat.session_fetch(ctx)
    subprocess.run([sys.executable, str(HERE / "fake_writer.py"), str(ctx.notes_path)], check=True)
    page = "wiki/proba/2026-10-02-teszt-jegyzet.md"
    guarded, built = [], []
    original = steps.guard_step
    def guard(ctx, task):
        guarded.append(task.get("attempt", 1))
        original(ctx, task)
    def build(ctx, task, commit):
        built.append(commit)
        if len(built) == 1:
            raise steps.CheckFailed([{"file": page, "severity": "error", "line": 1, "message": "build defect"}])
        return {"commit": commit, "output": "/nonexistent"}
    monkeypatch.setattr(steps, "guard_step", guard)
    monkeypatch.setattr(finish_flow, "_build", build)
    assert chat.session_finish(ctx)["state"] == "check_failed"
    text = safefs.read_text(ctx.notes_path, page).replace("[Első]", "[Első téma]")
    safefs.write_text(ctx.notes_path, page, text)
    result = chat.session_finish(ctx)
    assert result["state"] == "done", result
    assert guarded == [1, 1] and len(built) == 2  # No new attempt: nothing is re-read (fix-46).
    assert "[Első téma]" in show(origin, "main:" + page)
