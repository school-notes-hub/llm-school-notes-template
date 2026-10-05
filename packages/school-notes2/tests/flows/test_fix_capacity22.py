"""Capacity counts reservations and oversized highest-priority pages make progress."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from school_notes2.flows import correction, correction_figures
from school_notes2.review import files
from school_notes2.sources import calls
from school_notes2.state import phase, safefs


@pytest.mark.parametrize("monthly", ["10", "0.20"])
@pytest.mark.parametrize("learner", ["one", "two"])
def test_assignment_reserves_all_attempts_per_generated_figure(tmp_path, monthly, learner):
    page = "wiki/m/topic.md"
    safefs.write_text(tmp_path, page, "<!-- image: c -->\n")
    entries = [{"commission": {"id": fid, "page": page, "kind": kind}, "runs": 0}
               for fid, kind in [("a", "banner"), ("b", "infographic"), ("c", "figure"), ("d", "figure")]]
    ledger = {"jobs": {"spent": {"attempts": [{"state": "generated", "cost_usd": "0.05",
        "started_at": "2026-10-05T12:00:00+02:00"}]}}}
    settings = SimpleNamespace(today=lambda: date(2026, 10, 5), daily_usd=Decimal("0.37"),
        monthly_usd=Decimal(monthly), reservation_usd=Decimal("0.05"), max_attempts=3, learner=learner, ledger=lambda: ledger)
    ctx = SimpleNamespace(notes_path=tmp_path, image_settings=lambda: settings)
    selected = correction_figures.assignable(ctx, entries[::-1])
    assert [e["commission"]["id"] for e in selected] == (["a", "b", "d"] if monthly == "10" else ["a", "d"])
    task = phase.create(tmp_path / "state", learner, "notes", "cron", "moved")
    task.update(pending_figures=selected)
    assert phase.load(task.dir).get("pending_figures") == selected
    assert all(e["runs"] == 0 for e in entries)


@pytest.mark.parametrize("p4", [False, True])
def test_31_item_page_finishes_in_two_runs(tmp_path, p4):
    page = "wiki/m/a.md"
    path = files.write_review(tmp_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"id": f"R{n}", "file": page, "problem": "Hiba.", "relates_to": None}
        for n in range(1, 32)]}, "fake", "a", "b").relative_to(tmp_path).as_posix()
    ctx = SimpleNamespace(notes_path=tmp_path, cfg=SimpleNamespace(limits=SimpleNamespace(review_closures_per_run=30)))
    task = phase.create(tmp_path / "state", "learner", "notes", "cron", "correcting")
    task.update(inspection_report=path, inspection_units=[{"pages": [page]}], inspection_result={})
    for n, count in [(1, 30), (2, 1)]:
        selected = correction.assigned(ctx, phase.load(task.dir)) if p4 else calls.select_reviews(
            files.open_items(tmp_path, "cron"), 30, repo=tmp_path)
        assert len(selected) == count
        assert [i["item_id"] for i in selected] == ([f"R{k}" for k in range(1, 31)] if n == 1 else ["R31"])
        closures = [{"file": i["file"], "item_id": i["item_id"], "status": "fixed"} for i in selected]
        files.apply_closure(tmp_path, f"run-{n}", closures, selected)
    assert files.open_items(tmp_path, "cron") == []
