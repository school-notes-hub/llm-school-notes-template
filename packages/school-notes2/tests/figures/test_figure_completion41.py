"""A saved 2.4.3 verdict keeps its original validation contract."""

import pytest

from school_notes2.figures import context, review
from school_notes2.state import safefs
from test_review import make_run, response, fake_render


@pytest.mark.parametrize("verdict", ["repair", "reject"])
def test_old_empty_defect_receipt_resumes_but_new_output_rejected(repo, make_figure, tmp_path, log, verdict):
    brief, candidate = make_figure()
    run = make_run(tmp_path)
    assigned = {"figures": [{"id": brief["id"], "key": context.verdict_key(repo, brief, candidate)}]}
    output = response(assigned, verdict)
    folder = run.task_dir / "figure-review/topic"
    folder.mkdir(parents=True)
    saved = {"status": "reviewed", "review": output, "failed": []}
    safefs.write_json(folder, "accepted.json", saved)
    for _ in range(2):
        assert review.run_batch(repo, [brief], "topic", run, render=fake_render, log=log,
            invoke=lambda *a, **kw: pytest.fail("replayed legacy call")) == saved
    with pytest.raises(ValueError, match="requires a hiba"):
        review.validate_output(output, assigned, repo, [brief])
    safefs.write_json(folder, "accepted.json", {**saved, "validation_version": 2})
    with pytest.raises(ValueError, match="requires a hiba"):
        review.run_batch(repo, [brief], "topic", run, render=fake_render, log=log)


@pytest.mark.parametrize("mode", ["interactive", "repair"])
def test_scoped_waiting_excludes_other_figures(repo, make_figure, tmp_path, mode):
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import correction_figures
    from school_notes2.state import phase
    brief, _ = make_figure()
    pending.record(repo, brief, "old", [], attempted=False)
    task = phase.create(tmp_path / "state", "one", "notes", "interactive" if mode == "interactive" else "cron", "inspecting")
    task.update(mode=mode, pending_figures=[], inspection_figures=[])
    ctx = SimpleNamespace(name="one", notes_path=repo, cfg=SimpleNamespace(state_dir=tmp_path / "state"))
    assert correction_figures.waiting(ctx, task) == []


@pytest.mark.parametrize("reason", ["budget", "unknown"])
@pytest.mark.parametrize("stage", ["inspecting", "rechecking"])
def test_image_wait_does_not_start_another_round(repo, make_figure, tmp_path, log, monkeypatch, reason, stage):
    from decimal import Decimal
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import correction, correction_figures, inspection, recheck, review_phases
    from school_notes2.images import plans
    from school_notes2.state import phase
    from tests.figures.test_capacity24 import settings
    brief, _ = make_figure(kind="banner")
    s = settings("one")
    s.monthly_usd = Decimal("0") if reason == "budget" else Decimal("10")
    if reason == "unknown":
        job = plans.job_id("one", brief["id"])
        s.ledger()["jobs"][job] = {"id": job, "learner": "one", "attempts": [
            {"number": 1, "state": "unknown", "started_at": "2026-10-05T10:00:00+02:00", "cost_usd": "0"}]}
    safefs.write_json(repo, f".school-notes/figures/{brief['id']}/figure.json", {"state": "failed", "reason": reason})
    entry = pending.record(repo, brief, "old", [], attempted=False)
    task = phase.create(tmp_path / "state", "one", "notes", "cron", stage)
    task.update(mode="fix", pending_figures=[entry], correction_round=1)
    ctx = SimpleNamespace(name="one", notes_path=repo, image_settings=lambda: s, log=log,
                          cfg=SimpleNamespace(state_dir=tmp_path / "state"))
    assert not correction_figures.waiting(ctx, task)
    monkeypatch.setattr(inspection, "inspect", lambda *a: None)
    monkeypatch.setattr(recheck, "run", lambda *a: None)
    monkeypatch.setattr(review_phases, "record_figures", lambda *a, **kw: None)
    monkeypatch.setattr(review_phases, "finalize", lambda *a: None)
    monkeypatch.setattr(correction, "run", lambda *a: pytest.fail("empty correction round"))
    review_phases.advance(ctx, task, lambda _: None)
    assert task.phase == "finishing"


def test_figure_attempt_ids_include_finish_attempt(repo, make_figure, tmp_path, log):
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import correction_round, review_phases
    from school_notes2.state import phase
    brief, _ = make_figure()
    ctx = SimpleNamespace(name="one", notes_path=repo, log=log)
    task = phase.create(tmp_path / "state", "one", "notes", "cron", "rechecking")
    task.update(correction_round=1, attempt=1, inspection_figures=[{
        "brief": brief, "candidate": {"state": "failed"}, "attempted": True}])
    for attempt in (1, 1, 2, 2):
        task.update(attempt=attempt)
        review_phases.record_figures(ctx, task, correction_round.identity(task))
        task = phase.load(task.dir)
    entry = pending.load(repo)[0]
    assert entry["runs"] == 2
    assert entry["run_ids"] == [task.run_id + "-fix-a1-r1", task.run_id + "-fix-a2-r1"]
