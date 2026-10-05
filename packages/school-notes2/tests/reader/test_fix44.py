"""Restored targets only reject broken links, within the failing writer call."""

import json
from urllib.parse import quote

import pytest

from school_notes2.flows import correction, correction_calls, correction_round, fix_scope, steps, writer
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from .test_fix35 import OLD, OTHER


@pytest.mark.parametrize("target,broken", [
    ("other.md", False), ("./other.md#másik", False),
    ("other.md#" + quote("árvíztűrő-tükörfúrógép"), False),
    ("other.md#árvíztűrő-tükörfúrógép-1", False), ("other.md#kézi-horgony", False),
    ("other.md#hiányzó", True), ("new.md", True), ("new.md#hiányzó", True),
])
def test_dependency_requires_a_broken_restored_target(setup, target, broken):
    ctx, task, page = setup
    text = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, text + f"\nRégi szöveg [linkkel](<{target}>).\n")
    safefs.write_text(ctx.notes_path, OTHER, OLD + '\n## Árvíztűrő tükörfúrógép\n'
                      '\n## Árvíztűrő tükörfúrógép\n\n<a id="kézi-horgony"></a>\n')
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix", correction_before=str(root / "before"), retry_link_pages=[page])
    safefs.write_text(ctx.notes_path, page, text + f"\nJavított szöveg [linkkel](<{target}>).\n")
    safefs.write_text(ctx.notes_path, OTHER, OLD + "\n## Hiányzó\n")
    safefs.write_text(ctx.notes_path, "wiki/m/new.md", "Új oldal.\n")
    fix_scope.recover(ctx, task)
    assert bool(fix_scope.dependency_items(ctx, root)) == broken
    if broken:
        with pytest.raises(steps.CheckFailed):
            fix_scope.check_dependencies(ctx, task)
    else:
        fix_scope.check_dependencies(ctx, task)


