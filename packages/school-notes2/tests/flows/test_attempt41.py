"""P1 fix receipts use round one even after a finish retry."""

from school_notes2.flows import steps
from school_notes2.state import phase, safefs
from tests.flows.test_learning_checks import learning_run


def test_content_steps_uses_first_round_of_current_attempt(learning_run, monkeypatch):
    ctx, task = learning_run
    task.data["mode"] = "cron"
    task.update(mode="fix", attempt=2, correction_round=3, skip_writer=True)
    seen = []
    original = steps.review_files.apply_closure
    def close(repo, run_id, *args, **kwargs):
        seen.append(run_id)
        return original(repo, run_id, *args, **kwargs)
    monkeypatch.setattr(steps.review_files, "apply_closure", close)
    steps.content_steps(ctx, task)
    steps.content_steps(ctx, phase.load(task.dir))
    assert seen == [task.run_id + "-fix-a2-r1"] * 2
