"""A skipped P5 leaves no unchecked change: the next P5 measures from the oldest unchecked round (fix-45b)."""

import pytest

from school_notes2.flows import correction, correction_round, learning, recheck, review_phases, steps
from school_notes2.reader import calls
from school_notes2.review import files
from school_notes2.state import phase, safefs
from school_notes2.wiki import check
from .test_phases import finding

OTHER = "wiki/m/other.md"
NEW_LINE = "Az első körben írt új állítás."


def start_round(ctx, task, n, closures=()):
    task.update(correction_round=n)
    root = correction_round.root(task)
    correction.snapshot(ctx.notes_path, root)
    task.update(correction_assignment_root=str(root),
                correction_result={"status": "done", "review_closure": list(closures)})
    return root


def broken_metadata(monkeypatch, page):
    def validate(ctx, task):
        if "type: rossz" in safefs.read_text(ctx.notes_path, page):
            raise steps.CheckFailed([check.item(page, 3, "Hibás metaadat: type")])
    monkeypatch.setattr(learning, "validate", validate)


def scenario(setup, monkeypatch):
    ctx, task, page = setup
    safefs.write_text(ctx.notes_path, OTHER, "---\ntitle: Másik\ntype: topic\n---\n# Másik\n\nRégi szöveg.\n")
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "changed", OTHER: "changed"})
    broken_metadata(monkeypatch, page)
    path = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {**finding(OTHER), "id": "R1", "quote": "Régi szöveg."}]}, "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    closure = {"file": path, "item_id": "R1", "status": "fixed"}
    task.set_phase("rechecking", mode="run", inspection_report=path)
    # Round n: a content change on another page and a metadata error that survives the round.
    root1 = start_round(ctx, task, 1, [closure])
    files.apply_closure(ctx.notes_path, task.run_id, [closure], [{"file": path, "item_id": "R1"}])
    safefs.write_text(ctx.notes_path, OTHER, safefs.read_text(ctx.notes_path, OTHER) + "\n" + NEW_LINE + "\n")
    good = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, good.replace("type: topic", "type: rossz"))
    return ctx, task, page, root1, closure, good


def reader(monkeypatch):
    seen = {}
    def review(repo, view, folder, stage, assigned, role, **kw):
        for p in safefs.read_json(folder, "in/pages.json"):
            seen[p["file"]] = str(p.get("changed_lines"))
        seen.setdefault("items", []).extend(i["key"] for i in assigned["items"])
        return {"status": "reviewed", "model": "fake/high", "review": {
            "items": [{"key": i["key"], "severity": "javaslat", "verdict": "ok", "answer": "Jó."}
                      for i in assigned["items"]], "hits": [], "findings": [], "owner_notes": []}}
    monkeypatch.setattr(calls, "run", review)
    return seen


@pytest.mark.parametrize("boundary", ["none", "between-rounds", "after-p5-stored"])
def test_skipped_p5_round_changes_reach_the_next_p5(setup, monkeypatch, boundary):
    ctx, task, page, root1, closure, good = scenario(setup, monkeypatch)
    seen = reader(monkeypatch)
    recheck.run(ctx, task)
    assert not seen and not safefs.is_file(recheck.inspection.folder(task), "p5-r1.json")
    assert task.get("p5_before") == str(root1) and task.get("p5_closures") == [closure]
    if boundary == "between-rounds":
        task = phase.load(task.dir)  # Crash after the skip: the durable task carries the pending tree.
        assert task.get("p5_before") == str(root1)
    # Round n+1 repairs only the YAML; its own pre-edit tree no longer differs on the other page.
    start_round(ctx, task, 2)
    safefs.write_text(ctx.notes_path, page, good)
    if boundary == "after-p5-stored":
        original = safefs.write_json
        def crash(root, rel, value):
            original(root, rel, value)
            if rel == "p5-r2.json":
                raise KeyboardInterrupt
        monkeypatch.setattr(safefs, "write_json", crash)
        with pytest.raises(KeyboardInterrupt):
            recheck.run(ctx, task)
        monkeypatch.setattr(safefs, "write_json", original)
        task = phase.load(task.dir)
        assert task.get("p5_before") == str(root1)
        calls_before = dict(seen)
        recheck.run(ctx, task)
        assert seen == calls_before  # The stored P5 is applied, not repeated.
    else:
        recheck.run(ctx, task)
    assert NEW_LINE in seen[OTHER]
    assert closure["file"] + "#R1" in seen["items"]
    saved = safefs.read_json(recheck.inspection.folder(task), "p5-r2.json")
    other = next(u for u in saved["units"] if u["unit"]["pages"] == [OTHER])
    assert other["status"] == "reviewed" and other["before"] == str(root1 / "before")
    assert phase.load(task.dir).get("p5_before") is None and not phase.load(task.dir).get("p5_closures")


def test_review_ready_with_unchecked_round_runs_p5_before_publication(setup, monkeypatch):
    ctx, task, page, root1, closure, good = scenario(setup, monkeypatch)
    seen = reader(monkeypatch)
    recheck.run(ctx, task)
    # The owner repaired the metadata outside a writer round; the run reaches review_ready.
    safefs.write_text(ctx.notes_path, page, good)
    task.set_phase("review_ready", machine_problems=[])
    monkeypatch.setattr(correction, "all_items", lambda *a: [])
    monkeypatch.setattr(review_phases.correction_figures, "waiting", lambda *a: [])
    order = []
    monkeypatch.setattr(review_phases, "finalize", lambda *a, **kw: order.append(("finalize", dict(seen))))
    review_phases.advance(ctx, task, lambda _: None)
    assert order and NEW_LINE in order[0][1][OTHER]
    assert task.phase == "finishing" and task.get("p5_before") is None


def test_review_ready_with_unchecked_round_and_metadata_error_does_not_publish(setup, monkeypatch):
    ctx, task, page, root1, closure, good = scenario(setup, monkeypatch)
    seen = reader(monkeypatch)
    recheck.run(ctx, task)
    task.set_phase("review_ready", machine_problems=[])
    finalized = []
    monkeypatch.setattr(review_phases, "finalize", lambda *a, **kw: finalized.append(1))
    monkeypatch.setattr(correction, "all_items", lambda *a: [{"file": "x", "item_id": "y"}])
    assert review_phases.advance(ctx, task, lambda _: None) == {"state": "machine_errors", "round": 2}
    assert not finalized and not seen and task.get("p5_before") == str(root1)
