"""A complete fix queue uses resumable calls and stops after zero progress."""

from types import SimpleNamespace

import pytest

from school_notes2.flows import fetch, fix_progress, writer
from school_notes2.review import files
from school_notes2.sources import calls
from school_notes2.state import phase, safefs
from school_notes2.wiki.check_result import check_closures


@pytest.mark.parametrize("learner", ["one", "two"])
def test_complete_queue_figures_first_and_resume_each_call(tmp_path, monkeypatch, learner):
    repo = tmp_path / "repo"
    repo.mkdir()
    report = files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{n}", "file": f"wiki/{'a' if n <= 71 else 'b'}/topic.md", "problem": f"Hiba {n}."}
        for n in range(1, 112)]}, "fake", "a", "b")
    items = files.open_items(repo, "cron")
    waiting = [{"commission": {"id": fid, "page": f"wiki/{subject}/topic.md"}}
               for fid, subject in (("banner-a", "a"), ("banner-b", "b"))]
    grouping = calls.fix_assignments(repo, items, waiting)
    assert grouping == calls.fix_assignments(repo, items[::-1], waiting[::-1])
    assert grouping[0]["pending_figure_ids"] == ["banner-a", "banner-b"]
    assert all(not c["pending_figure_ids"] for c in grouping[1:])
    assert [len(c["open_review_items"]) for c in grouping] == [30, 30, 11, 30, 10]
    assert [i for c in grouping for i in c["open_review_items"]] == items
    task = phase.create(tmp_path / "tasks", learner, "notes", "cron", "prepared")
    task.update(mode="fix", calls=grouping, ranges=calls.ranges(grouping), open_review_items=items,
                pending_figures=waiting, packages=[], pages=[], writing_k=1)
    # The first call receives both subjects' figures; later calls never receive them.
    monkeypatch.setattr(fetch, "validate", lambda *a: None)
    assert len(fetch.fetch_json(task, 1, grade=9)["pending_figures"]) == 2
    assert all(not fetch.fetch_json(task, k, grade=9)["pending_figures"] for k in range(2, 6))
    invoked = []
    ctx = SimpleNamespace(notes_path=repo, cfg=SimpleNamespace(role=lambda _: (None, None), limits=SimpleNamespace(max_agents=3)))
    monkeypatch.setattr(writer, "write_inputs", lambda *a: None)
    monkeypatch.setattr(writer, "_call", lambda ctx, task, k, *a: invoked.append(k) or {"status": "done"})
    monkeypatch.setattr(writer, "_check_call", lambda *a: None)
    original = writer.write_json
    def crash(path, value):
        original(path, value)
        raise KeyboardInterrupt()
    monkeypatch.setattr(writer, "write_json", crash)
    for k in range(1, 6):
        with pytest.raises(KeyboardInterrupt):
            writer.run_ranges(ctx, phase.load(task.dir), None)
        assert invoked == list(range(1, k + 1))
    monkeypatch.setattr(writer, "write_json", original)
    assert writer.run_ranges(ctx, phase.load(task.dir), None) == "done"
    assert invoked == list(range(1, 6))
    closures = [{**i, "status": "fixed"} for i in items]
    assert check_closures(repo, {"review_closure": closures}, {(i["file"], i["item_id"]) for i in items}, 20) == []


def test_fix_must_account_for_every_assigned_item(tmp_path):
    from school_notes2.wiki.check_result import check_result
    fetch_data = {"mode": "fix", "pages": [], "packages": [], "range": {"from": 0, "to": 0}}
    problems = check_result(tmp_path, {"status": "done"}, fetch_data, {("docs/review/old.md", "R1")})
    assert any("every assigned item" in p["message"] for p in problems)


def test_fix_preparation_restores_all_pending_commissions(tmp_path, log, monkeypatch):
    from school_notes2.flows import fix
    from tests.flows.test_repair import context
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    base = ctx.worktree("notes").out("rev-parse", "HEAD").strip()
    waiting = [{"commission": {"id": "first", "page": page, "kind": "banner"}},
               {"commission": {"id": "second", "page": "wiki/other/topic.md", "kind": "figure"}}]
    task.update(mode="fix", base=base, pending_figures=waiting)
    fix.prepare(ctx, task)
    for entry in waiting:
        fid = entry["commission"]["id"]
        assert safefs.read_json(ctx.notes_path, f".school-notes/figures/{fid}.json") == entry["commission"]
    assert task.get("calls")[0]["pending_figure_ids"] == ["first", "second"]


