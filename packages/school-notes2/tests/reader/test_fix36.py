"""Scope rollback consumes a bounded attempt, with replay-safe owner escalation."""

import pytest

from school_notes2.flows import correction, finish, fix_scope, inspection, recheck, run, steps, writer
from school_notes2.notify import pending
from school_notes2.reader import calls, units
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.state.errors import BadWork
from school_notes2.wiki import check
from tests.conftest import recording_mailer
from .test_fix35 import NEW, OLD, OTHER
from .test_phases import finding, install_reader


def review(ctx, page):
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {**finding(page), "id": "R1"}]}, "fake", "a", "b")
    return files.open_items(ctx.notes_path, "cron")


def gates(monkeypatch):
    monkeypatch.setattr(writer, "write_changes", lambda *a: None)
    monkeypatch.setattr(steps, "guard_step", lambda *a: None)
    monkeypatch.setattr(steps, "order_step", lambda *a: [])
    def links(ctx, task, **kw):
        errors = check.check_links(ctx.notes_path, "wiki/m/topic.md", safefs.read_text(ctx.notes_path, "wiki/m/topic.md"))
        if errors:
            raise steps.CheckFailed(errors)
    monkeypatch.setattr(steps, "check_changed", links)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["p4", "fix"])
@pytest.mark.parametrize("target", ["new.md", "other.md", "./other.md#uj-resz"])
def test_three_scope_failures_become_owner_once(setup, monkeypatch, learner, mode, target):
    ctx, _, page = setup
    ctx.name = learner
    delivered = []
    ctx.mailer = recording_mailer(ctx.cfg.state_dir, ctx.log, monkeypatch, delivered)
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    items = review(ctx, page)
    before = safefs.read_text(ctx.notes_path, page)
    gates(monkeypatch)
    invoked = []
    def write(ctx, child, k, *args):
        invoked.append(child.run_id)
        safefs.write_text(ctx.notes_path, OTHER, OLD + "\n## Új rész\n")
        safefs.write_text(ctx.notes_path, NEW, "Új oldal.\n")
        safefs.write_text(ctx.notes_path, page, before + f"\n[Lásd](<{target}>)\n")
        return {"status": "done", "infographic_decisions": [{"page": page, "reason": "Szöveggel érthető."}],
                "review_closure": [{"file": items[0]["file"], "item_id": "R1", "status": "fixed"}]}
    monkeypatch.setattr(writer, "_call", write)
    for n in range(1, 4):
        task = phase.create(ctx.cfg.state_dir, learner, "notes", "cron", "writing", f"fix-{n}")
        task.update(base="base", ranges=[[0, 0]], packages=[], pages=[], inspection_report=items[0]["file"],
                    inspection_result={"status": "done"}, open_review_items=items)
        if mode == "fix":
            root = task.dir / "fix-before"
            correction.snapshot(ctx.notes_path, root)
            task.update(mode="fix", correction_before=str(root / "before"))
            assert run._write(ctx, task) == "done"
            fix_scope.resume(ctx, phase.load(task.dir))
        else:
            correction.run(ctx, task)
            correction.run(ctx, phase.load(task.dir))
        record = relations.inventory(ctx.notes_path)["items"][items[0]["key"]]
        assert record["repair_attempts"] == n
        assert record["status"] == ("owner" if n == 3 else "open")
        assert safefs.read_text(ctx.notes_path, page) == before
        assert task.get("tool_hashes")[items[0]["file"]]
        assert task.data["llm_failures"] == 0 and not task.data["needs_owner"]
        owners = [{"file": items[0]["file"], "item_id": "R1"}] if n == 3 else []
        assert run.owner_items(ctx, task, owners)
        assert run.owner_items(ctx, phase.load(task.dir), owners)
    assert len(invoked) == 3 and len(delivered) == 1
    assert safefs.read_json(pending.path(ctx).parent, pending.path(ctx).name) == {}


@pytest.mark.parametrize("mode", ["p4", "fix"])
@pytest.mark.parametrize("boundary", ["closure", "record"])
def test_scope_attempt_survives_rollback_crash(setup, monkeypatch, mode, boundary):
    ctx, task, page = setup
    items = review(ctx, page)
    root = task.dir / "fix-before" if mode == "fix" else inspection.folder(task) / "correction"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix" if mode == "fix" else "run", correction_before=str(root / "before"),
                open_review_items=items, correction_items=items)
    safefs.write_text(ctx.notes_path, NEW, "Új oldal.\n")
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n[Új](new.md)\n")
    fix_scope.recover(ctx, task, root, items)
    module, name = (files, "apply_closure") if boundary == "closure" else (steps, "record_tool_files")
    original = getattr(module, name)
    def crash(*args, **kwargs):
        value = original(*args, **kwargs)
        if boundary == "closure" or items[0]["file"] in args[-1]:
            raise KeyboardInterrupt()
        return value
    monkeypatch.setattr(module, name, crash)
    saved = {"status": "rollback", "reason": "scope dependency"}
    with pytest.raises(KeyboardInterrupt):
        if mode == "fix":
            fix_scope.rollback(ctx, task, steps.CheckFailed(fix_scope.dependency_items(ctx, root)))
        else:
            correction.apply(ctx, task, root, saved)
    monkeypatch.setattr(module, name, original)
    for _ in range(2):
        task = phase.load(task.dir)
        if mode == "fix":
            fix_scope.resume(ctx, task)
        else:
            correction.apply(ctx, task, root, saved)
        assert relations.inventory(ctx.notes_path)["items"][items[0]["key"]]["repair_attempts"] == 1
        assert task.get("tool_hashes")[items[0]["file"]]


