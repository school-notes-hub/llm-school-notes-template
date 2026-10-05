"""Hourly admission, whole-page batches and budget-filtered figure work."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from school_notes2.config import ConfigError, Limits
from school_notes2.flows import correction_figures, fix
from school_notes2.review import files
from school_notes2.sources import calls
from school_notes2.state import phase, safefs
from tests.flows.test_repair import context


@pytest.mark.parametrize("learner", ["one", "two"])
def test_more_than_six_runs_admitted_without_daily_limit(tmp_path, log, monkeypatch, learner):
    ctx, page, _ = context(tmp_path, log, monkeypatch)
    ctx.name = learner
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.worktree = lambda _: wt
    ctx.bare = lambda: wt
    ctx.cfg.limits = Limits()
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": page, "problem": "Hiba.", "relates_to": None}]}, "fake", "a", "b")
    for _ in range(6):
        task = fix.next_task(ctx)
        assert task is not None
        phase.load(task.dir).set_phase("done")
    assert fix.next_task(ctx) is not None


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "6"])
def test_fix_limit_positive_integer(value):
    with pytest.raises(ConfigError, match="fix_runs_per_day"):
        Limits(fix_runs_per_day=value)


def test_selection_groups_whole_pages_by_first_priority(tmp_path):
    files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": f"R{n}", "file": f"wiki/m/{'a' if n <= 12 else 'b'}.md", "problem": "Hiba."}
        for n in range(1, 25)]}, "fake", "a", "b")
    items = files.open_items(tmp_path, "cron")
    assert len(calls.select_reviews(items, 20, repo=tmp_path)) == 12
    assert len(calls.select_reviews(items, 30, repo=tmp_path)) == 24
    assert calls.select_reviews(items, 20, repo=tmp_path) == calls.select_reviews(items[::-1], 20, repo=tmp_path)


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("remaining", [False, True])
def test_budget_exhaustion_only_defers_generated_figures(tmp_path, learner, remaining):
    page = "wiki/m/topic.md"
    safefs.write_text(tmp_path, page, "<!-- image: banner -->\n<!-- figure: drawing -->\n")
    entries = [{"commission": {"id": fid, "page": page, "kind": kind}, "runs": 0}
               for fid, kind in [("banner", "banner"), ("drawing", "notebook-drawing")]]
    settings = SimpleNamespace(today=lambda: date(2026, 10, 4), daily_usd=Decimal("1") if remaining else Decimal("0"),
        reservation_usd=Decimal("0.05"), max_attempts=3, learner=learner, monthly_usd=Decimal("10"), ledger=lambda: {"jobs": {}})
    ctx = SimpleNamespace(notes_path=tmp_path, name=learner, image_settings=lambda: settings)
    actual = correction_figures.assignable(ctx, entries)
    assert [e["commission"]["id"] for e in actual] == ["banner", "drawing"]
    assert entries[0]["runs"] == 0


def test_oversized_first_page_gets_first_batch(tmp_path):
    files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": f"R{n}", "file": f"wiki/m/{'a' if n <= 31 else 'b'}.md", "problem": "Hiba."}
        for n in range(1, 33)]}, "fake", "a", "b")
    items = files.open_items(tmp_path, "cron")
    assert [i["item_id"] for i in calls.select_reviews(items, 30, repo=tmp_path)] == [f"R{n}" for n in range(1, 31)]


def test_asset_items_stay_with_their_embedding_page(tmp_path):
    safefs.write_text(tmp_path, "wiki/m/a.md", "# A\n\n![Ábra](../assets/a.svg)\n")
    files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": f"R{n}", "file": "wiki/assets/a.svg" if n == 31 else "wiki/m/a.md", "problem": "Hiba."}
        for n in range(1, 32)]}, "fake", "a", "b")
    assert len(calls.select_reviews(files.open_items(tmp_path, "cron"), 30, repo=tmp_path)) == 30


def test_fix_assigns_all_figures_even_when_paid_generation_must_wait(tmp_path):
    page = "wiki/m/topic.md"
    safefs.write_text(tmp_path, page, "<!-- image: banner -->\n")
    entries = [{"commission": {"id": "banner", "page": page, "kind": "banner"}, "runs": 0}]
    settings = SimpleNamespace(today=lambda: date(2026, 10, 5), daily_usd=Decimal("0"),
        reservation_usd=Decimal("0.05"), max_attempts=3, learner="one", monthly_usd=Decimal("10"), ledger=lambda: {"jobs": {}})
    ctx = SimpleNamespace(notes_path=tmp_path, name="one", image_settings=lambda: settings)
    assert correction_figures.assignable(ctx, entries) == entries
    settings.monthly_usd = Decimal("0")
    assert correction_figures.assignable(ctx, entries) == entries
    assert entries[0]["runs"] == 0
