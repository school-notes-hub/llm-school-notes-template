"""Lost paid attempts and bounded, crash-safe free review assignments."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from school_notes2.figures import migration_gate, pending, rechecks, rejected
from school_notes2.flows import correction, correction_figures, review_phases, writer
from school_notes2.images import pending as image_pending
from school_notes2.notify import Mailer
from school_notes2.state import phase, safefs
from tests.figures.test_capacity24 import settings
from tests.figures.test_gate25 import legacy
from tests.conftest import assert_suppressed


def context(repo, log, monkeypatch, learner, last):
    config = settings(learner, ["rejected", "rejected", last])
    config.worktree = repo
    cfg = SimpleNamespace(state_dir=repo.parent / "state")
    sent = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: sent.append(message) or True)
    ctx = SimpleNamespace(name=learner, notes_path=repo, log=log, cfg=cfg,
        student=SimpleNamespace(grade=9), image_settings=lambda: config,
        mailer=Mailer(repo / "unused", "test@example.test", cfg.state_dir / "notify.json", log))
    return ctx, config, sent


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("paid_disabled", [False, True])
def test_lost_last_attempt_escalates_once_without_taking_capacity(repo, make_figure, log, monkeypatch, learner, paid_disabled):
    brief, _ = make_figure(kind="banner")
    pending.record(repo, brief, "old", [], attempted=True)
    other, _ = make_figure(fid="next", kind="banner")
    pending.record(repo, other, "old", [], attempted=False)
    ctx, _, sent = context(repo, log, monkeypatch, learner, "lost")
    for _ in range(2):
        entries = pending.load(repo)
        actual = correction_figures.assignable(ctx, entries, paid_disabled=paid_disabled)
        assert [e["commission"]["id"] for e in actual] == ["next"]
        correction_figures.persist_owners(ctx, entries)
    stored = pending.load(repo)[0]
    assert stored["owner_required"] and stored["run_ids"] == ["old"]
    assert [e["commission"]["id"] for e in pending.for_subjects(repo, {"physics"})] == ["next"]
    assert not sent
    assert_suppressed(log)


def inputs(monkeypatch, entry):
    monkeypatch.setattr(writer.fetch_flow, "fetch_json", lambda *a, **kw: {"pending_figures": [entry]})
    monkeypatch.setattr(writer, "write_changes", lambda *a: None)
    monkeypatch.setattr(writer.call_scope, "write_check", lambda *a: None)


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("crash_at", ["receipt", "fetch"])
def test_free_rechecks_stop_after_two_assignments_and_resume_once(repo, make_figure, log, monkeypatch, learner, crash_at):
    brief, _ = make_figure(kind="banner")
    entry = pending.record(repo, brief, "old", [], attempted=True)
    ctx, config, sent = context(repo, log, monkeypatch, learner, "generated")
    config.daily_usd = Decimal(0)
    inputs(monkeypatch, entry)
    first = phase.create(repo.parent, learner, "notes", "cron", "prepared")
    module, name = (rechecks, "write_json") if crash_at == "receipt" else (safefs, "write_json")
    original = getattr(module, name)
    def crash(*args):
        original(*args)
        if crash_at == "receipt" or args[1] == ".school-notes/fetch.json":
            raise KeyboardInterrupt()
    monkeypatch.setattr(module, name, crash)
    with pytest.raises(KeyboardInterrupt):
        writer.write_inputs(ctx, first, 1)
    before = rechecks.path(ctx).read_bytes()
    monkeypatch.setattr(module, name, original)
    writer.write_inputs(ctx, phase.load(first.dir), 1)
    writer.write_inputs(ctx, phase.load(first.dir), 2)  # another range of the same assignment
    assert rechecks.path(ctx).read_bytes() == before
    assert correction_figures.assignable(ctx, [entry], paid_disabled=True) == [entry]
    # P4 has a separate child run ID; its receipt survives a worktree rollback.
    second = phase.Task(first.dir / "child", {**first.data, "run_id": first.run_id + "-fix-a1"})
    snapshot = first.dir / "snapshot"
    correction.snapshot(repo, snapshot)
    writer.write_inputs(ctx, second, 1)
    writer.write_inputs(ctx, second, 1)
    correction.restore(repo, snapshot)
    assert json.loads(rechecks.path(ctx).read_text()) == {brief["id"]: sorted([first.run_id, second.run_id])}
    third = phase.Task(first.dir / "third", {**first.data, "run_id": first.run_id + "-third"})
    with pytest.raises(ValueError, match="assignments exhausted"):
        writer.write_inputs(ctx, third, 1)
    first.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": False}])
    monkeypatch.setattr(review_phases.steps, "generate_all", lambda *a: None)
    monkeypatch.setattr(review_phases.steps, "record_tool_files", lambda *a: None)
    monkeypatch.setattr(review_phases.notices, "refresh", lambda *a, **kw: [])
    for _ in range(2):
        review_phases.finalize(ctx, phase.load(first.dir))
        assert correction_figures.assignable(ctx, pending.load(repo)) == []
    stored = pending.load(repo)[0]
    assert stored["owner_required"] and stored["run_ids"] == ["old"]
    assert not sent
    assert_suppressed(log)
    assert not image_pending.scan(config)["pending"]


@pytest.mark.parametrize("last", ["failed", "lost"])
def test_no_free_receipt_without_a_reviewable_candidate(repo, make_figure, log, monkeypatch, last):
    brief, _ = make_figure(kind="banner")
    entry = pending.record(repo, brief, "old", [], attempted=False)
    ctx, config, _ = context(repo, log, monkeypatch, "benedek", last)
    config.daily_usd = Decimal(0)
    inputs(monkeypatch, entry)
    task = phase.create(repo.parent, ctx.name, "notes", "cron", "prepared")
    writer.write_inputs(ctx, task, 1)
    assert not rechecks.path(ctx).exists()
    assert pending.load(repo)[0]["runs"] == 0


def test_gate_logs_new_runtime_and_nightly_commissions_without_mutation(repo, make_figure, log, monkeypatch):
    old, _ = make_figure()
    before = legacy(repo, old)
    brief, _ = make_figure(fid="new")
    ctx = SimpleNamespace(notes_path=repo, log=log)
    task = phase.create(repo.parent, "one", "notes", "cron", "review_ready")
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": False}])
    monkeypatch.setattr(review_phases.steps, "generate_all", lambda *a: None)
    monkeypatch.setattr(review_phases.steps, "record_tool_files", lambda *a: None)
    monkeypatch.setattr(review_phases.notices, "refresh", lambda *a, **kw: [])
    review_phases.finalize(ctx, task)
    assert rejected.apply(repo, [{"commission": {"id": "retry-z"}}, {"commission": {"id": "retry-a"}}], log=log) == []
    events = [json.loads(line) for line in log.main.read_text().splitlines()]
    assert [(e["action"], e["target"]) for e in events if e["action"] != "review.finalize"] == [
        ("figure.migration_dropped", fid) for fid in ("new", "retry-a", "retry-z")]
    assert safefs.read_bytes(repo, pending.PATH) == before
    assert not safefs.is_file(repo, migration_gate.MARK)
