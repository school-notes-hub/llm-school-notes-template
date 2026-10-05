"""T18 (image flow) in the wrapper's scope."""

import json
import subprocess
import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from school_notes2.images import generate as gen
from school_notes2.images import pending
from school_notes2.images.budget import images_lock
from school_notes2.images.plans import PlanError
from school_notes2.images.settings import budapest_today

from image_fakes import KEY, prepare_candidate, independent_accept, write_shim

PAGE = "wiki/gazdasag/termeles.md"


def run(settings, log, plan_id="termeles-banner", **kw):
    return gen.generate(settings, plan_id, log=log, sleep=lambda s: None, **kw)


def test_generate_gives_image_and_preview_and_keeps_marker(make_settings, fake_api, log):
    s = make_settings()
    result = run(s, log)
    assert result["state"] == "generated" and result["attempts_left"] == 2
    assert (s.worktree / result["image"]).is_file() and result["preview"].endswith("publication.webp")
    assert "<!-- image: termeles-banner -->" in (s.worktree / PAGE).read_text()
    assert (s.plans_dir / "termeles-banner.json").is_file()
    job = json.loads((s.plans_dir / "termeles-banner.job.json").read_text())
    assert job["request_id"].startswith("school-year-") and job["learner"] == "benedek"
    assert [src["path"] for src in job["sources"]] == [".school-notes/images/termeles-banner.json",
                                                       "sources/gazdasag/p0001.jpg"]


def test_key_only_in_child_environment(make_settings, fake_api, log, monkeypatch):
    seen = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: seen.append(argv) or real(argv, **kw))
    run(make_settings(), log)
    assert fake_api.requests[0]["auth"] == f"Bearer {KEY}"
    assert all(KEY not in " ".join(argv) for argv in seen)


def test_independent_accept_inserts_exact_preview_and_records_reviewer(make_settings, fake_api, log):
    s = make_settings()
    generated = run(s, log)
    brief, candidate = prepare_candidate(s)
    assert (s.worktree / candidate["asset"]).read_bytes() == (s.worktree / generated["preview"]).read_bytes()
    written = independent_accept(s)
    assert PAGE in written and candidate["asset"] in written
    text = (s.worktree / PAGE).read_text()
    assert "<!-- image: termeles-banner -->" not in text
    assert "generated figure-termeles-banner" in text
    record = json.loads((s.worktree / "docs/evidence/media/termeles-banner/figure.json").read_text())
    assert record["verifier"] == "independent/high"
    assert independent_accept(s) == written
    assert (s.worktree / PAGE).read_text() == text


def test_repair_keeps_marker_and_uses_an_attempt(make_settings, fake_api, log):
    s = make_settings()
    run(s, log)
    assert "<!-- image: termeles-banner -->" in (s.worktree / PAGE).read_text()
    assert run(s, log)["number"] == 1  # rereading does not spend
    second = run(s, log, repair_note="A cím legyen nagyobb.")
    assert second["state"] == "generated" and second["number"] == 2
    assert "A cím legyen nagyobb." in fake_api.requests[-1]["body"]["prompt"]
    assert run(s, log, repair_note="x" * 2001)["state"] == "error"


@pytest.mark.parametrize("action,retried", [(429, True), (503, False), (400, False)])
def test_provider_errors_cost_nothing_and_only_429_retries(make_settings, fake_api, log, action, retried):
    s = make_settings()
    fake_api.actions = [action]
    result = run(s, log)
    if retried:
        assert result["state"] == "generated" and fake_api.calls == 2
    else:
        assert result == {**result, "state": "failed", "cost_usd": "0"} and fake_api.calls == 1
        assert run(s, log)["state"] == "generated"  # no stop, attempt not counted
        assert run(s, log)["attempts_left"] == 2


def test_unsent_request_is_free_and_retried(make_settings, fake_api, log, tmp_path):
    folder = tmp_path / "closed"
    folder.mkdir()
    closed = "http://127.0.0.1:9/api/v1/images"  # discard port: connection refused
    s = make_settings(script=write_shim(folder, closed))
    result = run(s, log)
    assert result["state"] == "failed" and result["failure"] == "not-sent"
    entry = s.ledger()["jobs"]["benedek-termeles-banner"]
    assert [a["state"] for a in entry["attempts"]] == ["failed"] * 3
    assert all(a["cost_usd"] == "0" for a in entry["attempts"])


def test_unknown_outcome_stops_both_learners_until_settled(make_settings, fake_api, log):
    benedek, barna = make_settings("benedek"), make_settings("barna")
    fake_api.actions = ["drop"]
    assert run(benedek, log)["state"] == "unknown"
    assert run(barna, log)["state"] == "waiting-unknown"
    assert pending.scan(barna)["pending"] == [] and pending.scan(barna)["waiting_unknown"]
    assert fake_api.calls == 1
    assert gen.settle_unknown(benedek, log=log) == []  # younger than a day
    settled = gen.settle_unknown(benedek, log=log, max_age_hours=0)
    assert settled[0]["state"] == "lost" and settled[0]["cost_usd"] == "0.05"
    assert run(barna, log)["state"] == "generated"
    assert run(benedek, log)["number"] == 2  # the lost attempt counts


