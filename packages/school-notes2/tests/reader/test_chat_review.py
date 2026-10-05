"""Chat P3→P4 handoff→P5 and finish regression coverage (K-2–K-4, K-9)."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import chat, correction, correction_chat, finish, handlers, inspection, report, steps, writer
from school_notes2.reader import calls
from school_notes2.review import relations
from school_notes2.state import phase, safefs
from .test_phases import finding, install_reader
from .test_review_fixes import acceptance, figure


@pytest.fixture
def session(setup, monkeypatch):
    ctx, task, page = setup
    task.data["mode"] = "interactive"
    task.save()
    ctx.task_root = lambda: ctx.cfg.state_dir
    ctx.lock = lambda: SimpleNamespace(note=lambda _: None)
    monkeypatch.setattr(writer, "write_changes", lambda *args: None)
    monkeypatch.setattr(steps, "guard_step", lambda *args: None)
    monkeypatch.setattr(steps, "check_changed", lambda *args, **kwargs: None)
    monkeypatch.setattr(report, "completion", lambda *args: None)
    monkeypatch.setattr(chat.run_flow, "owner_items", lambda *args: None)
    def git(task, wt, hooks, timeouts, start):
        if hooks.snapshot() != start:
            raise finish.git_finish.EditedDuringFinish()
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(finish.git_finish, "run", git)
    monkeypatch.setattr(writer, "run_ranges", lambda *a: pytest.fail("chat launched a second writer"))
    return ctx, task, page


def submit(ctx, task, status="fixed"):
    path = phase.load(task.dir).get("inspection_report")
    supplied = safefs.read_json(ctx.notes_path, ".school-notes/fetch.json")
    result = {"status": "done", "infographic_decisions": [{"page": p, "reason": "A szöveg elegendő."}
              for p in supplied.get("infographic_pages", [])], "review_closure": [
        {"file": path, "item_id": "R1", "status": status, "note": "Szakmai indok"}]}
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
    return result


@pytest.mark.parametrize("status", ["fixed", "disagree", "open"])
def test_chat_existing_writer_handles_p4_and_fetch_preserves_result(session, monkeypatch, status):
    ctx, task, page = session
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    answer = chat.session_finish(ctx)
    assert answer["state"] == "review_items" and len(answer["open_review_items"]) == 1
    assert "Csak akkor javíts" in answer["prompt"]
    task.reload()
    assert task.phase == "correcting"
    assert safefs.read_json(ctx.notes_path, ".school-notes/fetch.json")["mode"] == "fix"
    # A lost reply and session restart preserve the assignment, snapshot and check budget.
    assert chat.session_finish(ctx) == answer
    result = submit(ctx, task, status)
    child = correction_chat.active(task)
    child.update(writer_check={"count": 2, "warnings": []})
    assert chat.session_fetch(ctx)["open_review_items"] == 1
    assert safefs.read_json(ctx.notes_path, ".school-notes/result.json") == result
    assert correction_chat.active(task).get("writer_check")["count"] == 2
    routed = []
    monkeypatch.setattr(handlers, "check", lambda ctx, t: routed.append(t.dir))
    handlers.build(ctx).check()
    assert routed == [child.dir]
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nA gravitáció miatt.\n")
    gates = []
    monkeypatch.setattr(steps, "guard_step", lambda *args: gates.append("guard"))
    monkeypatch.setattr(steps, "check_changed", lambda *args, **kwargs: gates.append("check"))
    assert chat.session_finish(ctx)["state"] == "done"
    assert gates == ["guard", "check"]
    assert invoked == ["reader-1"] + ([] if status == "open" else ["recheck"])
    record = next(iter(relations.inventory(ctx.notes_path)["items"].values()))
    assert record["status"] == ("fixed" if status == "fixed" else "open")
    assert record["round"] == (2 if status == "disagree" else 1)


@pytest.mark.parametrize("damage", ["check", "warning", "closure", "json"])
def test_bad_chat_fix_rolls_back_once_and_keeps_items_open(session, monkeypatch, damage):
    ctx, task, page = session
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    before = safefs.read_text(ctx.notes_path, page)
    chat.session_finish(ctx)
    task.reload()
    result = submit(ctx, task)
    safefs.write_text(ctx.notes_path, page, before + "\nJavítás.\n")
    if damage == "check":
        def fail(*args, **kwargs):
            raise steps.CheckFailed([{"file": page, "line": 1, "severity": "error", "message": "bad"}])
        monkeypatch.setattr(steps, "check_changed", fail)
    elif damage == "warning":
        correction_chat.active(task).update(writer_check={"count": 1, "warnings": ["H1"]})
    elif damage == "closure":
        result["review_closure"][0]["item_id"] = "R99"
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
    else:
        safefs.write_text(ctx.notes_path, ".school-notes/result.json", "{broken")
    assert chat.session_finish(ctx)["state"] == "done"
    task.reload()
    assert task.get("correction_rolled_back")
    assert steps._llm_part(safefs.read_text(ctx.notes_path, page)) == steps._llm_part(before)
    assert not safefs.is_file(ctx.notes_path, "wiki/m/else.md")
    assert invoked == ["reader-1"]
    assert next(iter(relations.inventory(ctx.notes_path)["items"].values()))["status"] == "open"


@pytest.mark.parametrize("after_write", [False, True])
def test_t095_chat_correction_receipt_survives_crash(session, monkeypatch, after_write):
    ctx, task, page = session
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    chat.session_finish(ctx)
    submit(ctx, task)
    original, crashes = safefs.write_json, []
    def crash(root, rel, value):
        if root.name == "correction" and rel == "receipt.json" and not crashes:
            crashes.append(1)
            if after_write:
                original(root, rel, value)
            raise RuntimeError("crash at P4 receipt")
        return original(root, rel, value)
    monkeypatch.setattr(safefs, "write_json", crash)
    with pytest.raises(RuntimeError, match="P4 receipt"):
        chat.session_finish(ctx)
    assert phase.load(task.dir).phase == "correcting"
    assert chat.session_finish(ctx)["state"] == "done"
    assert invoked == ["reader-1", "recheck"]
    text = safefs.read_text(ctx.notes_path, phase.load(task.dir).get("inspection_report"))
    assert text.count("## Végrehajtva") == 1


def test_chat_accepted_figure_finishes_once(session, monkeypatch):
    ctx, task, page = session
    brief, candidate = figure(ctx, task, page)
    invoked = install_reader(monkeypatch, page)
    monkeypatch.setattr(inspection, "figures", lambda *args: acceptance(ctx, brief, candidate))
    monkeypatch.setattr(steps, "llm_snapshot", lambda *args: {
        page: steps._llm_hash(page, safefs.read_bytes(ctx.notes_path, page))})
    assert chat.session_finish(ctx)["state"] == "done"
    assert "generated figure-f" in safefs.read_text(ctx.notes_path, page)
    assert invoked == ["reader-1"]
    assert phase.load(task.dir).get("attempt") == 1


@pytest.mark.parametrize("stage", ["review", "G4", "G5"])
def test_chat_check_failure_new_attempt_runs_guard_and_new_review(session, monkeypatch, stage):
    ctx, task, page = session
    invoked = install_reader(monkeypatch, page)
    failed = []
    def fail():
        if not failed:
            failed.append(1)
            raise steps.CheckFailed([{"file": page, "severity": "error", "line": 1, "message": "bad"}])
    original_git = finish.git_finish.run
    def git(t, wt, hooks, timeouts, start):
        t.set_phase("committed")
        if stage == "G4":
            hooks.regenerate()
        else:
            hooks.build("commit")
        return original_git(t, wt, hooks, timeouts, start)
    if stage == "review":
        monkeypatch.setattr(steps, "generate_all", lambda *args: fail())
    else:
        monkeypatch.setattr(finish.git_finish, "run", git)
        monkeypatch.setattr(steps, "regenerate", lambda *args: fail())
        monkeypatch.setattr(finish, "_build", lambda *args: fail())
    assert chat.session_finish(ctx)["state"] == "check_failed"
    task.reload()
    assert task.phase == "writing" and not task.get("review_complete") and task.get("attempt") == 2
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nJavított mondat.\n")
    guarded = []
    monkeypatch.setattr(steps, "guard_step", lambda *args: guarded.append(1))
    def content(ctx, task):
        steps.guard_step(ctx, task)
        return steps.Prepared({"status": "done"}, False)
    monkeypatch.setattr(steps, "content_steps", content)
    assert chat.session_finish(ctx)["state"] == "done"
    assert guarded == [1] and invoked == ["reader-1", "reader-1"]
    assert (task.dir / "attempt-2/p3.json").is_file()


def test_resolved_conflict_runs_guard_before_regeneration(session, monkeypatch):
    ctx, task, page = session
    task.set_phase("committed", rebase="conflict", review_complete=True, conflict_files=[page])
    events = []
    def guard(ctx, task):
        events.append("guard")
        assert task.get("conflict_files") == [page]
        raise steps.CheckFailed([{"file": page, "severity": "error", "line": 1, "message": "machine edit"}])
    monkeypatch.setattr(steps, "guard_step", guard)
    monkeypatch.setattr(steps, "regenerate", lambda *args: events.append("regenerate"))
    assert chat.session_finish(ctx)["state"] == "check_failed"
    assert events == ["guard"]
