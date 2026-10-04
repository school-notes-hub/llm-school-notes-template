"""K-10, K-11, K-13: real snapshots, rejected edits and range-local restoration."""

import subprocess

import pytest

from school_notes2.flows import chat, correction, correction_chat, finish, inspection, steps, writer
from school_notes2.flows.steps import llm_snapshot as real_snapshot
from school_notes2.state import phase, safefs
from .test_chat_review import session, submit
from .test_phases import finding, install_reader
from .test_review_fixes import acceptance, figure


@pytest.fixture
def guarded_session(session, monkeypatch, git_factory):
    ctx, task, page = session
    repo = ctx.notes_path
    safefs.write_text(repo, ".gitignore", ".school-notes/\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    wt = git_factory(repo / ".git", repo)
    wt.run("add", "wiki", "tools", ".gitignore")
    wt.run("commit", "-m", "base")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "\nÚj tananyag.\n")
    ctx.worktree = lambda _: wt
    monkeypatch.setattr(steps, "llm_snapshot", real_snapshot)
    return ctx, task, page


@pytest.mark.parametrize("stage", ["P3", "handoff", "P5", "P6"])
def test_chat_review_time_edit_is_detected(guarded_session, monkeypatch, stage):
    from school_notes2.flows import recheck, review_phases
    ctx, task, page = guarded_session
    install_reader(monkeypatch, page, findings=[finding(page)] if stage in ("P5", "handoff") else [])
    if stage == "P5":
        assert chat.session_finish(ctx)["state"] == "review_items"
        submit(ctx, task)
    module, name = {"P3": (inspection, "inspect"), "handoff": (inspection, "inspect"), "P5": (recheck, "run"),
                    "P6": (review_phases, "finalize")}[stage]
    original = getattr(module, name)
    def edit(*args):
        original(*args)
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nVersenyhelyzet.\n")
    monkeypatch.setattr(module, name, edit)
    assert chat.session_finish(ctx)["state"] == "edited"
    task.reload()
    assert task.phase == "writing" and task.get("attempt") == 2
    assert not task.get("review_complete")


@pytest.mark.parametrize("marker", ["figure", "image"])
def test_tool_figure_insertion_is_not_an_edit(guarded_session, monkeypatch, marker):
    ctx, task, page = guarded_session
    brief, candidate = figure(ctx, task, page)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page).replace(
        "<!-- figure: f -->", f"<!-- {marker}: f -->"))
    install_reader(monkeypatch, page)
    monkeypatch.setattr(inspection, "figures", lambda *args: acceptance(ctx, brief, candidate))
    assert chat.session_finish(ctx)["state"] == "done"
    assert "generated figure-f" in safefs.read_text(ctx.notes_path, page)


@pytest.mark.parametrize("edit", ["none", "text", "asset"])
@pytest.mark.parametrize("at_base", [False, True])
def test_tool_replacement_preserves_guard_for_text_and_candidate(guarded_session, monkeypatch, edit, at_base):
    from school_notes2.flows import review_phases
    ctx, task, page = guarded_session
    brief, candidate = figure(ctx, task, page)
    brief.update(replaces="wiki/assets/old.png", decision_reason={"code": "a", "text": "Hibás nyíl"})
    safefs.write_bytes(ctx.notes_path, brief["replaces"], safefs.read_bytes(ctx.notes_path, candidate["asset"]))
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n![Régi](../assets/old.png)\n")
    if at_base:
        wt = ctx.worktree("notes")
        wt.run("add", page, brief["replaces"])
        wt.run("commit", "-m", "pending replacement")
        task.update(base=wt.out("rev-parse", "HEAD").strip())
        assert page not in real_snapshot(ctx, task)
    invoked = install_reader(monkeypatch, page)
    def accept(*args):
        if edit == "text":
            safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nKésői szerkesztés.\n")
        return acceptance(ctx, brief, candidate)
    monkeypatch.setattr(inspection, "figures", accept)
    original = review_phases.finalize
    def finalize(*args):
        original(*args)
        if edit == "asset":
            safefs.write_bytes(ctx.notes_path, candidate["asset"], b"changed after acceptance")
    monkeypatch.setattr(review_phases, "finalize", finalize)
    assert chat.session_finish(ctx)["state"] == ("done" if edit == "none" else "edited")
    assert "![Régi]" not in safefs.read_text(ctx.notes_path, page)
    assert invoked == ["reader-1"]
    if edit == "none":
        assert phase.load(task.dir).get("attempt") == 1


