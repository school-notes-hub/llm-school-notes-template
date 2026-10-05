"""Paid-attempt evidence and identical P3/P5 recheck routing survive interruption."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from school_notes2.figures import pending
from school_notes2.flows import correction, correction_figures, inspection, recheck
from school_notes2.reader import report
from school_notes2.review import files, relations, scope
from school_notes2.state import phase, safefs
from .test_review_fixes import figure


@pytest.mark.parametrize("kind", ["banner", "infographic", "figure"])
@pytest.mark.parametrize("paid", [False, True])
@pytest.mark.parametrize("p4", [False, True])
def test_paid_attempt_gate_survives_candidate_failure_and_restart(setup, monkeypatch, kind, paid, p4):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    brief["kind"] = kind
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f.json", brief)
    safefs.write_text(ctx.notes_path, page, safefs.read_text(ctx.notes_path, page).replace("<!-- figure: f -->", "<!-- image: f -->"))
    safefs.write_json(ctx.notes_path, ".school-notes/figures/f/figure.json", {"state": "failed", "reason": "budget-exhausted"})
    start = datetime.fromisoformat(task.data["created"])
    attempts = [{"started_at": (start - timedelta(days=1)).isoformat(), "state": "generated", "cost_usd": "0.05"}]
    if paid:
        attempts.append({"started_at": start.isoformat(), "state": "rejected", "cost_usd": "0.05", "reserved_usd": "0.05"})
    ledger = {"jobs": {"tester-f": {"attempts": attempts}, "other-f": {"attempts": [
        {"started_at": start.isoformat(), "state": "generated", "cost_usd": "0.05"}]}}}
    ctx.image_settings = lambda: SimpleNamespace(learner="tester", ledger=lambda: ledger)
    task.update(inspection_result={"figures": [{k: brief[k] for k in ("id", "kind", "page")}], "status": "done"})
    original = inspection.candidate_state
    fired = []
    def crash(*args):
        value = original(*args)
        if not fired:
            fired.append(1)
            raise KeyboardInterrupt()
        return value
    monkeypatch.setattr(inspection, "candidate_state", crash)
    if p4:
        task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed", "reason": "old"}, "attempted": False}],
                    correction_figures=[{"commission": brief}])
        monkeypatch.setattr(correction.generation_receipts, "refresh", lambda *a: None)
        def run(t):
            correction.apply(ctx, t, task.dir / "correction", {"status": "done", "result": {"status": "done"}})
    else:
        def run(t):
            inspection.prepare(ctx, t)
    with pytest.raises(KeyboardInterrupt):
        run(task)
    resumed = phase.load(task.dir)
    run(resumed)
    state = resumed.get("inspection_figures")[0]
    assert state["attempted"] is paid
    for _ in range(2):
        entry = pending.record(ctx.notes_path, brief, task.run_id, [], attempted=state["attempted"])
    assert entry["runs"] == int(paid)


def test_generated_candidate_counts_without_paid_call(setup):
    ctx, task, page = setup
    brief, _ = figure(ctx, task, page)
    brief["kind"] = "banner"
    assert correction_figures.attempted(ctx, task, brief)


@pytest.mark.parametrize("quote", ["Repeated.", "Absent."])
def test_targeted_ambiguous_quotes_remain_unlocated(setup, quote):
    ctx, _, page = setup
    text = "Repeated.\nRepeated.\nChanged.\n"
    safefs.write_text(ctx.notes_path, page, text)
    kept, notes = scope.partition([{"severity": "hiba", "file": page, "quote": quote, "problem": "Explain."}],
        lambda _: "Repeated.\nRepeated.\nOld.\n", lambda _: text, [page])
    assert len(kept) == 1 and not notes
    assert report.locate(ctx.notes_path, kept[0])["unlocated"]


@pytest.mark.parametrize("mode", ["fix", "cron"])
def test_recheck_not_ok_and_new_hit_stay_open_on_replay(setup, mode):
    ctx, task, page = setup
    task.update(mode=mode)
    path = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": page, "quote": "Old.", "problem": "Explain.", "chain": 0,
         "relates_to": None}]}, "fake", "a", "b").relative_to(ctx.notes_path).as_posix()
    files.apply_closure(ctx.notes_path, task.run_id, [{"file": path, "item_id": "R1", "status": "fixed"}], [])
    before = task.dir / "before"
    before.mkdir()
    safefs.write_text(before, page, "Old.\n")
    safefs.write_text(ctx.notes_path, page, "New.\n")
    task.update(inspection_report=path)
    saved = {"receipts": {}, "units": [{"status": "reviewed", "model": "fake", "before": str(before),
        "unit": {"pages": [page]}, "items": [], "hits": [{"id": "hit", "file": page, "line": 1}],
        "review": {"items": [{"severity": "hiba", "key": path + "#R1", "verdict": "not-ok", "answer": "Still wrong."}],
                   "hits": [{"severity": "hiba", "hit_id": "hit", "verdict": "hiba", "reason": "New issue.", "covered_by": None}],
                   "owner_notes": []}}]}
    recheck.apply(ctx, task, saved)
    recheck.apply(ctx, phase.load(task.dir), saved)
    known = relations.inventory(ctx.notes_path)["items"]
    assert len(known) == 2
    assert all(i["status"] == "open" and i["chain"] == 0 and i["origin"] == "recheck" for i in known.values())


def test_p4_budget_assignment_stays_pinned_after_writer_crash(setup, monkeypatch):
    ctx, task, page = setup
    brief, candidate = figure(ctx, task, page)
    task.update(inspection_figures=[{"brief": brief, "candidate": candidate}])
    waiting = [{"commission": brief, "runs": 0, "run_ids": [], "defects": [], "owner_required": False}]
    calls = []
    def assign(*a):
        calls.append(1)
        return waiting if len(calls) == 1 else []
    monkeypatch.setattr(correction_figures, "waiting", assign)
    monkeypatch.setattr(correction, "assigned", lambda *a: [])
    monkeypatch.setattr(correction.handlers, "build", lambda *a: None)
    def crash(*a):
        raise KeyboardInterrupt()
    monkeypatch.setattr(correction.writer, "run_ranges", crash)
    with pytest.raises(KeyboardInterrupt):
        correction.run(ctx, task)
    resumed = phase.load(task.dir)
    with pytest.raises(KeyboardInterrupt):
        correction.run(ctx, resumed)
    assert calls == [1]
    assert resumed.get("correction_figures") == waiting
