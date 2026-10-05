"""Migration admission freezes legacy bytes while unrelated work continues."""

from types import SimpleNamespace

import pytest

from school_notes2.figures import migrate_pending, migration_gate, pending, rejected
from school_notes2.flows import correction_figures, fix, review_phases
from school_notes2.notify import Mailer
from school_notes2.reader import report
from school_notes2.review import night_figures, files
from school_notes2.state import phase, safefs
from tests.figures.test_capacity24 import settings
from tests.flows.test_repair import context as fix_context


def legacy(repo, brief):
    pending.record(repo, brief, "old-1", [], attempted=True)
    pending.record(repo, brief, "old-2", [], attempted=True)
    safefs.unlink(repo, migration_gate.MARK)
    return safefs.read_bytes(repo, pending.PATH)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_fix_freezes_legacy_then_migration_unlocks(tmp_path, log, monkeypatch, learner):
    ctx, page, _ = fix_context(tmp_path, log, monkeypatch)
    ctx.name = learner
    ctx.cfg.state_dir = tmp_path / "state"
    ctx.log = log
    sent = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: sent.append(message) or True)
    ctx.mailer = Mailer(tmp_path / "unused", "test@example.test", ctx.cfg.state_dir / "notify.json", log)
    brief = {"id": "forces", "page": page, "kind": "banner", "anchor": "Header", "purpose": "Topic",
        "must_show": [], "avoid_misreading": "Topic", "taught_conventions": [], "text_complete_without_figure": True}
    before = legacy(ctx.notes_path, brief)
    ctx.image_settings = lambda: settings(learner, ["rejected"] * 3)
    wt = ctx.worktree("notes")
    original = wt.run
    wt.run = lambda *a, **kw: None if a[0] == "switch" else original(*a, **kw)
    ctx.bare = lambda: wt
    ctx.cfg.limits = SimpleNamespace(fix_runs_per_day=6, max_agents=3, review_closures_per_run=30)
    ctx.cfg.timeouts = SimpleNamespace(fetch_s=1)
    monkeypatch.setattr(fix.repos, "fetch", lambda *a: None)
    files.write_review(ctx.notes_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R1", "file": page, "problem": "Text problem", "relates_to": None}]}, "fake", "a", "b")
    for _ in range(2):
        task = fix.next_task(ctx)
        assert task is not None  # The fixture's unrelated text review still runs.
        assert not task.get("pending_figures") and not task.get("figure_owners")
        task.set_phase("done")
        assert safefs.read_bytes(ctx.notes_path, pending.PATH) == before
    assert len(sent) == 1 and "a függő ábrák migrációja még nem futott le" in sent[0].get_content()
    assert "figure.migration_required" in log.main.read_text()
    migrate_pending.migrate(ctx.notes_path, state_dir=ctx.cfg.state_dir / learner, repo=wt)
    task = fix.next_task(ctx)
    assert task.get("figure_owners")[0]["owner_required"]
    assert len(sent) == 2  # Distinct, now justified paid-exhaustion notice.


def test_all_mutators_and_restoration_preserve_legacy(repo, make_figure, log, monkeypatch):
    brief, _ = make_figure()
    before = legacy(repo, brief)
    ctx = SimpleNamespace(notes_path=repo, log=log)
    assert pending.for_subjects(repo, {"physics"}) == []
    assert pending.restore(repo, {brief["page"]}) == []
    pending.record(repo, brief, "new", [], attempted=True, owner_required=True)
    pending.clear(repo, brief["id"])
    assert correction_figures.persist_owners(ctx, [{"commission": brief, "owner_required": True}]) == []
    assert not correction_figures.mark_exhausted(ctx, {"commission": brief})
    assert rejected.apply(repo, [{"commission": brief}]) == []
    task = phase.create(repo.parent, "one", "notes", "cron", "review_ready")
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": True}])
    monkeypatch.setattr(review_phases.steps, "generate_all", lambda *a: None)
    monkeypatch.setattr(review_phases.steps, "record_tool_files", lambda *a: None)
    monkeypatch.setattr(review_phases.notices, "refresh", lambda *a: [])
    review_phases.finalize(ctx, task)
    assert safefs.read_bytes(repo, pending.PATH) == before
    assert not list((repo / "docs/review").glob("*.md")) if (repo / "docs/review").exists() else True


def test_nightly_and_reader_skip_pending_image_but_keep_text(repo, make_figure):
    brief, candidate = make_figure()
    asset = candidate["asset"]
    brief.update(replaces=asset, decision_reason={"code": "c", "text": "Review"})
    before = legacy(repo, brief)
    safefs.write_text(repo, brief["page"], f"# Topic\n\n<!-- figure: {brief['id']} -->\n![Image](../assets/physics/{asset.rsplit('/', 1)[-1]})\nText.\n")
    unit = {"topic": brief["page"], "pages": [brief["page"]]}
    assert night_figures.discover(repo, unit) == []
    findings = [{"file": brief["page"], "quote": f"<!-- figure: {brief['id']} -->", "problem": "Pending"},
                {"file": brief["page"], "quote": "Text.", "problem": "Text problem"}]
    kept, _, _ = report.prepare(repo, findings, [])
    assert [f["problem"] for f in kept] == ["Text problem"]
    assert safefs.read_bytes(repo, pending.PATH) == before


@pytest.mark.parametrize("flow", ["package", "repair", "nightly"])
def test_each_entry_point_notifies_and_keeps_unrelated_work(repo, make_figure, log, monkeypatch, flow):
    from school_notes2.flows import fetch, repair, night_topics
    from tests.flows.test_fetch_cards import context as fetch_context
    from tests.sources.test_cards import shared
    brief, _ = make_figure()
    before = legacy(repo, brief)
    shared(repo)
    sent = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: sent.append(message) or True)
    if flow == "package":
        ctx = fetch_context(repo, monkeypatch)
        ctx.log, ctx.name = log, "one"
        ctx.cfg.state_dir = repo.parent / "state"
        task = phase.create(repo.parent, "one", "notes", "cron", "moved")
        task.update(selected=[])
        monkeypatch.setattr(fetch.calls, "assignments", lambda *a, **k: [{"subject": "physics", "seqs": [],
            "packages": [], "open_review_items": [], "pending_images": []}])
        invoke = lambda: fetch.prepare(ctx, task, new_subject_index=fetch.new_subject)
    elif flow == "repair":
        # Its preparation normally gets a pinned worktree from start().
        ctx = SimpleNamespace(name="one", notes_path=repo, log=log, cfg=SimpleNamespace(state_dir=repo.parent / "state"))
        task = phase.create(repo.parent, "one", "notes", "cron", "moved")
        task.update(mode="repair", queue_only=True, repair_queue_absent=True, repair_queue={"items": [], "figures": []})
        ctx.worktree = lambda _: None
        monkeypatch.setattr(repair.workbranch, "start", lambda *a, **k: None)
        monkeypatch.setattr(repair.workbranch, "reset_workdir", lambda *a: None)
        from school_notes2.repair import failure
        monkeypatch.setattr(failure, "write_item", lambda *a: None)
        safefs.write_text(repo, ".git", "gitdir: unused\n")
        invoke = lambda: repair.prepare(ctx, task)
    else:
        ctx = SimpleNamespace(name="one", notes_path=repo, log=log, bare=lambda: None,
            worktree=lambda _: SimpleNamespace(work_tree=repo),
            cfg=SimpleNamespace(state_dir=repo.parent / "state", role=lambda _: (None, None)))
        task = phase.create(repo.parent, "one", "review", "cron", "prepared")
        task.update(units=[])
        invoke = lambda: night_topics.run(ctx, task)
    ctx.mailer = Mailer(repo.parent / "unused", "test@example.test", ctx.cfg.state_dir / "notify.json", log)
    invoke()
    assert task.phase in ("prepared", "reviewed")
    assert not task.get("pending_figures")
    assert safefs.read_bytes(repo, pending.PATH) == before
    assert len(sent) == 1


def test_first_current_queue_record_recovers_after_marker_write(repo, make_figure, monkeypatch):
    brief, _ = make_figure()
    original = safefs.write_json
    def crash(root, name, value):
        original(root, name, value)
        if name == migration_gate.MARK:
            raise KeyboardInterrupt()
    monkeypatch.setattr(safefs, "write_json", crash)
    with pytest.raises(KeyboardInterrupt):
        pending.record(repo, brief, "first", [], attempted=True)
    assert not migration_gate.blocked(repo)
    assert not safefs.is_file(repo, pending.PATH)
    monkeypatch.setattr(safefs, "write_json", original)
    pending.record(repo, brief, "first", [], attempted=True)
    assert pending.load(repo)[0]["run_ids"] == ["first"]
    assert safefs.read_json(repo, migration_gate.MARK) == {"pending_format": "attempted-runs"}
