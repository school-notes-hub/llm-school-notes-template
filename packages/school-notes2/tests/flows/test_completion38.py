"""A complete fix queue uses resumable calls; work without progress waits 24 hours."""

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
    # 6b: pending figures get their own calls, one per subject, after the text work.
    assert [c["pending_figure_ids"] for c in grouping] == [[]] * 5 + [["banner-a"], ["banner-b"]]
    assert [len(c["open_review_items"]) for c in grouping] == [30, 30, 11, 30, 10, 0, 0]
    assert [c["subject"] for c in grouping[5:]] == ["a", "b"]
    assert [i for c in grouping for i in c["open_review_items"]] == items
    task = phase.create(tmp_path / "tasks", learner, "notes", "cron", "prepared")
    task.update(mode="fix", calls=grouping, ranges=calls.ranges(grouping), open_review_items=items,
                pending_figures=waiting, packages=[], pages=[], writing_k=1)
    # Text calls never receive a figure; each figure call receives only its own.
    monkeypatch.setattr(fetch, "validate", lambda *a: None)
    assert all(not fetch.fetch_json(task, k, grade=9)["pending_figures"] for k in range(1, 6))
    assert [len(fetch.fetch_json(task, k, grade=9)["pending_figures"]) for k in (6, 7)] == [1, 1]
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
    for k in range(1, 8):
        with pytest.raises(KeyboardInterrupt):
            writer.run_ranges(ctx, phase.load(task.dir), None)
        assert invoked == list(range(1, k + 1))
    monkeypatch.setattr(writer, "write_json", original)
    assert writer.run_ranges(ctx, phase.load(task.dir), None) == "done"
    assert invoked == list(range(1, 8))
    closures = [{**i, "status": "fixed"} for i in items]
    assert check_closures(repo, {"review_closure": closures}, {(i["file"], i["item_id"]) for i in items}, 20) == []


def test_item_without_a_decision_stays_open_and_is_no_error(tmp_path):
    """#17: a missing closure decision is not a failure; the item simply stays open."""
    from school_notes2.wiki.check_result import check_result
    fetch_data = {"mode": "fix", "pages": [], "packages": [], "range": {"from": 0, "to": 0}}
    assert check_result(tmp_path, {"status": "done"}, fetch_data, {("docs/review/old.md", "R1")}) == []


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
    assert [c["pending_figure_ids"] for c in task.get("calls")] == [["first"], ["second"]]


class Clock:
    """A settable clock for the 24-hour time brake."""
    from datetime import datetime as _dt
    at = None

    @classmethod
    def now(cls, tz=None):
        return cls.at

    @classmethod
    def fromisoformat(cls, value):
        return cls._dt.fromisoformat(value)


@pytest.mark.parametrize("learner", ["one", "two"])
def test_zero_progress_parks_only_the_stalled_work_for_24_hours(tmp_path, log, monkeypatch, learner):
    """#21/Fable 15: the brake is per item and time-based, never per release or per run."""
    from datetime import datetime, timedelta
    from school_notes2.flows import fix
    from school_notes2.log import TZ
    from tests.flows.test_repair import context
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(max_agents=3)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    Clock.at = datetime(2026, 10, 5, 10, tzinfo=TZ)
    monkeypatch.setattr(fix_progress, "datetime", Clock)
    report = {"verdict": "changes", "findings": [{"id": "R1", "file": page, "problem": "Hiba."}]}
    files.write_review(ctx.notes_path, "2026-10-05", report, "fake", "a", "b")
    task = fix.next_task(ctx)
    task.set_phase("review_ready")
    fix_progress.record(ctx, task)
    assert task.get("fix_stalled") == task.get("fix_work")
    task.set_phase("done")
    assert fix.next_task(ctx) is None
    files.write_review(ctx.notes_path, "2026-10-05", report, "fake", "a", "b")
    assert len(fix.next_task(ctx).get("open_review_items")) == 1  # New work is not parked.
    Clock.at += timedelta(hours=24, seconds=1)
    assert len(fix.next_task(ctx).get("open_review_items")) == 2


def test_progressed_item_is_not_parked(tmp_path, log, monkeypatch):
    from tests.flows.test_repair import context
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    path = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{n}", "file": page, "problem": "Hiba."} for n in (1, 2)]}, "fake", "a", "b")
    rel = path.relative_to(ctx.notes_path).as_posix()
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "review_ready")
    listed = files.open_items(ctx.notes_path, "cron")
    files.apply_closure(ctx.notes_path, task.run_id, [{"file": rel, "item_id": "R1", "status": "fixed"}], listed,
                        automatic=True)
    task.update(mode="fix", fix_work=[rel + "#R1", rel + "#R2"])
    fix_progress.record(ctx, task)
    assert fix_progress.parked(ctx) == {rel + "#R2"}


@pytest.mark.parametrize("learner", ["one", "two"])
def test_repair_admission_skips_a_parked_topic_without_writing_queue(tmp_path, log, monkeypatch, learner):
    from datetime import datetime, timedelta
    from school_notes2.flows import repair
    from school_notes2.log import TZ
    from school_notes2.repair import queue
    from school_notes2.state.files import write_json
    from tests.flows.test_repair import context
    from tests.flows.test_repair_queue import page as add_page
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    add_page(ctx.notes_path, "b")
    safefs.write_json(ctx.notes_path, queue.PATH, queue.build(ctx.notes_path))
    original = safefs.read_bytes(ctx.notes_path, queue.PATH)
    Clock.at = datetime(2026, 10, 5, 10, tzinfo=TZ)
    monkeypatch.setattr(fix_progress, "datetime", Clock)
    write_json(fix_progress.path(ctx), {"repair:" + page: (Clock.at + timedelta(hours=1)).isoformat()})
    monkeypatch.setattr(repair, "start", lambda ctx, topic: topic)
    assert repair.next_task(ctx) == "wiki/m/b.md"
    assert safefs.read_bytes(ctx.notes_path, queue.PATH) == original
    Clock.at += timedelta(hours=2)
    assert repair.next_task(ctx) == page