def test_finish_errors_resume_the_assigned_page_call(tmp_path, monkeypatch):
    from school_notes2.flows import call_scope
    repo = tmp_path / "repo"
    repo.mkdir()
    pages = ["wiki/a/first.md", "wiki/a/first.md", "wiki/a/second.md", "wiki/b/topic.md"]
    files.write_review(repo, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{n}", "file": page, "problem": f"Hiba {n}."}
        for n, page in enumerate(pages, 1)]}, "fake", "a", "b")
    waiting = [{"commission": {"id": "banner", "page": "wiki/b/figure.md"}}]
    grouping = calls.fix_assignments(repo, files.open_items(repo, "cron"), waiting, limit=1)
    task = phase.create(tmp_path / "tasks", "one", "notes", "cron", "prepared")
    task.update(mode="fix", calls=grouping, ranges=calls.ranges(grouping), pending_figures=waiting)
    ctx = SimpleNamespace(notes_path=repo)
    defects = [{"file": p, "line": None, "message": "bad output"} for p in (pages[2], "wiki/b/figure.md")]
    assert call_scope.current(ctx, task, defects, 1) == defects
    assert call_scope.current(ctx, task, defects, 3) == defects
    shared = [{"file": pages[0], "message": "shared page error"}]
    assert all(call_scope.current(ctx, task, shared, k) == shared for k in (1, 2))
    for k in range(1, 5):
        safefs.write_json(task.dir, f"result-{k}.json", {"status": "done"})
    original = call_scope.invalidate
    monkeypatch.setattr(call_scope, "invalidate", lambda _: None)
    call_scope.retry(ctx, task, defects)
    resumed = phase.load(task.dir)
    assert resumed.get("retry_calls") == [1, 3]
    original(resumed)
    assert not (task.dir / "result-1.json").exists() and not (task.dir / "result-3.json").exists()
    assert all((task.dir / f"result-{k}.json").exists() for k in (2, 4))


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("reason", ["program", "no-progress"])
def test_fix_admission_uses_external_version_bound_work_stop(tmp_path, log, monkeypatch, learner, reason):
    from school_notes2.flows import fix, set_aside
    from tests.flows.test_repair import context
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    version = ["2.5.0"]
    ctx.release = lambda: version[0]
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    report = {"verdict": "changes", "findings": [{"id": "R1", "file": page, "problem": "Hiba."}]}
    files.write_review(ctx.notes_path, "2026-10-05", report, "fake", "a", "b")
    task = fix.next_task(ctx)
    if reason == "no-progress":
        fix_progress.record(ctx, task)
    else:
        set_aside.record(ctx, task, reason)
    task.set_phase("done")
    assert fix.next_task(ctx) is None
    files.write_review(ctx.notes_path, "2026-10-05", report, "fake", "a", "b")
    fresh = fix.next_task(ctx)
    assert len(fresh.get("open_review_items")) == 1
    version[0] = "2.5.1"
    assert len(fix.next_task(ctx).get("open_review_items")) == 2


@pytest.mark.parametrize("learner", ["one", "two"])
def test_repair_admission_skips_stopped_topic_without_writing_queue(tmp_path, log, monkeypatch, learner):
    from school_notes2.flows import repair, set_aside
    from school_notes2.repair import queue
    from tests.flows.test_repair import context
    from tests.flows.test_repair_queue import page as add_page
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    add_page(ctx.notes_path, "b")
    safefs.write_json(ctx.notes_path, queue.PATH, queue.build(ctx.notes_path))
    original = safefs.read_bytes(ctx.notes_path, queue.PATH)
    task = phase.create(ctx.task_root(), learner, "notes", "cron", "correcting")
    task.update(mode="repair", repair_topic=page)
    version = ["2.5.0"]
    ctx.release = lambda: version[0]
    set_aside.record(ctx, task, "program")
    monkeypatch.setattr(repair, "start", lambda ctx, topic: topic)
    assert repair.next_task(ctx) == "wiki/m/b.md"
    assert safefs.read_bytes(ctx.notes_path, queue.PATH) == original
    version[0] = "2.5.1"
    assert repair.next_task(ctx) == page