@pytest.mark.parametrize("boundary", ["patch", "receipt", "restore"])
def test_t095_rejected_fix_survives_rollback_restart(guarded_session, monkeypatch, boundary):
    ctx, task, page = guarded_session
    install_reader(monkeypatch, page, findings=[finding(page)])
    before = safefs.read_text(ctx.notes_path, page)
    assert chat.session_finish(ctx)["state"] == "review_items"
    submit(ctx, task)
    safefs.write_text(ctx.notes_path, page, before + "\nElutasított javítás.\n")
    safefs.write_text(ctx.notes_path, "wiki/m/else.md", "Tiltott bővítés.\n")
    safefs.write_bytes(ctx.notes_path, "wiki/assets/new.bin", b"\0\xffimage")
    crashed = []
    if boundary == "restore":
        original = correction.restore
        def crash(repo, root):
            original(repo, root)
            if not crashed:
                crashed.append(1)
                raise RuntimeError("interrupted rollback")
        monkeypatch.setattr(correction, "restore", crash)
    else:
        name = "write_bytes" if boundary == "patch" else "write_json"
        original = getattr(safefs, name)
        def crash(root, rel, value, *args):
            original(root, rel, value, *args)
            if root.name == "correction" and rel == ("rejected.patch" if boundary == "patch" else "receipt.json") and not crashed:
                crashed.append(1)
                raise RuntimeError("interrupted rollback")
        monkeypatch.setattr(safefs, name, crash)
    with pytest.raises(RuntimeError, match="interrupted rollback"):
        chat.session_finish(ctx)
    root = inspection.folder(task) / "correction"
    patch = safefs.read_bytes(root, "rejected.patch")
    assert b"GIT binary patch" in patch and "Elutasított javítás".encode() in patch
    answer = chat.session_finish(ctx)
    assert answer["state"] == "done" and answer["correction_rolled_back"] is True
    assert "unassigned page" in answer["reason"]
    assert answer["rejected_patch"] == "attempt-1/correction/rejected.patch"
    assert safefs.read_bytes(root, "rejected.patch") == patch
    assert safefs.read_bytes(root, "rejected/wiki/assets/new.bin") == b"\0\xffimage"
    assert steps._llm_part(safefs.read_text(ctx.notes_path, page)) == steps._llm_part(before)


@pytest.mark.parametrize("damage", [False, True])
def test_p4_fix_and_rollback_keep_race_guard(guarded_session, monkeypatch, damage):
    ctx, task, page = guarded_session
    install_reader(monkeypatch, page, findings=[finding(page)])
    chat.session_finish(ctx)
    submit(ctx, task)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nJavítás.\n")
    if damage:
        safefs.write_text(ctx.notes_path, "wiki/m/else.md", "scope error")
    answer = chat.session_finish(ctx)
    assert answer["state"] == "done"
    assert answer.get("correction_rolled_back", False) == damage


@pytest.mark.parametrize("last_result", [True, False])
def test_chat_p4_restores_only_current_range_before_retry(session, monkeypatch, last_result):
    ctx, task, page = session
    brief, candidate = figure(ctx, task, page)
    first = {"status": "done", "figures": [{k: brief[k] for k in ("id", "kind", "page")}],
             "checks": [{"page": page, "image": candidate["asset"], "locator": "ábra",
                         "observed": "Erő", "decision": "confirmed"}],
             "owner_notes": ["Első tartomány"]}
    second = {"status": "done", "owner_notes": ["Második tartomány"]}
    task.update(ranges=[[0, 0], [0, 0]], writing_k=2, inspection_result=writer.merge([first, second]))
    safefs.write_json(task.dir, "result-1.json", first)
    safefs.write_json(task.dir, "result-2.json", second)
    if last_result:
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", second)
    install_reader(monkeypatch, page, findings=[finding(page)])
    monkeypatch.setattr(inspection, "figures", lambda *args: acceptance(ctx, brief, candidate))
    assert chat.session_finish(ctx)["state"] == "review_items"
    submit(ctx, task)
    def fail(*args):
        raise steps.CheckFailed([{"file": page, "line": 1, "severity": "error", "message": "G5"}])
    monkeypatch.setattr(finish.git_finish, "run", fail)
    assert chat.session_finish(ctx)["state"] == "check_failed"
    assert safefs.read_json(ctx.notes_path, ".school-notes/result.json") == (second if last_result else None)
    task.reload()
    merged = steps.merged_result(ctx, task)
    assert merged["figures"] == first["figures"] and merged["checks"] == first["checks"]
    assert merged["owner_notes"] == first["owner_notes"] + second["owner_notes"]


def test_repeated_handoff_allows_p4_edit_during_finish(guarded_session, monkeypatch):
    ctx, task, page = guarded_session
    invoked = install_reader(monkeypatch, page, findings=[finding(page)])
    answer = chat.session_finish(ctx)
    original = correction_chat.result
    def edit(ctx, child):
        safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nJavítás folyamatban.\n")
        return original(ctx, child)
    monkeypatch.setattr(correction_chat, "result", edit)
    assert chat.session_finish(ctx) == answer
    resumed = phase.load(task.dir)
    assert resumed.phase == "correcting" and resumed.get("attempt") == 1
    assert invoked == ["reader-1"]
    monkeypatch.setattr(correction_chat, "result", original)
    submit(ctx, task)
    assert chat.session_finish(ctx)["state"] == "done"
    assert invoked == ["reader-1", "recheck"]


