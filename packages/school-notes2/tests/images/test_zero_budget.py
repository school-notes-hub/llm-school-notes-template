"""No socket or paid executor is needed to verify the zero-budget gate."""

from datetime import date
from decimal import Decimal

import pytest

from school_notes2.images import generate, pending
from school_notes2.images.settings import ImageSettings
from school_notes2.state.files import write_json


@pytest.mark.parametrize("student", ["benedek", "barna"])
@pytest.mark.parametrize("attempts", [[], [{"number": 1, "state": "rejected", "cost_usd": "0.05",
                                          "started_at": "2026-10-03T10:00:00+02:00"}]])
def test_zero_budget_queues_nothing_and_preserves_attempts(tmp_path, student, attempts):
    repo = tmp_path / "repo"
    page = repo / "wiki/proba/tema.md"
    page.parent.mkdir(parents=True)
    page.write_text("<!-- image: tema-banner -->\n")
    settings = ImageSettings(student, repo, tmp_path / "unused.py", tmp_path / "state",
                             tmp_path / "plans", tmp_path / "lock", tmp_path / "key",
                             Decimal("10"), Decimal("5"), daily_usd=Decimal("0"), monthly_usd=Decimal("0"),
                             today=lambda: date(2026, 10, 4))
    write_json(settings.plans_dir / "tema-banner.json", {"id": "tema-banner"})
    ledger = {"request_id": settings.request_id, "jobs": {f"{student}-tema-banner": {
        "id": f"{student}-tema-banner", "learner": student, "attempts": attempts}}}
    path = settings.state_dir / "ledger.json"
    write_json(path, ledger)
    before = path.read_bytes()
    for _ in range(2):
        found = pending.scan(settings)
        assert found["pending"] == [] and found["budget_left"] is False
        assert found["missing_plan"] == []
    assert path.read_bytes() == before
    if not attempts:
        assert generate._blocked(settings, f"{student}-tema-banner")["state"] == "budget-exhausted"
