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
    assert result["state"] == "check_failed" and result["problems"]
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


def test_session_review_handoff_real_guard_and_git_finish(world, monkeypatch):
    from school_notes2.flows import handlers, writer
    from school_notes2.reader import calls
    from school_notes2.state import safefs
    ctx, origin, drive, package = world
    chat.session_fetch(ctx)
    subprocess.run([sys.executable, str(HERE / "fake_writer.py"), str(ctx.notes_path)], check=True)
    page = "wiki/proba/2026-10-02-teszt-jegyzet.md"
    invoked = []
    def reader(repo, view, folder, stage, assigned, configured, **kwargs):
        invoked.append(stage)
        if stage == "reader-1":
            findings = [{"id": "F-1", "file": page, "quote": "Mit tanultunk ezen az órán",
                         "category": "nyelvezet", "problem": "Pontatlan cím", "suggestion": "Pontosítsd",
                         "relates_to": None}] if page in [p["file"] for p in assigned["pages"]] else []
            review = {"pages": [{"file": p["file"], "verdict": "changes" if p["file"] == page else "ok",
                                  "first_glance": "Téma"} for p in assigned["pages"]],
                      "findings": findings, "owner_notes": []}
        else:
            review = {"items": [{"key": i["key"], "verdict": "ok", "answer": "Rendben"}
                                 for i in assigned["items"]], "hits": [], "owner_notes": []}
        return {"status": "reviewed", "model": "fake/high", "review": review}
    monkeypatch.setattr(calls, "run", reader)
    def no_second_writer(*args):
        raise AssertionError("second writer")
    monkeypatch.setattr(writer, "run_ranges", no_second_writer)
    answer = chat.session_finish(ctx)
    assert answer["state"] == "review_items", answer
    assigned = answer["open_review_items"]
    # A local clarification leaves the lesson-log's required title intact.
    text = safefs.read_text(ctx.notes_path, page).replace("[Első]", "[Első téma]")
    safefs.write_text(ctx.notes_path, page, text)
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done", "review_closure": [
        {"file": i["file"], "item_id": i["item_id"], "status": "fixed", "note": "Pontosítva"} for i in assigned]})
    checked = handlers.build(ctx).check()
    assert checked["ok"], checked
    result = chat.session_finish(ctx)
    assert result["state"] == "done", result
    assert invoked.count("recheck") == 1
    assert "[Első téma]" in show(origin, "main:" + page)


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
    assert guarded == [1, 2] and len(built) == 2
    assert "[Első téma]" in show(origin, "main:" + page)