def test_tool_replacement_can_restore_base_snapshot(guarded_session, monkeypatch):
    ctx, task, page = guarded_session
    brief, candidate = figure(ctx, task, page)
    wt = ctx.worktree("notes")
    wt.run("add", page)
    wt.run("commit", "-m", "pending figure")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    brief.update(replaces="wiki/assets/old.png", decision_reason={"code": "a", "text": "Hibás nyíl"})
    safefs.write_bytes(ctx.notes_path, brief["replaces"], safefs.read_bytes(ctx.notes_path, candidate["asset"]))
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n![Régi](../assets/old.png)\n")
    assert page in real_snapshot(ctx, task)
    install_reader(monkeypatch, page)
    monkeypatch.setattr(inspection, "figures", lambda *args: acceptance(ctx, brief, candidate))
    assert chat.session_finish(ctx)["state"] == "done"
    assert page not in real_snapshot(ctx, phase.load(task.dir))
    assert "generated figure-f" in safefs.read_text(ctx.notes_path, page)


@pytest.mark.parametrize("failure", ["check", "edited"])
def test_new_attempt_without_p4_clears_rollback_answer(session, monkeypatch, failure):
    ctx, task, page = session
    install_reader(monkeypatch, page, findings=[finding(page)])
    assert chat.session_finish(ctx)["state"] == "review_items"
    submit(ctx, task)
    safefs.write_text(ctx.notes_path, "wiki/m/else.md", "Tiltott módosítás")
    original = finish.git_finish.run
    def fail(*args):
        if failure == "check":
            raise steps.CheckFailed([{"file": page, "line": 1, "severity": "error", "message": "G5"}])
        raise finish.git_finish.EditedDuringFinish()
    monkeypatch.setattr(finish.git_finish, "run", fail)
    assert chat.session_finish(ctx)["state"] == ("check_failed" if failure == "check" else "edited")
    assert phase.load(task.dir).get("correction_rolled_back")
    # No item remains eligible for P4 in attempt 2.
    monkeypatch.setattr(correction, "all_items", lambda *args: [])
    monkeypatch.setattr(correction, "run", lambda *args: pytest.fail("unexpected P4"))
    monkeypatch.setattr(steps, "content_steps", lambda *args: steps.Prepared({"status": "done"}, False))
    monkeypatch.setattr(finish.git_finish, "run", original)
    answer = chat.session_finish(ctx)
    assert answer["state"] == "done"
    assert not {"correction_rolled_back", "reason", "items", "rejected_patch"} & answer.keys()
    resumed = phase.load(task.dir)
    assert resumed.get("attempt") == 2 and not resumed.get("correction_rolled_back")
    assert resumed.get("correction_rollback_reason") is None
    assert resumed.get("correction_rollback_items") == []
    assert resumed.get("correction_rejected_patch") is None


@pytest.mark.parametrize("count", [2, 12])
def test_check_rollback_details_survive_receipt_restart(session, monkeypatch, count):
    ctx, task, page = session
    install_reader(monkeypatch, page, findings=[finding(page)])
    chat.session_finish(ctx)
    submit(ctx, task)
    items = [{"file": page, "line": n, "severity": "error", "message": f"Hiba {n}"}
             for n in range(1, count + 1)]
    def fail(*args, **kwargs):
        steps.write_check_items(ctx, items)
        raise steps.CheckFailed(items)
    monkeypatch.setattr(steps, "check_changed", fail)
    original = safefs.write_json
    def crash(root, rel, value, *args):
        original(root, rel, value, *args)
        if root.name == "correction" and rel == "receipt.json":
            raise RuntimeError("receipt saved")
    monkeypatch.setattr(safefs, "write_json", crash)
    with pytest.raises(RuntimeError, match="receipt saved"):
        chat.session_finish(ctx)
    monkeypatch.setattr(safefs, "write_json", original)
    monkeypatch.setattr(steps, "check_changed", lambda *a, **kw: pytest.fail("replayed P4"))
    answer = chat.session_finish(ctx)
    assert answer["state"] == "done" and answer["correction_rolled_back"]
    assert answer["items"] == items[:10]
    assert answer["rejected_patch"] == "attempt-1/correction/rejected.patch"
    assert (task.dir / answer["rejected_patch"]).is_file()
    saved = safefs.read_json(inspection.folder(task) / "correction", "receipt.json")
    assert saved["items"] == items[:10] and saved["rejected_patch"] == answer["rejected_patch"]
    assert safefs.read_json(ctx.notes_path, ".school-notes/check.json") != items
