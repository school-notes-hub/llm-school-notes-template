"""Legacy check defects survive scope restoration without failing current work."""

import pytest

from school_notes2.flows import checks, correction, fix_scope, handlers, inherited_check, steps, writer
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import check as wiki_check
from tests.flows.test_learning_checks import learning_run, TOPIC

QUESTIONS = "\n# Nyitott kérdések\n\n1. Első kérdés?\n\n2. Második kérdés?\n"


def old_questions(ctx, task):
    path = ctx.notes_path / TOPIC
    path.write_text(path.read_text() + QUESTIONS)
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old question errors")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    return path.read_bytes()


def inherited_items(ctx):
    return [i for i in relations.inventory(ctx.notes_path)["items"].values()
            if i.get("origin") == inherited_check.KIND]


@pytest.mark.parametrize("mode", ["run", "fix", "repair"])
def test_old_errors_do_not_block_assigned_page_but_new_errors_do(learning_run, mode):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    task.update(mode=mode, repair_targets=[{"page": TOPIC, "related": [], "kind": "topic"}])
    safefs.write_bytes(ctx.notes_path, TOPIC, old.replace(b"# Nyitott", b"\n\n# Nyitott"))
    answer = handlers.check(ctx, task)
    inherited = [i for i in answer["problems"] if i.get("kind") == inherited_check.KIND]
    assert answer["ok"] and len(inherited) == 2
    assert all("nem a te feladatod" in i["message"] for i in inherited)
    assert checks.accounting(task, {"status": "done"}) == []
    assert not inherited_items(ctx)
    steps.check_changed(ctx, task)
    assert len(inherited_items(ctx)) == 2
    first = safefs.read_bytes(ctx.notes_path, task.get("inspection_report"))
    # Repeated checks, including a reconstructed task, do not duplicate open items.
    handlers.check(ctx, phase.load(task.dir))
    assert safefs.read_bytes(ctx.notes_path, task.get("inspection_report")) == first
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\n[Broken](missing.md)\n")
    with pytest.raises(steps.CheckFailed) as failure:
        steps.check_changed(ctx, task)
    assert len(failure.value.items) == 1 and "link target" in failure.value.items[0]["message"]


def test_scope_restore_fake_writer_keeps_two_old_errors_for_next_run(learning_run, monkeypatch):
    ctx, task = learning_run
    original = old_questions(ctx, task)
    task.data["mode"] = "cron"
    task.update(mode="fix", open_review_items=[], pending_figures=[])
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.update(correction_before=str(root / "before"))
    called = []
    def fake(*args):
        called.append(1)
        text = original.decode().replace("1. Első", "<!-- q: elso-one -->\n1. Első")
        text = text.replace("2. Második", "<!-- q: elso-two -->\n2. Második")
        safefs.write_text(ctx.notes_path, TOPIC, text)
        return {"status": "done"}
    monkeypatch.setattr(writer, "_call", fake)
    assert writer.run_ranges(ctx, task, None) == "done"
    assert called == [1] and safefs.read_bytes(ctx.notes_path, TOPIC) == original
    assert TOPIC not in steps.changed_paths(ctx, task) and TOPIC not in steps.llm_snapshot(ctx, task)
    steps.check_changed(ctx, task)
    found = inherited_items(ctx)
    assert len(found) == 2 and all(i["status"] == "open" and i["severity"] == "hiba" for i in found)
    saved = safefs.read_bytes(ctx.notes_path, task.get("inspection_report"))
    assert writer.run_ranges(ctx, phase.load(task.dir), None) == "done"
    assert called == [1] and safefs.read_bytes(ctx.notes_path, task.get("inspection_report")) == saved


def test_restored_legacy_line_endings_stay_byte_identical(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task).replace(b"\n", b"\r\n")
    safefs.write_bytes(ctx.notes_path, TOPIC, old)
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "legacy line endings")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    inherited_check.restored(ctx, task, [TOPIC])
    assert safefs.read_bytes(ctx.notes_path, TOPIC) == old
    assert TOPIC not in steps.changed_paths(ctx, task)
    assert len(inherited_items(ctx)) == 2


def test_exact_bytes_override_stale_git_change_list(learning_run, monkeypatch):
    ctx, task = learning_run
    monkeypatch.setattr(steps.workbranch, "changed_files", lambda *a: [{"path": TOPIC, "status": "modified"}])
    assert steps.changed_paths(ctx, task) == []
    assert steps.llm_snapshot(ctx, task) == {}


def test_new_missing_target_cannot_be_inherited_from_old_link(learning_run):
    ctx, task = learning_run
    target = "wiki/proba/target.md"
    safefs.write_text(ctx.notes_path, target, "# Target\n")
    text = safefs.read_text(ctx.notes_path, TOPIC) + "\n[Link](target.md)\n"
    safefs.write_text(ctx.notes_path, TOPIC, text)
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old valid link")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    safefs.unlink(ctx.notes_path, target)
    safefs.write_text(ctx.notes_path, TOPIC, text + "\nNew prose.\n")
    with pytest.raises(steps.CheckFailed) as failure:
        steps.check_changed(ctx, task)
    assert any("link target" in p["message"] for p in failure.value.items)


