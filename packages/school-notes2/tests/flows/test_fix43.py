"""Fix 43: inherited defects are host work, with stable attempts and conservative matching."""

import json

import pytest

from school_notes2.flows import correction, handlers, inherited_check, steps
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import check, frontmatter
from tests.flows.test_learning_checks import learning_run, TOPIC, NOTE
from tests.flows.test_inherited_check40 import old_questions, inherited_items


def commit(ctx, task):
    wt = ctx.worktree("notes")
    wt.run("add", "wiki")
    wt.run("commit", "-qm", "base defect")
    task.update(base=wt.out("rev-parse", "HEAD").strip())


def test_mcp_does_not_leave_a_fixed_legacy_item(learning_run):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    assert handlers.check(ctx, task)["ok"]
    assert not inherited_items(ctx)
    text = old.decode().replace("1. Első", "<!-- q: elso-one -->\n1. Első")
    text = text.replace("2. Második", "<!-- q: elso-two -->\n2. Második")
    safefs.write_text(ctx.notes_path, TOPIC, text)
    steps.check_changed(ctx, task)
    assert not inherited_items(ctx)


@pytest.mark.parametrize("before,after", [
    ("/home/old/private", "/home/new/private\n/home/old/private"),
    ("/home/old/private", "/home/new/private"),
    ("$$ old", "$$ new\n$$\n$$"),
    ("<!-- school-notes:generated old -->", "<!-- school-notes:generated new -->"),
    ("1. Régi kérdés?", "1. Új kérdés?"),
])
def test_new_matching_defect_is_blocking(learning_run, before, after):
    ctx, task = learning_run
    prefix = safefs.read_text(ctx.notes_path, TOPIC) + ("\n# Nyitott kérdések\n\n" if before.startswith("1.") else "\n")
    safefs.write_text(ctx.notes_path, TOPIC, prefix + before + "\n")
    commit(ctx, task)
    safefs.write_text(ctx.notes_path, TOPIC, prefix + after + "\n")
    items = check.check_files(ctx.notes_path, [TOPIC])
    result = inherited_check.classify(ctx, task, items)
    assert check.errors(result)
    assert not any(i.get("kind") == inherited_check.KIND for i in result)


def test_secrets_returns_every_occurrence():
    result = check.check_secrets("wiki/a.md", "/home/one/private\n/home/two/private\n/home/three/private")
    assert [i["line"] for i in result] == [1, 2, 3]


@pytest.mark.parametrize("broken", [b"---\nchapters: [\n---\n", b"\xff\xfe"])
def test_invalid_base_dependencies_keep_errors_blocking(learning_run, broken):
    ctx, task = learning_run
    index = "wiki/proba/index.md"
    original = safefs.read_bytes(ctx.notes_path, index)
    safefs.write_bytes(ctx.notes_path, index, broken)
    commit(ctx, task)
    safefs.write_bytes(ctx.notes_path, index, original)
    text = safefs.read_text(ctx.notes_path, TOPIC) + "\n[Broken](missing.md)\n"
    safefs.write_text(ctx.notes_path, TOPIC, text)
    with pytest.raises(steps.CheckFailed):
        steps.check_changed(ctx, task)
    rows = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    assert sum(row["action"] == "check.base" for row in rows) == 1
    assert not inherited_items(ctx)


@pytest.mark.parametrize("crash_after", [False, True])
def test_fixed_inherited_hit_reopens_same_item_until_owner(learning_run, monkeypatch, crash_after):
    ctx, task = learning_run
    old = old_questions(ctx, task)
    safefs.write_bytes(ctx.notes_path, TOPIC, old + b"\nChanged.\n")
    steps.check_changed(ctx, task)
    path = task.get("inspection_report")
    hits = {i["hit_id"] for i in inherited_items(ctx)}
    assert {i["quote"] for i in inherited_items(ctx)} == {"1. Első kérdés?", "2. Második kérdés?"}
    original = safefs.write_text
    fired = []
    for n in range(1, 4):
        text = safefs.read_text(ctx.notes_path, path)
        safefs.write_text(ctx.notes_path, path, frontmatter.set_keys(text, {"items": {"R1": "fixed", "R2": "fixed"}}))
        next_task = phase.create(task.dir.parent, ctx.name, "notes", "cron", "writing")
        next_task.update(base=task.get("base"), ranges=[[0, 0]])
        def crash(repo, rel, text):
            if rel == path and not fired:
                fired.append(True)
                if crash_after:
                    original(repo, rel, text)
                raise KeyboardInterrupt
            original(repo, rel, text)
        if n == 1:
            monkeypatch.setattr(safefs, "write_text", crash)
            with pytest.raises(KeyboardInterrupt):
                steps.check_changed(ctx, next_task)
            monkeypatch.setattr(safefs, "write_text", original)
            next_task = phase.load(next_task.dir)
        steps.check_changed(ctx, next_task)
        steps.check_changed(ctx, phase.load(next_task.dir))
        found = inherited_items(ctx)
        assert len(found) == 2 and {i["hit_id"] for i in found} == hits
        assert all(i["repair_attempts"] == n for i in found)
        assert all(i["status"] == ("owner" if n == 3 else "open") for i in found)


