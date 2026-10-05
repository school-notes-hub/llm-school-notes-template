"""P4/P5 isolation, bounded provenance and upgrade continuation (fix 41)."""

import pytest

from school_notes2.flows import correction, correction_calls, correction_round, recheck, review_phases, writer
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from school_notes2.wiki import frontmatter
from .test_completion39 import backlog


@pytest.mark.parametrize("mode", ["interactive", "repair"])
def test_scoped_p4_excludes_backlog(setup, mode):
    ctx, task, page = setup
    old = backlog(ctx, page)
    own = "docs/review/own.md"
    safefs.write_text(ctx.notes_path, own, safefs.read_text(ctx.notes_path, old))
    task.data["mode"] = "interactive" if mode == "interactive" else "cron"
    task.update(mode=mode, inspection_report=own)
    assert [i["file"] for i in correction.assigned(ctx, task)] == [own]
    from school_notes2.flows import set_aside
    task.update(correction_items=correction.assigned(ctx, task))
    assert set_aside.work(task) == [own + "#R1"]


@pytest.mark.parametrize("depth", [0, 2, 3])
@pytest.mark.parametrize("legacy", [False, True])
def test_p5_depth_and_legacy_supplement_replay(setup, depth, legacy):
    ctx, task, page = setup
    path = backlog(ctx, page)
    text = safefs.read_text(ctx.notes_path, path)
    meta = frontmatter.split(text).meta
    meta["item_details"]["R1"]["chain"] = depth
    safefs.write_text(ctx.notes_path, path, frontmatter.set_keys(text, meta))
    listed = files.open_items(ctx.notes_path, "cron")
    closures = [{"file": path, "item_id": "R1", "status": "fixed"}]
    files.apply_closure(ctx.notes_path, "a", closures, listed, automatic=True)
    before = task.dir / "before"
    before.mkdir()
    safefs.write_text(before, page, "Old.\n")
    safefs.write_text(ctx.notes_path, page, "Changed.\n")
    task.update(inspection_report=path, correction_round=1)
    saved = {"receipts": {}, "units": [{"status": "reviewed", "model": "fake", "unit": {"pages": [page]},
        "before": str(before), "items": [{**closures[0], "key": path + "#R1"}], "hits": [],
        "review": {"items": [], "hits": [], "owner_notes": [], "findings": [{"file": page,
            "quote": "Changed.", "problem": "Új hiba.", "category": "pontosság", "severity": "hiba",
            "relates_to": None, "item_key": None}]}}]}
    recheck.apply(ctx, task, saved)
    if legacy:
        text = safefs.read_text(ctx.notes_path, path)
        safefs.write_text(ctx.notes_path, path, frontmatter.set_keys(text, {"supplements": ["recheck-1"]}))
    first = safefs.read_bytes(ctx.notes_path, path)
    recheck.apply(ctx, phase.load(task.dir), saved)
    assert safefs.read_bytes(ctx.notes_path, path) == first
    known = relations.inventory(ctx.notes_path)["items"]
    assert len(known) == 2
    assert known[path + "#R2"]["chain"] == depth + 1
    assert known[path + "#R2"]["status"] == ("owner" if depth == 3 else "open")
    assert known[path + "#R2"].get("repair_attempts", 0) == 0
    assert known[path + "#R1"]["repair_attempts"] == 1


def test_bound_p5_finding_keeps_location(setup):
    from .test_completion39 import test_p5_new_error_has_own_item_or_reopens_exact_key
    test_p5_new_error_has_own_item_or_reopens_exact_key(setup, True)
    ctx, task, page = setup
    detail = relations.inventory(ctx.notes_path)["items"][task.get("inspection_report") + "#R2"]
    assert page in detail["recheck"]["answer"] and "Changed." in detail["recheck"]["answer"]


def test_attempt_round_identity(setup):
    _, task, _ = setup
    task.update(attempt=2, correction_round=3)
    assert correction_round.identity(task) == task.run_id + "-fix-a2-r3"
    assert correction_round.identity(task, 1) == task.run_id + "-fix-a2-r1"


