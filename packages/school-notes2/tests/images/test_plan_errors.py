"""Invalid plans return actionable guidance without an executor or socket."""

import json
from decimal import Decimal

import pytest

from school_notes2.images import generate, plans
from school_notes2.images.settings import ImageSettings
from school_notes2.state.files import write_json
from image_fakes import PLAN, make_worktree


@pytest.mark.parametrize("student", ["benedek", "barna"])
@pytest.mark.parametrize("invalid", ["commission-fields", "invalid-json", "missing"])
def test_bad_plan_explains_repair_without_spending(tmp_path, log, monkeypatch, student, invalid):
    repo = make_worktree(tmp_path, student)
    settings = ImageSettings(student, repo, tmp_path / "unused.py", tmp_path / "state",
                             tmp_path / "plans", tmp_path / "lock", tmp_path / "key",
                             Decimal("10"), Decimal("5"))
    plan_id = "termeles-banner"
    path = repo / plans.target(plan_id)
    if invalid == "commission-fields":
        value = {k: v for k, v in PLAN.items() if k != "role"}
        value.update(id=plan_id, kind="banner", page="wiki/gazdasag/termeles.md", purpose="Orient")
        path.write_text(json.dumps(value))
    elif invalid == "invalid-json":
        path.write_text("{")
    else:
        path.unlink()
    ledger = settings.state_dir / "ledger.json"
    write_json(ledger, {"jobs": {}})
    before = ledger.read_bytes()
    monkeypatch.setattr(generate, "call", lambda *a, **kw: pytest.fail("executor called"))
    monkeypatch.setattr(generate, "ensure_ledger", lambda *a: pytest.fail("ledger changed"))
    result = generate.generate(settings, plan_id, log=log)
    assert result["state"] == "error"
    message = result["message"]
    assert plans.target(plan_id) in message
    assert f".school-notes/figures/{plan_id}.json" in message
    assert "id, kind, page, purpose" in message and "nem a képtervbe" in message
    assert "hívd újra az image_generate-et" in message
    if invalid == "commission-fields":
        assert "'role' is a required property" in message
        assert "Additional properties are not allowed" in message
    assert ledger.read_bytes() == before
    assert not plans.job_path(settings, plan_id).exists()
    write_json(path, PLAN)
    assert generate.generate(settings, plan_id, log=log, paid_disabled=True)["state"] == "disabled"
    assert ledger.read_bytes() == before
