"""Fix-50/3: a reopened figure's run counter grows by one per judged run, also when the
figure was assigned twice in that run (the 2.6.1 Benedek run); an unjudged run is no try."""

from types import SimpleNamespace

import pytest

from school_notes2.figures import pending
from school_notes2.flows import review_phases
from school_notes2.state import phase


@pytest.mark.parametrize("judged,runs", [(True, 1), (False, 0)])
def test_a_twice_assigned_figure_counts_one_try_per_run(repo, make_figure, tmp_path, log, monkeypatch, judged, runs):
    brief, candidate = make_figure()
    pending.record(repo, brief, "r0", [], attempted=False)      # reopened: runs 0
    monkeypatch.setattr("school_notes2.notify.pending.send", lambda ctx_, notice: True)
    ctx = SimpleNamespace(name="one", notes_path=repo, log=log, cfg=SimpleNamespace(state_dir=tmp_path / "vm"))
    receipt = {"status": "reviewed", "model": "m", "review": {"figures": [{
        "id": brief["id"], "verdict": "repair", "key": "k", "text_mismatch": [],
        "defects": [{"location": "map", "observed": "x", "expected": "y", "severity": "hiba"}]}],
        "owner_notes": []}} if judged else {"status": "pending", "reason": "invalid output", "timed_out": False}
    task = phase.create(tmp_path / "state", "one", "notes", "cron", "review_ready")
    state = {"brief": brief, "candidate": candidate, "attempted": True}
    task.update(attempt=1, inspection_receipts={brief["id"]: receipt}, inspection_figures=[state, state])
    for _ in range(2):                                          # a replayed finalize counts nothing
        review_phases.record_figures(ctx, phase.load(task.dir))
    [entry] = pending.load(repo)
    assert entry["runs"] == runs and entry["run_ids"] == ([task.run_id] if judged else [])
    assert not entry["owner_required"]
