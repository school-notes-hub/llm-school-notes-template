"""Assigned decisions are required; an infographic itself is not mandatory."""

import pytest
from types import SimpleNamespace

from school_notes2.figures import infographics, pending
from school_notes2.flows import fetch, review_phases, writer
from school_notes2.schemas import validate
from school_notes2.state import phase, safefs
from school_notes2.wiki import markers
from .test_notice_regressions import legacy_items


def assignment(repo, page):
    legacy_items(repo, page, ["A test lefelé gyorsul."])
    return {"mode": "fix", "infographic_pages": [page], "open_review_items": [{"file": "docs/review/legacy.md", "item_id": "R1"}]}


def test_decision_scope_validation_and_fetch(setup):
    ctx, task, page = setup
    supplied = assignment(ctx.notes_path, page)
    task.update(mode="fix", open_review_items=supplied["open_review_items"])
    result = {"status": "done"}
    assert not infographics.check(ctx.notes_path, {"status": "question"}, supplied)
    assert fetch.fetch_json(task, 1, grade=9, repo=ctx.notes_path)["infographic_pages"] == [page]
    assert "missing decision" in infographics.check(ctx.notes_path, result, supplied)[0]["message"]
    result["infographic_decisions"] = [{"page": page, "reason": "Az egyetlen összefüggés szövegben áttekinthető."}]
    validate("result", result)
    assert not infographics.check(ctx.notes_path, result, supplied)
    infographics.record(ctx, task, result)
    assert fetch.fetch_json(task, 1, grade=9, repo=ctx.notes_path)["infographic_pages"] == []
    assert not infographics.check(ctx.notes_path, {"status": "done"}, supplied)
    assert infographics.assigned(ctx.notes_path, {"mode": "cron", "packages": []}) == []
    assert infographics.assigned(ctx.notes_path, {"mode": "repair", "repair_targets": [
        {"page": page, "related": []}]}) == [page]


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_decision_write_resumes_and_content_changes_invalidate(setup, monkeypatch, boundary):
    ctx, task, page = setup
    supplied = assignment(ctx.notes_path, page)
    decision = {"infographic_decisions": [{"page": page, "reason": "Nem segít új áttekintés."}]}
    write, fired = safefs.write_text, []
    def crash(repo, path, text, **kwargs):
        if path == infographics.PATH and not fired:
            fired.append(path)
            if boundary == "after":
                write(repo, path, text, **kwargs)
            raise RuntimeError("crash")
        return write(repo, path, text, **kwargs)
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(RuntimeError, match="crash"):
        infographics.record(ctx, task, decision)
    task = phase.load(task.dir)
    infographics.record(ctx, task, decision)
    before = safefs.read_bytes(ctx.notes_path, infographics.PATH)
    infographics.record(ctx, task, decision)
    assert safefs.read_bytes(ctx.notes_path, infographics.PATH) == before
    text = safefs.read_text(ctx.notes_path, page)
    safefs.write_text(ctx.notes_path, page, text + "\n" + markers.wrap("pending", "⏳ Próba\n") + "\n<!-- image: new -->\n")
    assert infographics.needed(ctx.notes_path, [page]) == []
    safefs.write_text(ctx.notes_path, page, text + "\nA gyorsulás mértékegysége m/s².\n")
    assert infographics.needed(ctx.notes_path, [page]) == [page]
    assert infographics.check(ctx.notes_path, {}, supplied)


def test_required_infographic_uses_generated_commission_and_pending_without_attempt(setup):
    ctx, task, page = setup
    repo = ctx.notes_path
    supplied = assignment(repo, page)
    brief = {"id": "overview", "page": page, "kind": "infographic", "anchor": "Téma",
             "purpose": "Áttekintés", "must_show": [], "avoid_misreading": "Egyértelmű irányok.",
             "taught_conventions": [], "text_complete_without_figure": True}
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "\n<!-- image: overview -->\n")
    safefs.write_json(repo, ".school-notes/figures/overview.json", brief)
    safefs.write_json(repo, ".school-notes/figures/overview/figure.json", {"state": "failed", "reason": "Elfogyott a képkeret."})
    result = {"status": "done", "infographic_decisions": [{"page": page, "figure_id": "overview"}],
              "figures": [{k: brief[k] for k in ("id", "page", "kind")}]}
    validate("result", result)
    assert not infographics.check(repo, result, supplied)
    assert infographics.check(repo, {**result, "figures": []}, supplied)
    safefs.write_json(repo, ".school-notes/figures/overview/figure.json", {"state": "no-figure", "reason": "Elmaradt."})
    assert "cannot be no-figure" in infographics.check(repo, result, supplied)[0]["message"]
    safefs.write_json(repo, ".school-notes/figures/overview/figure.json", {"state": "failed", "reason": "Elfogyott a képkeret."})
    infographics.record(ctx, task, result)
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": False}])
    ctx.image_settings = lambda: SimpleNamespace(learner="tester", max_attempts=3, ledger=lambda: {"jobs": {}})
    review_phases.finalize(ctx, task)
    entry = pending.load(repo)[0]
    assert entry["runs"] == 0 and entry["run_ids"] == []
    assert "⏳ Ehhez a részhez ábra készül." in safefs.read_text(repo, page)
    assert infographics.needed(repo, [page]) == []


def test_schema_rejects_ambiguous_empty_decision_and_merge_is_sorted():
    for decision in ({"page": "wiki/m/a.md"}, {"page": "wiki/m/a.md", "reason": " "},
                     {"page": "wiki/m/a.md", "reason": "Nem.", "figure_id": "x"}):
        with pytest.raises(ValueError):
            validate("result", {"status": "done", "infographic_decisions": [decision]})
    results = [{"status": "done", "infographic_decisions": [{"page": p, "reason": "Nem kell."}]}
               for p in ("wiki/m/b.md", "wiki/m/a.md")]
    assert writer.merge(results) == writer.merge(list(reversed(results)))


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("exhausted", ["daily", "monthly"])
def test_five_daily_ten_monthly_budget_blocks_without_an_attempt(tmp_path, learner, exhausted):
    from datetime import date
    from decimal import Decimal
    from school_notes2.images import generate
    from school_notes2.images.settings import ImageSettings
    from school_notes2.state.files import write_json
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = ImageSettings(learner, repo, tmp_path / "unused.py", tmp_path / "state",
        tmp_path / "plans", tmp_path / "lock", tmp_path / "key", Decimal("10"), Decimal("5"),
        daily_usd=Decimal("5"), monthly_usd=Decimal("10"), today=lambda: date(2026, 10, 5))
    ledger = {"jobs": {"previous": {"learner": learner, "attempts": [{"number": 1, "state": "accepted",
        "cost_usd": "5" if exhausted == "daily" else "10",
        "started_at": "2026-10-05T10:00:00+02:00" if exhausted == "daily" else "2026-10-04T10:00:00+02:00"}]}}}
    path = settings.state_dir / "ledger.json"
    write_json(path, ledger)
    before = path.read_bytes()
    assert generate._blocked(settings, f"{learner}-overview")["state"] == "budget-exhausted"
    assert path.read_bytes() == before
