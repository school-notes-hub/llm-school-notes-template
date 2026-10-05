"""Paid exhaustion, per-subject reservations and content-first assignment."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from school_notes2.figures import pending
from school_notes2.flows import correction_figures, fetch, fix
from school_notes2.images import plans
from school_notes2.notify import Mailer
from school_notes2.state import phase, safefs
from tests.flows.test_fetch_cards import context as fetch_context
from tests.flows.test_repair import context as fix_context
from tests.sources.test_cards import shared
from tests.conftest import assert_suppressed


def settings(learner, attempts=()):
    ledger = {"jobs": {plans.job_id(learner, "forces"): {"id": "job", "learner": learner, "attempts": [
        {"state": state, "cost_usd": "0.01", "started_at": "2026-10-04T12:00:00+02:00"} for state in attempts]}}}
    return SimpleNamespace(learner=learner, ledger=lambda: ledger, max_attempts=3,
        today=lambda: date(2026, 10, 5), reservation_usd=Decimal("0.05"),
        daily_usd=Decimal("0.15"), monthly_usd=Decimal("10"))


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("paid_disabled", [False, True])
def test_exhausted_job_becomes_owner_once_without_a_run(repo, make_figure, log, monkeypatch, learner, paid_disabled):
    brief, _ = make_figure(kind="banner")
    pending.record(repo, brief, "old", [], attempted=True)
    cfg = SimpleNamespace(state_dir=repo.parent / "state")
    sent = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: sent.append(message) or True)
    ctx = SimpleNamespace(name=learner, notes_path=repo, cfg=cfg,
        image_settings=lambda: settings(learner, ["rejected"] * 3),
        mailer=Mailer(repo / "unused", "test@example.test", cfg.state_dir / "notify.json", log))
    for _ in range(2):
        entries = pending.load(repo)
        assert correction_figures.assignable(ctx, entries, paid_disabled=paid_disabled) == []
        assert entries[0]["owner_required"]
        correction_figures.persist_owners(ctx, entries)
    stored = pending.load(repo)[0]
    assert stored["runs"] == 1 and stored["run_ids"] == ["old"] and stored["owner_required"]
    assert pending.for_subjects(repo, {"physics"}) == []
    assert not sent
    assert_suppressed(log)


def test_unpaid_failed_calls_do_not_exhaust_job(repo, make_figure):
    brief, _ = make_figure(kind="banner")
    entry = pending.record(repo, brief, "old", [], attempted=False)
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: settings("one", ["failed"] * 3))
    assert correction_figures.assignable(ctx, [entry]) == [entry]
    assert not entry["owner_required"]


@pytest.mark.parametrize("capacity", ["0.15", "0.30"])
def test_new_content_precedes_replacements_regardless_of_id(repo, make_figure, capacity):
    entries = []
    for fid, changes in [("a-replacement", {"replaces": "wiki/assets/old.webp", "decision_reason": {"code": "c", "text": "Review"}}),
                         ("z-new", {})]:
        brief, _ = make_figure(fid=fid, kind="banner", **changes)
        entries.append(pending.record(repo, brief, "old", [], attempted=False))
    config = settings("one")
    config.daily_usd = Decimal(capacity)
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: config)
    actual = correction_figures.assignable(ctx, entries)
    expected = ["z-new", "a-replacement"]
    assert [e["commission"]["id"] for e in actual] == expected
    restored = pending.for_subjects(repo, {"physics"}, allowed=set(expected))
    assert [e["commission"]["id"] for e in restored] == expected


def test_fetch_reserves_only_its_assigned_subject(repo, make_figure, monkeypatch):
    shared(repo)
    for fid, subject in [("a-outside", "algebra"), ("z-inside", "physics")]:
        brief, _ = make_figure(fid=fid, page=f"wiki/{subject}/topic.md", kind="banner")
        pending.record(repo, brief, "old", [], attempted=False)
    ctx = fetch_context(repo, monkeypatch)
    ctx.image_settings = lambda: settings("one")
    monkeypatch.setattr(fetch.calls, "assignments", lambda *a, **k: [{"subject": "physics", "seqs": [], "packages": [],
        "open_review_items": [], "pending_images": []}])
    task = phase.create(repo.parent, "one", "notes", "cron", "moved")
    task.update(selected=[])
    fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    assert [e["commission"]["id"] for e in task.get("pending_figures")] == ["z-inside"]
    assert pending.load(repo)[0]["runs"] == 0


def test_owner_only_fix_resumes_without_writer_or_attempt(tmp_path, log, monkeypatch):
    ctx, page, _ = fix_context(tmp_path, log, monkeypatch)
    brief = {"id": "forces", "page": page, "kind": "banner", "anchor": "Header", "purpose": "Topic",
        "must_show": [], "avoid_misreading": "Topic", "taught_conventions": [], "text_complete_without_figure": True}
    pending.record(ctx.notes_path, brief, "old", [], attempted=False)
    ctx.image_settings = lambda: settings(ctx.name, ["rejected"] * 3)
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(fix_runs_per_day=6, max_agents=3, review_closures_per_run=30)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    task = fix.next_task(ctx)
    assert task.get("pending_figures") == [] and task.get("figure_owners")[0]["owner_required"]
    monkeypatch.setattr(task, "set_phase", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        fix.prepare(ctx, task)
    resumed = phase.load(task.dir)
    fix.prepare(ctx, resumed)
    assert resumed.get("skip_writer") and resumed.get("pending_figures") == []
    assert pending.PATH in resumed.get("tool_writes")
    assert pending.load(ctx.notes_path)[0]["owner_required"]
    assert pending.load(ctx.notes_path)[0]["runs"] == 0
    resumed.set_phase("done")
    assert fix.next_task(ctx) is None


@pytest.mark.parametrize("old_runs", [0, 2])
def test_finalization_marks_paid_exhaustion_with_one_notice(repo, make_figure, log, monkeypatch, old_runs):
    from school_notes2.flows import review_phases
    brief, _ = make_figure(kind="banner")
    for n in range(old_runs):
        pending.record(repo, brief, f"old-{n}", [], attempted=True)
    cfg = SimpleNamespace(state_dir=repo.parent / "state")
    sent = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: sent.append(message) or True)
    ctx = SimpleNamespace(name="one", notes_path=repo, cfg=cfg, log=log,
        image_settings=lambda: settings("one", ["rejected"] * 3),
        mailer=Mailer(repo / "unused", "test@example.test", cfg.state_dir / "notify.json", log))
    task = phase.create(repo.parent, "one", "notes", "cron", "review_ready")
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": True}])
    monkeypatch.setattr(review_phases.steps, "generate_all", lambda *a: None)
    monkeypatch.setattr(review_phases.steps, "record_tool_files", lambda *a: None)
    monkeypatch.setattr(review_phases.notices, "refresh", lambda *a, **kw: [])
    for _ in range(2):
        review_phases.finalize(ctx, phase.load(task.dir))
    stored = pending.load(repo)[0]
    assert stored["owner_required"] and stored["runs"] == old_runs + 1
    assert not sent
    assert_suppressed(log)