@pytest.mark.parametrize("stage", ["write", "finish"])
@pytest.mark.parametrize("mixed", [False, True])
def test_unrelated_check_failure_is_not_swallowed(setup, monkeypatch, stage, mixed):
    ctx, task, page = setup
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.set_phase("writing", mode="fix", correction_before=str(root / "before"), retry_link_pages=[page])
    safefs.write_text(ctx.notes_path, NEW, "Új oldal.\n")
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\n$$\n[Új](new.md)\n")
    fix_scope.recover(ctx, task)
    problems = check.check_formulas(page, safefs.read_text(ctx.notes_path, page))
    if mixed:
        problems += fix_scope.dependency_items(ctx, root)
    def fail(*args, **kwargs):
        raise steps.CheckFailed(problems)
    monkeypatch.setattr(writer, "run_ranges", fail)
    monkeypatch.setattr(steps, "content_steps", fail)
    with pytest.raises(steps.CheckFailed) as exc:
        if stage == "write":
            run._write(ctx, task)
        else:
            finish.finish(ctx, task, notify_owner_items=lambda _: None)
    assert exc.value.items == problems and not task.get("fix_scope_rolled_back")


@pytest.mark.parametrize("changed", [False, True])
def test_only_changed_link_lines_depend_on_restored_page(setup, changed):
    ctx, task, page = setup
    root = task.dir / "fix-before"
    text = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, text + "\n[Lásd](other.md#resz)\n")
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix", correction_before=str(root / "before"), retry_link_pages=[page])
    safefs.write_text(ctx.notes_path, OTHER, OLD + "\nÚj rész.\n")
    text += "\n[Új cím](other.md#resz)\n" if changed else "\n[Lásd](other.md#resz)\n\nJavítás.\n"
    safefs.write_text(ctx.notes_path, page, text)
    fix_scope.recover(ctx, task)
    assert bool(fix_scope.dependency_items(ctx, root)) == changed


@pytest.mark.parametrize("mode", ["p4", "fix"])
def test_recheck_receives_sorted_restored_paths(setup, monkeypatch, mode):
    ctx, task, page = setup
    items = review(ctx, page)
    root = task.dir / "fix-before" if mode == "fix" else inspection.folder(task) / "correction"
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix" if mode == "fix" else "run")
    safefs.write_json(root, "scope-restores.json", [NEW, OTHER])
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page) + "\nJavítás.\n")
    install_reader(monkeypatch, page)
    original = calls.run
    seen = []
    def inspect_input(repo, view, folder, *args, **kwargs):
        seen.append(safefs.read_json(folder, "in/scope-restores.json"))
        return original(repo, view, folder, *args, **kwargs)
    monkeypatch.setattr(calls, "run", inspect_input)
    closure = {"file": items[0]["file"], "item_id": "R1", "status": "fixed"}
    recheck.check_unit(ctx, task, ctx.notes_path, units.collect(ctx.notes_path, [page])[0], [closure])
    assert seen == [[NEW, OTHER]]


def test_rejected_output_cannot_bypass_crash_limit(setup):
    ctx, task, _ = setup
    task.update(mode="fix", fix_calls={"1": 1}, writer_output_key="old", counted_bad_outputs=["old"])
    assert writer._fix_resume(ctx, task, 1) is None
    task = phase.load(task.dir)
    safefs.write_json(ctx.notes_path, ".school-notes/result.json", {"status": "done"})
    for _ in range(3):
        with pytest.raises(BadWork, match="interrupted twice"):
            writer._fix_resume(ctx, task, 1)
        assert task.get("fix_calls") == {"1": 2}


def test_generated_links_on_unassigned_page_are_not_author_dependencies(setup):
    ctx, task, page = setup
    root = task.dir / "fix-before"
    safefs.write_text(ctx.notes_path, OTHER, OLD)
    correction.snapshot(ctx.notes_path, root)
    task.update(mode="fix", correction_before=str(root / "before"))
    safefs.write_text(ctx.notes_path, OTHER, OLD + "\nNem kiosztott.\n")
    text = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, text + "\n<!-- school-notes:generated topics -->\n"
                      "[Másik](other.md)\n<!-- /school-notes:generated -->\n")
    fix_scope.recover(ctx, task)
    assert safefs.read_json(root, "scope-restores.json") == [OTHER]
    assert fix_scope.dependency_items(ctx, root) == []
