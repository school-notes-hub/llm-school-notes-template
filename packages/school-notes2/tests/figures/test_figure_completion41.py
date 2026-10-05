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


def test_figure_attempt_counts_once_per_run(repo, make_figure, tmp_path, log):
    """One pass per run: a pending figure's run counter grows once per run, never per round."""
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import review_phases
    from school_notes2.state import phase
    brief, _ = make_figure()
    ctx = SimpleNamespace(name="one", notes_path=repo, log=log)
    runs = []
    for _ in range(2):
        task = phase.create(tmp_path / "state", "one", "notes", "cron", "review_ready")
        task.update(attempt=1, inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": True}])
        for _ in range(2):  # A replayed finalize does not count again.
            review_phases.record_figures(ctx, phase.load(task.dir))
        runs.append(task.run_id)
    entry = pending.load(repo)[0]
    assert entry["runs"] == 2 and entry["run_ids"] == sorted(runs)


def test_figure_brake_after_three_runs_is_a_notice_not_an_item(repo, make_figure, tmp_path, log, monkeypatch):
    """A3: the pending figure brake tells the owner by status and mail; no review item."""
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import review_phases
    from school_notes2.review import relations
    from school_notes2.state import phase
    brief, _ = make_figure()
    for run_id in ("a", "b"):
        pending.record(repo, brief, run_id, [], attempted=True)
    sent = []
    monkeypatch.setattr("school_notes2.notify.pending.send", lambda ctx_, notice: sent.append(notice) or True)
    ctx = SimpleNamespace(name="one", notes_path=repo, log=log, mailer=SimpleNamespace())
    task = phase.create(tmp_path / "state", "one", "notes", "cron", "review_ready")
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "failed"}, "attempted": True}])
    review_phases.record_figures(ctx, task)
    assert pending.load(repo)[0]["owner_required"]
    assert [n.kind for n in sent] == [f"figure_owner:{brief['id']}"]
    assert not relations.inventory(repo)["items"]


@pytest.mark.parametrize("receipt,counted", [
    ({"status": "pending", "reason": "figure reviewer timed out"}, False),
    ({}, False),
    ({"status": "reviewed", "model": "m", "review": {"figures": [{"id": "forces", "verdict": "reject",
      "key": "k", "defects": [], "text_mismatch": []}], "owner_notes": []}}, True)])
def test_an_unjudged_drawn_figure_is_no_try(repo, make_figure, tmp_path, log, receipt, counted):
    """Fix-49/4 (REJT-17): without the figure reviewer's verdict a run is no try; three such
    runs never make a drawn figure an owner matter."""
    from types import SimpleNamespace
    from school_notes2.figures import pending
    from school_notes2.flows import review_phases
    from school_notes2.state import phase
    brief, candidate = make_figure()
    ctx = SimpleNamespace(name="one", notes_path=repo, log=log)
    for _ in range(3):
        task = phase.create(tmp_path / "state", "one", "notes", "cron", "review_ready")
        task.update(attempt=1, inspection_receipts={brief["id"]: receipt},
                    inspection_figures=[{"brief": brief, "candidate": candidate, "attempted": True}])
        review_phases.record_figures(ctx, task)
    entry = pending.load(repo)[0]
    assert entry["runs"] == (3 if counted else 0) and entry["owner_required"] == counted
