"""Paid waits remain temporary; suggestions and monthly notices never disappear."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from school_notes2.figures import pending
from school_notes2.flows import correction_figures, fix_progress, image_notices, set_aside
from school_notes2.images import plans
from school_notes2.images.generate import attempts_used
from school_notes2.state import phase
from tests.conftest import recording_mailer
from tests.figures.test_capacity24 import settings


@pytest.mark.parametrize("reason", ["budget", "unknown"])
def test_image_only_wait_does_not_consume_attempt_or_set_progress_brake(repo, make_figure, reason):
    brief, _ = make_figure(kind="banner")
    s = settings("one")
    s.monthly_usd = Decimal("0") if reason == "budget" else Decimal("10")
    if reason == "unknown":
        s.ledger()["jobs"][plans.job_id("one", brief["id"])] = {"id": plans.job_id("one", brief["id"]), "learner": "one", "attempts": [
            {"number": 1, "state": "unknown", "started_at": "2099-10-05T10:00:00+02:00", "cost_usd": "0"}]}
    from school_notes2.state import safefs
    safefs.write_json(repo, f".school-notes/figures/{brief['id']}/figure.json", {"state": "failed", "reason": reason})
    entry = pending.record(repo, brief, "old", [], attempted=False)
    task = phase.create(repo.parent / "tasks", "one", "notes", "cron", "review_ready")
    task.update(mode="fix", pending_figures=[entry])
    ctx = SimpleNamespace(name="one", notes_path=repo, image_settings=lambda: s,
                          cfg=SimpleNamespace(state_dir=repo.parent / "state"))
    assert fix_progress.image_wait(ctx, [entry])
    assert not correction_figures.attempted(ctx, task, brief)
    fix_progress.record(ctx, task)
    assert not set_aside.path(ctx).exists()
    task.update(open_review_items=[{"file": "docs/review/old.md", "item_id": "R1"}])
    fix_progress.record(ctx, task)
    assert "docs/review/old.md#R1" in set_aside.blocked(ctx)
    set_aside.path(ctx).unlink()
    s.monthly_usd = Decimal("10")
    s.ledger()["jobs"].clear()
    assert not fix_progress.image_wait(ctx, [entry])
    assert fix_progress.available(ctx, [], [entry])[1] == [entry]
    assert attempts_used({"attempts": [{"state": "unknown"}]}) == 0


def test_shared_monthly_threshold_strictly_over_eighty_once(repo, log, monkeypatch):
    s = settings("one")
    s.monthly_usd = Decimal("10")
    clock = [date(2026, 10, 5)]
    s.today = lambda: clock[0]
    attempt = {"state": "generated", "cost_usd": "8", "started_at": "2026-10-05T10:00:00+02:00"}
    s.ledger()["jobs"]["one-x"] = {"attempts": [attempt]}
    delivered = []
    ctx = SimpleNamespace(name="one", cfg=SimpleNamespace(state_dir=repo.parent / "state"), log=log,
                          image_settings=lambda: s,
                          mailer=recording_mailer(repo.parent, log, monkeypatch, delivered))
    image_notices.threshold(ctx)
    assert not delivered
    attempt["cost_usd"] = "8.01"
    image_notices.threshold(ctx)
    ctx.name = "two"
    image_notices.threshold(ctx)
    assert len(delivered) == 1
    task = phase.create(repo.parent / "tasks", "two", "notes", "cron", "done")
    image_notices.summary(ctx, task)
    assert task.get("image_budget_note") == "képkeret: 8.01/10 USD"
    clock[0] = date(2026, 11, 1)
    attempt["started_at"] = "2026-11-01T10:00:00+01:00"
    image_notices.threshold(ctx)
    assert len(delivered) == 2


def test_figure_advice_is_preserved_in_owner_notes(repo, make_figure, log):
    from school_notes2.figures import review
    from tests.figures.test_review import make_run, fake_render, response
    from school_notes2.state import safefs
    brief, _ = make_figure()
    run = make_run(repo.parent)
    def invoke(run, **kw):
        value = response(safefs.read_json(run.mounts.in_dir, "assigned.json"))
        value["figures"][0]["defects"] = [{"severity": "javaslat", "location": "felirat",
            "observed": "Hosszú felirat.", "expected": "Rövidebb lehet."}]
        return SimpleNamespace(output=value)
    receipt = review.run_batch(repo, [brief], "topic", run, render=fake_render, log=log, invoke=invoke)
    assert receipt["review"]["figures"][0]["verdict"] == "accept"
    assert receipt["review"]["owner_notes"] == [brief["page"] + " (forces): Hosszú felirat. – Rövidebb lehet."]


def test_completion_uses_accepted_evidence_after_tool_state_cleanup(repo, make_figure):
    from school_notes2.figures import context
    from school_notes2.flows import work_pending
    from school_notes2.state import safefs
    brief, candidate = make_figure()
    evidence = {"commission": brief, "candidate": candidate,
                "verdict": {"verdict": "accept", "key": context.verdict_key(repo, brief, candidate)}}
    safefs.write_json(repo, f"docs/evidence/media/{brief['id']}/figure.json", evidence)
    (repo / f".school-notes/figures/{brief['id']}.json").unlink()
    (repo / f".school-notes/figures/{brief['id']}/figure.json").unlink()
    assert not work_pending.missing_images(repo)
    (repo / candidate["asset"]).unlink()
    assert brief["id"] in work_pending.missing_images(repo)
