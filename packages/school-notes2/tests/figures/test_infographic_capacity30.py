"""New infographics are bounded while pending work keeps its reserved capacity."""

from types import SimpleNamespace
from decimal import Decimal

import pytest

from school_notes2.figures import infographics, pending
from school_notes2.images import plans
from school_notes2.state import phase, safefs
from tests.figures.test_capacity24 import settings


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_pending_reservations_then_two_new_commissions_survive_restart(repo, make_figure, learner):
    brief, _ = make_figure(fid="waiting", kind="banner")
    safefs.write_json(repo, ".school-notes/figures/waiting/figure.json", {"state": "failed", "reason": "Keret."})
    entry = pending.record(repo, brief, "old", [], attempted=False)
    config = settings(learner)
    task = phase.create(repo.parent / "state", learner, "notes", "cron", "writing")
    task.update(pending_figures=[entry])
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: config)
    figures = []
    for fid in ("a", "b", "c"):
        new, _ = make_figure(fid=fid, kind="infographic")
        figures.append({k: new[k] for k in ("id", "page", "kind")})
    assert infographics.generation_gate(ctx, task, "a") is None
    assert task.get("infographic_commissions", []) == ["a"]
    assert infographics.generation_gate(ctx, task, "waiting") is None
    config.daily_usd = Decimal("1")
    assert infographics.generation_gate(ctx, task, "a") is None
    task = phase.load(task.dir)
    assert infographics.generation_gate(ctx, task, "b") is None
    assert infographics.generation_gate(ctx, task, "c")["state"] == "disabled"
    result = {"status": "done", "figures": figures}
    assert any("at most 2" in i["message"] for i in infographics.check(repo, result, {"mode": "cron"}))


def test_free_candidate_retrieval_is_not_blocked_by_pending_reservations(repo, make_figure):
    make_figure(fid="overview", kind="infographic")
    config = settings("benedek")
    config.daily_usd = Decimal("0")
    config.ledger()["jobs"][plans.job_id("benedek", "overview")] = {"attempts": [{
        "state": "generated", "cost_usd": "0.05", "started_at": "2026-10-05T10:00:00+02:00"}]}
    task = phase.create(repo.parent / "state", "benedek", "notes", "cron", "writing")
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: config)
    assert infographics.generation_gate(ctx, task, "overview") is None
    assert infographics.generation_gate(ctx, task, "overview", "Javítás") is None


def test_figure_verdict_without_key_invalidates_without_keyerror(repo, make_figure):
    from school_notes2.figures import insert
    from school_notes2.reader import verdicts
    brief, candidate = make_figure()
    record = {"role": "figure-review", "file": brief["page"], "id": brief["id"],
              "commission": brief, "candidate": candidate, "verdict": "accept"}
    safefs.write_json(repo, insert.VERDICTS, [record])
    assert verdicts.invalidate(repo) == [record]
    assert safefs.read_json(repo, insert.VERDICTS) == []