def test_monthly_budget_ignores_daily_limit(make_settings, fake_api, log):
    s = make_settings(daily_usd=Decimal("0"), monthly_usd=Decimal("0.08"))
    other = make_settings("barna", daily_usd=Decimal("0"), monthly_usd=Decimal("0.08"))
    assert run(s, log)["state"] == "generated"            # 0.04 spent today
    assert run(other, log)["state"] == "budget-exhausted"  # 0.04 + 0.05 reservation > 0.08
    tomorrow = (budapest_today().replace(day=1) + timedelta(days=32)).replace(day=1)
    s_next_day = make_settings(daily_usd=Decimal("0"), monthly_usd=Decimal("0.08"), today=lambda: tomorrow)
    assert pending.scan(s_next_day)["budget_left"]
    assert pending.scan(other)["pending"] == [] and not pending.scan(other)["budget_left"]
    assert fake_api.calls == 1


def test_second_learner_waits_for_the_lock(make_settings, fake_api, log):
    s = make_settings()
    released = threading.Event()

    def hold():
        with images_lock(s.lock_path, 5):
            time.sleep(1.5)
        released.set()

    threading.Thread(target=hold).start()
    time.sleep(0.2)
    assert run(make_settings("barna"), log)["state"] == "generated"
    assert released.is_set()


def test_exhausted_image_is_not_pending_and_never_called(make_settings, fake_api, log):
    s = make_settings()
    for n in range(3):
        run(s, log, repair_note="javítás" if n else None)
    assert fake_api.calls == 3
    assert pending.scan(s)["exhausted"] == []
    assert pending.scan(s)["pending"] == [{"plan_id": "termeles-banner", "page": PAGE}]
    assert run(s, log)["number"] == 3  # Free retrieval while the last image awaits judgement.
    from school_notes2.figures import context
    from school_notes2.images import judgement
    brief, candidate = prepare_candidate(s)
    judgement.record(s, [brief], {"review": {"figures": [{"id": brief["id"], "verdict": "reject",
        "key": context.verdict_key(s.worktree, brief, candidate)}]}})
    scan = pending.scan(s)
    assert scan["exhausted"] == [{"plan_id": "termeles-banner", "page": PAGE}]
    assert run(s, log, repair_note="még egyszer")["state"] == "exhausted"
    assert fake_api.calls == 3


def test_pending_needs_marker_and_plan(make_settings, fake_api, log):
    s = make_settings()
    assert pending.scan(s)["pending"] == [{"plan_id": "termeles-banner", "page": PAGE}]
    (s.worktree / ".school-notes/images/termeles-banner.json").unlink()
    assert pending.scan(s)["missing_plan"] and not pending.scan(s)["pending"]


def test_kept_plan_is_restored_in_a_later_run(make_settings, fake_api, log):
    s = make_settings()
    run(s, log)
    (s.worktree / ".school-notes/images/termeles-banner.json").unlink()  # fetch wipes .school-notes
    from school_notes2.images import plans
    assert plans.restore(s, ["termeles-banner"]) == ["termeles-banner"]
    prepare_candidate(s)
    assert PAGE in independent_accept(s)


def test_invalid_input_is_refused(make_settings, fake_api, log):
    s = make_settings()
    with pytest.raises(PlanError):
        run(s, log, plan_id="../x")
    run(s, log)
    assert run(s, log, repair_note="x" * 2001)["state"] == "error"
    assert fake_api.calls == 1


def test_school_year_ledger_key():
    from school_notes2.images.settings import school_year
    assert school_year(date(2026, 9, 1)) == "school-year-2026-2027"
    assert school_year(date(2027, 6, 30)) == "school-year-2026-2027"


def test_refusal_before_any_request_is_not_retried(make_settings, fake_api, log):
    s = make_settings(max_total_usd=Decimal("0.01"))      # below one reservation: refused
    slept = []
    result = gen.generate(s, "termeles-banner", log=log, sleep=slept.append)
    assert result["state"] == "error" and slept == [] and fake_api.requests == []


def test_monthly_cap_stops_generation_before_the_daily_budget():
    from datetime import date
    from decimal import Decimal
    from school_notes2.images.budget import budget_left
    ledger = {"jobs": {"j": {"id": "j", "learner": "b", "attempts": [
        {"number": n, "state": "done", "cost_usd": "0.9", "started_at": f"2026-10-{n:02d}T10:00:00+02:00"}
        for n in range(1, 13)]}}}
    assert budget_left(ledger, date(2026, 10, 20), Decimal("1"), Decimal("0.05"))          # no cap
    assert not budget_left(ledger, date(2026, 10, 20), Decimal("1"), Decimal("0.05"), Decimal("10"))
    assert budget_left(ledger, date(2026, 11, 1), Decimal("1"), Decimal("0.05"), Decimal("10"))