def test_repair_related_lesson_defects_wait_for_own_rewrite(learning_run):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(mode="repair", repair_targets=[{"page": TOPIC, "kind": "topic", "related": [NOTE]}])
    # Only the link destination changes, within the authorized repair scope.
    text = safefs.read_text(ctx.notes_path, NOTE).replace("Az eredeti hosszú jegyzet.", "[Téma](elso.md)")
    safefs.write_text(ctx.notes_path, NOTE, text)
    commit(ctx, task)
    safefs.write_text(ctx.notes_path, NOTE, text.replace("](elso.md)", "](elso.md#tema)"))
    steps.check_changed(ctx, task)
    assert not inherited_items(ctx)
    assert correction.assigned(ctx, task) == []
    # The lesson's own later assignment does get the retained defects.
    task.update(repair_targets=[{"page": NOTE, "kind": "lesson-notes", "related": []}])
    steps.check_changed(ctx, task)
    assert inherited_items(ctx)


def test_three_fix_calls_finish_with_only_middle_open(learning_run, monkeypatch):
    from school_notes2.flows import finish, inspection, writer
    from school_notes2.sources import calls
    ctx, task = learning_run
    pages = [TOPIC, "wiki/proba/masodik.md", "wiki/proba/harmadik.md"]
    original = safefs.read_text(ctx.notes_path, TOPIC)
    for k, page in enumerate(pages[1:], 2):
        safefs.write_text(ctx.notes_path, page, original.replace("order: 10", f"order: {k * 10}"))
    report = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{k}", "file": page, "problem": "Hiba."} for k, page in enumerate(pages, 1)]},
        "test", task.get("base"), task.get("base")).relative_to(ctx.notes_path).as_posix()
    wt = ctx.worktree("notes")
    wt.run("add", "wiki", "docs")
    wt.run("commit", "-qm", "three assigned pages")
    listed = files.open_items(ctx.notes_path, "cron")
    assigned = [calls._fix_call(ctx.notes_path, "proba", [i]) for i in listed]
    task.data["mode"] = "cron"
    task.update(mode="fix", base=wt.out("rev-parse", "HEAD").strip(), calls=assigned,
                ranges=calls.ranges(assigned), open_review_items=listed, assigned_work=[],
                pending_figures=[], infographic_policy=False)
    invoked = []
    def write(ctx, task, k, *args):
        if task.get("correction_parent"):
            for target in pages:
                safefs.write_text(ctx.notes_path, target, safefs.read_text(ctx.notes_path, target).replace("[Broken](missing.md)", "Javítva."))
            return {"status": "done", "review_closure": [
                {"file": i["file"], "item_id": i["item_id"], "status": "fixed"}
                for i in task.get("calls")[k - 1]["open_review_items"]]}
        invoked.append(k)
        page = pages[k - 1]
        text = safefs.read_text(ctx.notes_path, page)
        safefs.write_text(ctx.notes_path, page, text + ("\n[Broken](missing.md)\n" if k == 2 else "\nJavítva.\n"))
        return {"status": "done", "review_closure": [{"file": report, "item_id": f"R{k}", "status": "fixed"}]}
    monkeypatch.setattr(writer, "_call", write)
    assert writer.run_ranges(ctx, task, {}) == "done"
    monkeypatch.setattr(inspection, "inspect", lambda *a: None)
    from school_notes2.reader import calls as reader_calls
    monkeypatch.setattr(reader_calls, "run", lambda *a, **kw: {"status": "not_checked"})
    built = []
    monkeypatch.setattr(finish, "_build", lambda ctx, task, commit: built.append(commit) or {"commit": commit})
    assert finish.finish(ctx, task, notify_owner_items=lambda _: None) == "done"
    assert invoked == [1, 2, 2, 3] and len(built) == 1
    known = relations.inventory(ctx.notes_path)["items"]
    assert [known[report + f"#R{k}"]["status"] for k in range(1, 4)] == ["fixed", "fixed", "fixed"]
    assert known[report + "#R2"]["repair_attempts"] == 1
    assert "Javítva." in safefs.read_text(ctx.notes_path, pages[0])
    assert "Javítva." in safefs.read_text(ctx.notes_path, pages[2])
    assert "Broken" not in safefs.read_text(ctx.notes_path, pages[1])
    assert not task.get("set_aside") and not list(task.dir.glob("call-*/before"))
