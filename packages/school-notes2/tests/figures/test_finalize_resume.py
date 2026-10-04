"""A tool failure at P6 can resume after owner clear, without another LLM call."""

import pytest

from school_notes2.flows import clear, finish, policy, review_phases, steps
from school_notes2.state import phase, safefs
from school_notes2.state.errors import SnError
from school_notes2.wiki import public
from tests.notify.test_pending import context
from test_insert import receipt


@pytest.mark.parametrize("learner", ["benedek", "barna"])
def test_review_ready_public_failure_then_clear_replays_finalize(
        repo, make_figure, tmp_path, log, monkeypatch, learner):
    ctx = context(tmp_path, log, learner)
    brief, candidate = make_figure()
    safefs.write_text(repo, "wiki/index.md", "# Jegyzetek\n")
    candidate["source"] = "wiki/assets/physics/forces.py"
    safefs.write_text(repo, candidate["source"], "# Drawing source\n")
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    task = phase.create(tmp_path, learner, "notes", "cron", "review_ready")
    task.update(ranges=[], inspection_figures=[{"brief": brief, "candidate": candidate}],
                inspection_receipts={brief["id"]: receipt(repo, brief, candidate)})
    # Only omit unrelated index generation; exercise the real insertion/public write.
    monkeypatch.setattr(steps, "generate_all", steps.write_public)
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {})
    original = public.media_receipt_rights
    monkeypatch.setattr(public, "media_receipt_rights", lambda repo: lambda rel: None)
    with pytest.raises(SnError, match="unchanged tool output") as caught:
        finish.finish(ctx, task, notify_owner_items=lambda items: None)
    assert policy.on_error(caught.value, task=task, student=learner, step="finish",
                           log=log, mailer=None) == "program"
    task = phase.load(task.dir)
    assert task.phase == "review_ready" and not task.get("review_complete")
    assert task.data["needs_owner"]["class"] == "program"
    # Replay the old production record, including its missing rights field.
    path = "docs/evidence/media/forces/figure.json"
    evidence = safefs.read_json(repo, path)
    evidence.pop("rights")
    safefs.write_json(repo, path, evidence)
    monkeypatch.setattr(public, "media_receipt_rights", original)
    assert "review_ready" in clear.clear(ctx, "notes", "continue")
    task = phase.load(task.dir)
    assert not task.data["needs_owner"]
    calls = []
    finalize = review_phases.finalize
    def resumed(ctx, task, edits=None):
        calls.append(task.phase)
        finalize(ctx, task, edits)
    monkeypatch.setattr(review_phases, "finalize", resumed)
    def git_finish(task, *args):
        assert task.phase == "finishing" and task.get("review_complete")
        task.set_phase("done")
        return "done"
    monkeypatch.setattr(finish.git_finish, "run", git_finish)
    assert finish.finish(ctx, task, notify_owner_items=lambda items: None) == "done"
    assert calls == ["review_ready"]
    assert safefs.read_json(repo, "publication/public.json")["assets"][0]["rights"] == "authored"
    assert safefs.read_text(repo, brief["page"]).count("![Two opposing arrows]") == 1