def seven_calls(ctx, task, mode):
    pages = [f"wiki/s{n}/topic.md" for n in range(1, 8)]
    findings = []
    for n, (page, count) in enumerate(zip(pages, [6, 6, 6, 7, 1, 1, 15]), 1):
        safefs.write_text(ctx.notes_path, page, f"Eredeti {n}.\n" + (
            "Régi magyarázat [linkkel](../m/other.md#másik).\n" if n == 4 else ""))
        findings += [{"id": f"R{len(findings) + i + 1}", "file": page,
                      "problem": "Javítandó.", "category": "pontosság"} for i in range(count)]
    files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": findings},
                       "fake", "a", "b")
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    items = files.open_items(ctx.notes_path, "cron")
    task.update(infographic_policy=False)
    root = task.dir / "fix-before" if mode == "fix" else correction_round.root(task)
    correction.snapshot(ctx.notes_path, root)
    child = correction.child_task(ctx, task, root, items)
    if mode == "fix":
        task.set_phase("writing", **{**child.data["data"], "correction_parent": None})
        child = task
    return child, pages, items, root


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["fix", "p4"])
@pytest.mark.parametrize("crash", [None, "restore", "result"])
def test_seven_calls_preserve_success_and_resume(setup, monkeypatch, learner, mode, crash):
    ctx, parent, _ = setup
    ctx.name = learner
    child, pages, items, root = seven_calls(ctx, parent, mode)
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    monkeypatch.setattr(writer, "_check_call", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    monkeypatch.setattr(steps, "check_changed", lambda *a, **kw: None)
    invoked = []

    def invoke(ctx, task, k, *args):
        invoked.append(k)
        safefs.write_text(ctx.notes_path, pages[k - 1], f"Javítás {k}.\n" + (
            "Javított magyarázat [linkkel](../m/other.md#másik).\n" if k == 4 else ""))
        if k in (5, 6):
            safefs.write_text(ctx.notes_path, OTHER, OLD + "\n## Új rész\n")
            safefs.write_text(ctx.notes_path, pages[k - 1], "[Új](../m/other.md#új-rész)\n")
        return {"status": "done", "review_closure": [
            {"file": i["file"], "item_id": i["item_id"], "status": "fixed"}
            for i in task.get("calls")[k - 1]["open_review_items"]]}

    monkeypatch.setattr(writer, "_invoke", invoke)
    original_restore, original_write = correction_calls.restore, writer.write_json
    stopped = []

    def restore(ctx, task, folder, failure):
        original_restore(ctx, task, folder, failure)
        if crash == "restore" and task.get("writing_k") == 6 and not stopped:
            stopped.append(True)
            raise KeyboardInterrupt

    def write(path, result):
        original_write(path, result)
        if crash == "result" and path.name == "result-6.json" and not stopped:
            stopped.append(True)
            raise KeyboardInterrupt

    monkeypatch.setattr(correction_calls, "restore", restore)
    monkeypatch.setattr(writer, "write_json", write)

    def run():
        if mode == "p4":
            correction.run(ctx, phase.load(parent.dir))
        else:
            task = phase.load(child.dir)
            assert writer.run_ranges(ctx, task, {}) == "done"
            result = writer.merge(writer.results(task))
            files.apply_closure(ctx.notes_path, task.run_id, result["review_closure"], items, automatic=True)

    if crash:
        with pytest.raises(KeyboardInterrupt):
            run()
    run()
    run()
    assert invoked == [1, 2, 3, 4, 5, 5, 6, 6, 7]
    for k in range(1, 8):
        text = safefs.read_text(ctx.notes_path, pages[k - 1])
        assert (f"Eredeti {k}." if k in (5, 6) else f"Javítás {k}.") in text
    assert safefs.read_text(ctx.notes_path, OTHER) == OLD
    known = relations.inventory(ctx.notes_path)["items"]
    assert sum(i["status"] == "fixed" for i in known.values()) == 40
    assert sum(i["status"] == "open" for i in known.values()) == 2
    assert all(i["repair_attempts"] == 1 for i in known.values())
    assert phase.load(child.dir).get("failed_fix_calls") == [5, 6]
    assert not safefs.is_file(root, "rollback.json")
    events = [json.loads(line) for line in ctx.log.main.read_text().splitlines()]
    assert not any(e["action"] == "fix.scope_rollback" for e in events)


def test_isolated_fix_never_replays_whole_phase_rollback(setup):
    ctx, task, page = setup
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix", calls=[{"subject": "m"}], correction_before=str(root / "before"))
    text = "Megőrzendő javítás. [Új](new.md)\n"
    safefs.write_text(ctx.notes_path, page, text)
    safefs.write_json(root, "scope-restores.json", ["wiki/m/new.md"])
    safefs.write_json(root, "rollback.json", {"reason": "legacy dependency error"})
    assert not fix_scope.rollback(ctx, task, steps.CheckFailed(fix_scope.dependency_items(ctx, root)))
    fix_scope.resume(ctx, task)
    assert safefs.read_text(ctx.notes_path, page) == text


@pytest.mark.parametrize("mixed", [False, True])
def test_p4_late_dependency_retries_affected_call_without_phase_rollback(setup, monkeypatch, mixed):
    ctx, parent, _ = setup
    child, pages, items, root = seven_calls(ctx, parent, "p4")
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    monkeypatch.setattr(writer, "_check_call", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    def check_changed(ctx, task, **kw):
        problems = fix_scope.dependency_items(ctx, root)
        if mixed and problems:
            raise steps.CheckFailed(problems + [{"file": pages[1], "line": 1, "message": "Másik hiba."}])
    monkeypatch.setattr(steps, "check_changed", check_changed)
    invoked = []

    def invoke(ctx, task, k, *args):
        invoked.append(k)
        safefs.write_text(ctx.notes_path, pages[k - 1], f"Javítás {k}.\n")
        return {"status": "done", "review_closure": [
            {"file": i["file"], "item_id": i["item_id"], "status": "fixed"}
            for i in task.get("calls")[k - 1]["open_review_items"]]}

    monkeypatch.setattr(writer, "_invoke", invoke)
    original = writer.run_ranges
    injected = []

    def late_restore(ctx, task, handlers):
        result = original(ctx, task, handlers)
        if not injected:
            injected.append(True)
            safefs.write_text(ctx.notes_path, pages[0], "Javítás 1. [Új](../m/new.md)\n")
            safefs.write_text(ctx.notes_path, "wiki/m/new.md", "Visszaállítandó.\n")
        return result

    monkeypatch.setattr(writer, "run_ranges", late_restore)
    with pytest.raises(steps.CheckFailed):
        correction.run(ctx, parent)
    assert not safefs.is_file(root, "receipt.json")
    assert phase.load(child.dir).get("writing_k") == 1
    for k, page in enumerate(pages, 1):
        assert f"Javítás {k}." in safefs.read_text(ctx.notes_path, page)
    correction.run(ctx, phase.load(parent.dir))
    assert invoked == [1, 2, 3, 4, 5, 6, 7, 1] + ([2] if mixed else [])
    assert all(i["status"] == "fixed" for i in relations.inventory(ctx.notes_path)["items"].values())
    assert not phase.load(parent.dir).get("correction_rolled_back")