@pytest.mark.parametrize("main_writer", [False, True])
@pytest.mark.parametrize("crash", [None, "undo", "undo_partial", "result", "cleanup"])
@pytest.mark.parametrize("retry_ok", [False, True])
@pytest.mark.parametrize("failure_stage", ["invoke", "check"])
def test_p4_call_failure_preserves_success_and_resumes(setup, monkeypatch, crash, retry_ok, failure_stage, main_writer):
    ctx, parent, page = setup
    other = "wiki/n/topic.md"
    safefs.write_text(ctx.notes_path, other, "Before.\n")
    path = backlog(ctx, page)
    report2 = files.write_review(ctx.notes_path, "2026-10-04", {"findings": [
        {"id": "R1", "file": other, "problem": "Hiba.", "category": "pontosság"}],
        "verdict": "changes"}, "old", "a", "b").relative_to(ctx.notes_path).as_posix()
    third = "wiki/o/topic.md"
    safefs.write_text(ctx.notes_path, third, "Third.\n")
    report3 = files.write_review(ctx.notes_path, "2026-10-05", {"findings": [
        {"id": "R1", "file": third, "problem": "Hiba.", "category": "pontosság"}],
        "verdict": "changes"}, "old", "a", "b").relative_to(ctx.notes_path).as_posix()
    items = correction.assigned(ctx, parent)
    root = correction_round.root(parent)
    correction.snapshot(ctx.notes_path, root)
    child = correction.child_task(ctx, parent, root, items)
    child.update(infographic_policy=False)
    if main_writer:
        child.update(correction_parent=None)
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    calls = []
    def invoke(ctx, task, k, *args):
        calls.append(k)
        target = {1: page, 2: other, 3: third}[k]
        safefs.write_text(ctx.notes_path, target, "Success.\n" if k == 1 else "Failed edit.\n")
        if failure_stage == "invoke" and k == 2 and (not retry_ok or calls.count(2) == 1):
            raise correction.steps.CheckFailed([{"file": other, "line": 1, "message": "bad output"}])
        result = {"status": "done", "review_closure": [{"file": {1: path, 2: report2, 3: report3}[k],
                "item_id": "R1", "status": "fixed"}]}
        safefs.write_json(ctx.notes_path, ".school-notes/result.json", result)
        return result
    monkeypatch.setattr(writer, "_invoke", invoke)
    def check_call(ctx, task, k, result):
        if failure_stage == "check" and k == 2 and (not retry_ok or calls.count(2) == 1):
            raise correction.steps.CheckFailed([{"file": other, "line": 1, "message": "bad output"}])
    monkeypatch.setattr(writer, "_check_call", check_call)
    fired = []
    original_restore = correction_calls.restore
    def restore(*args):
        if crash == "undo_partial" and not fired:
            fired.append(True)
            correction.restore(ctx.notes_path, args[2])
            raise KeyboardInterrupt
        original_restore(*args)
        if crash == "undo" and not fired:
            fired.append(True)
            raise KeyboardInterrupt
    monkeypatch.setattr(correction_calls, "restore", restore)
    original_write = writer.write_json
    def write_json(target, value):
        if crash == "result" and target.name == "result-2.json" and not fired:
            fired.append(True)
            raise KeyboardInterrupt
        return original_write(target, value)
    monkeypatch.setattr(writer, "write_json", write_json)
    original_cleanup = correction_calls.cleanup
    def cleanup(task, k):
        if crash == "cleanup" and k == 2 and not fired:
            fired.append(True)
            raise KeyboardInterrupt
        original_cleanup(task, k)
    monkeypatch.setattr(correction_calls, "cleanup", cleanup)
    if crash:
        with pytest.raises(KeyboardInterrupt):
            writer.run_ranges(ctx, child, {})
        child = phase.load(child.dir)
    writer.run_ranges(ctx, child, {})
    writer.run_ranges(ctx, phase.load(child.dir), {})
    assert not list(child.dir.glob("call-*/before"))
    assert not child.get("set_aside")
    assert calls.count(1) == 1
    assert calls.count(2) == 2 and calls.count(3) == 1
    assert safefs.read_text(ctx.notes_path, page) == "Success.\n"
    assert safefs.read_text(ctx.notes_path, other) == ("Failed edit.\n" if retry_ok else "Before.\n")
    result = writer.merge(writer.results(child))
    outcome = files.apply_closure(ctx.notes_path, correction_round.identity(parent),
                                 result["review_closure"], items, automatic=True)
    known = relations.inventory(ctx.notes_path)["items"]
    assert known[path + "#R1"]["status"] == "fixed"
    assert known[report2 + "#R1"]["status"] == ("fixed" if retry_ok else "open")
    assert known[report2 + "#R1"]["repair_attempts"] == 1
    assert known[report3 + "#R1"]["status"] == "fixed"
    if not retry_ok:
        assert correction.assigned(ctx, child) == []


def test_chain_does_not_reset_on_a_related_page_without_its_own_closure():
    known = {"report#R1": {"file": "wiki/a/topic.md", "chain": 3, "repair_attempts": 2}}
    source = {"key": "report#R1", "file": "report", "item_id": "R1", "status": "fixed"}
    assert recheck.source_chain(known, {"items": []}, {"file": "wiki/a/summary.md"}, [source]) == 3


def test_failed_call_does_not_require_an_infographic_decision(setup, monkeypatch):
    from school_notes2.flows import fetch
    from school_notes2.wiki.check_result import check_result
    ctx, task, page = setup
    path = backlog(ctx, page)
    items = files.open_items(ctx.notes_path, "cron")
    child = correction.child_task(ctx, task, correction_round.root(task), items)
    child.update(failed_fix_calls=[1])
    supplied = fetch.fetch_json(child, 1, grade=9, repo=ctx.notes_path, whole_run=True)
    result = correction_calls.failed_result(child, 1)
    supplied = correction_calls.successful_fetch(ctx, child, supplied)
    assert not check_result(ctx.notes_path, result, supplied, {(path, "R1")})


def test_severity_defaults_only_legacy_missing_field():
    from school_notes2.review.severity import is_error
    assert is_error({}) and is_error({"severity": "hiba"})
    assert not is_error({"severity": "javaslat"})