def test_base_render_glob_does_not_follow_symlinks(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    link = ctx.notes_path / "wiki/assets/proba/render.json"
    link.symlink_to("missing.json")
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old dangling render link")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    steps.check_changed(ctx, task)
    assert len(inherited_items(ctx)) == 2


def test_new_third_anchor_error_is_not_hidden(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\n3. Third?\n")
    with pytest.raises(steps.CheckFailed) as failure:
        steps.check_changed(ctx, task)
    assert len(failure.value.items) == 3
    assert not inherited_items(ctx)


@pytest.mark.parametrize("after", [False, True])
def test_review_write_crash_resumes_without_duplicates(learning_run, monkeypatch, after):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    replace = safefs.write_text
    def crash(repo, rel, text):
        if rel.endswith("-run.md") and "hit_id:" in text:
            if after:
                replace(repo, rel, text)
            raise KeyboardInterrupt()
        replace(repo, rel, text)
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(KeyboardInterrupt):
        steps.check_changed(ctx, task)
    monkeypatch.setattr(safefs, "write_text", replace)
    resumed = phase.load(task.dir)
    steps.check_changed(ctx, resumed)
    steps.guard_step(ctx, resumed)
    assert len(inherited_items(ctx)) == 2


def test_existing_report_and_inspection_findings_survive(learning_run, monkeypatch):
    from school_notes2.flows import inspection
    from types import SimpleNamespace
    ctx, task = learning_run
    old = old_questions(ctx, task)
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    steps.check_changed(ctx, task)
    monkeypatch.setattr(inspection, "role", lambda *a: SimpleNamespace(role=SimpleNamespace(model="test", effort="high")))
    saved = {"findings": [{"file": TOPIC, "problem": "Reader finding.", "quote": "Changed.",
                           "origin": "reader", "category": "content", "relates_to": None}],
             "notes": [], "pages": [], "receipts": {}}
    inspection._apply(ctx, task, saved)
    inspection._apply(ctx, task, saved)
    assert len(relations.inventory(ctx.notes_path)["items"]) == 3


def test_correction_inherits_parent_run_report(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    parent = "docs/review/parent-run.md"
    files.write_review(ctx.notes_path, task.data["created"][:10], {"verdict": "ok", "findings": []},
                       "reader", task.get("base"), task.get("base"), path=ctx.notes_path / parent)
    task.update(inspection_report=parent, correction_parent="parent")
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    steps.check_changed(ctx, task)
    assert len(files.review_files(ctx.notes_path)) == 1
    assert task.get("inspection_report") == parent and len(inherited_items(ctx)) == 2


def test_existing_open_problem_without_machine_id_is_not_duplicated(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    problem = wiki_check.errors(wiki_check.check_files(ctx.notes_path, [TOPIC]))[0]["message"]
    files.write_review(ctx.notes_path, "2026-10-01", {"verdict": "changes", "findings": [
        {"id": "R1", "file": TOPIC, "problem": problem}]}, "legacy", task.get("base"), task.get("base"))
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    steps.check_changed(ctx, task)
    assert len(inherited_items(ctx)) == 1
    assert len(relations.inventory(ctx.notes_path)["items"]) == 2
    # Later runs also recognize the same machine keys without opening new items.
    next_task = phase.create(task.dir.parent, ctx.name, "notes", "cron", "writing")
    next_task.update(base=task.get("base"), ranges=[[0, 0]])
    steps.check_changed(ctx, next_task)
    assert len(relations.inventory(ctx.notes_path)["items"]) == 2


@pytest.mark.parametrize("folder", ["wiki/assets", "wiki/assets/a", "wiki/assets/a/deep"])
def test_old_render_error_uses_base_assets_and_recursive_receipts(learning_run, folder):
    import hashlib
    ctx, task = learning_run
    source, output = folder + "/source.svg", folder + "/output.png"
    safefs.write_text(ctx.notes_path, source, "<svg/>\n")
    safefs.write_bytes(ctx.notes_path, output, b"old output")
    safefs.write_json(ctx.notes_path, folder + "/render.json", {
        "source": source, "source_sha256": hashlib.sha256(b"<svg/>\n").hexdigest(),
        "outputs": {"output.png": {"sha256": "0" * 64}}})
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "old render error")
    task.update(base=wt.out("rev-parse", "HEAD").strip())
    steps.check_changed(ctx, task)
    assert len(inherited_items(ctx)) == 1
    safefs.write_text(ctx.notes_path, source, "<svg>new</svg>\n")
    with pytest.raises(steps.CheckFailed) as failure:
        steps.check_changed(ctx, task)
    assert len(failure.value.items) == 1 and "source changed" in failure.value.items[0]["message"]
