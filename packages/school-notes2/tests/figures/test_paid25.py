"""The final paid candidate needs judgement before owner escalation."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from school_notes2.figures import context, pending
from school_notes2.flows import correction_figures, review_phases
from school_notes2.images import executor, generate, judgement
from school_notes2.state import phase, safefs
from school_notes2.state.files import read_json, write_json
from school_notes2.wiki.pages import sha256
from tests.figures.test_capacity24 import settings


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("paid_disabled", [False, True])
def test_unreviewed_last_image_gets_free_recheck(repo, make_figure, learner, paid_disabled):
    brief, _ = make_figure(kind="banner")
    entry = pending.record(repo, brief, "old", [], attempted=True)
    config = settings(learner, ["rejected", "rejected", "generated"])
    config.daily_usd = Decimal(0)
    ctx = SimpleNamespace(notes_path=repo, image_settings=lambda: config,
                          name=learner, cfg=SimpleNamespace(state_dir=repo.parent / "state"))
    assert not correction_figures.mark_exhausted(ctx, entry)
    assert correction_figures.assignable(ctx, [entry], paid_disabled=paid_disabled) == [entry]
    assert generate._blocked(config, f"{learner}-forces") is None
    assert generate._blocked(config, f"{learner}-forces", repairing=True)["state"] == "exhausted"
    assert not entry["owner_required"]


def test_third_unreviewed_run_resumes_without_owner(repo, make_figure, monkeypatch, log):
    brief, _ = make_figure(kind="banner")
    for rid in ("one", "two"):
        pending.record(repo, brief, rid, [], attempted=True)
    config = settings("one", ["rejected", "rejected", "generated"])
    config.daily_usd = Decimal(0)
    ctx = SimpleNamespace(notes_path=repo, log=log, image_settings=lambda: config,
                          name="one", cfg=SimpleNamespace(state_dir=repo.parent / "state"))
    task = phase.create(repo.parent, "one", "notes", "cron", "review_ready")
    task.update(inspection_figures=[{"brief": brief, "candidate": {"state": "candidate"}, "attempted": True}])
    monkeypatch.setattr(review_phases.steps, "generate_all", lambda *a: None)
    monkeypatch.setattr(review_phases.steps, "record_tool_files", lambda *a: None)
    monkeypatch.setattr(review_phases.notices, "refresh", lambda *a, **kw: [])
    for _ in range(2):
        review_phases.finalize(ctx, phase.load(task.dir))
    entry = pending.load(repo)[0]
    assert entry["runs"] == 3 and entry["review_pending"] and not entry["owner_required"]
    assert correction_figures.assignable(ctx, [entry]) == [entry]


@pytest.mark.parametrize("last", ["unknown", "lost", "accepted", "generated"])
def test_exhaustion_requires_no_unreviewed_candidate(last):
    entry = {"attempts": [{"state": "rejected"}, {"state": "rejected"}, {"state": last}]}
    assert generate.exhausted(entry, 3) == (last not in ("generated", "unknown"))
    entry["attempts"][-1]["state"] = "rejected"
    entry["attempts"].append({"state": "failed"})
    assert generate.exhausted(entry, 3)


@pytest.mark.parametrize("stale", [False, True])
def test_rejection_binds_exact_paid_image_and_replays(repo, make_figure, monkeypatch, stale):
    brief, candidate = make_figure(kind="banner")
    state = repo.parent / "state"
    path = state / "ledger.json"
    digest = sha256(repo, candidate["asset"])
    ledger = {"jobs": {"one-forces": {"attempts": [
        {"state": "generated", "sha256": "old", "cost_usd": "0.05"},
        {"state": "generated", "preview_sha256": digest, "cost_usd": "0.05"}]}}}
    write_json(path, ledger)
    config = SimpleNamespace(worktree=repo, learner="one", state_dir=state,
        lock_path=state / "images.lock", lock_timeout_s=1, ledger=lambda: read_json(path))
    key = context.verdict_key(repo, brief, candidate)
    receipt = {"review": {"figures": [{"id": brief["id"], "verdict": "reject", "key": "stale" if stale else key}]}}
    if stale:
        judgement.record(config, [brief], receipt)
        assert read_json(path) == ledger
        return
    original = judgement.write_json
    def crash(*args):
        original(*args)
        raise KeyboardInterrupt()
    monkeypatch.setattr(judgement, "write_json", crash)
    with pytest.raises(KeyboardInterrupt):
        judgement.record(config, [brief], receipt)
    monkeypatch.setattr(judgement, "write_json", original)
    before = path.read_bytes()
    judgement.record(config, [brief], receipt)
    assert path.read_bytes() == before
    attempts = read_json(path)["jobs"]["one-forces"]["attempts"]
    assert [a["state"] for a in attempts] == ["generated", "rejected"]
    assert [a["cost_usd"] for a in attempts] == ["0.05", "0.05"]


@pytest.mark.parametrize("paid_disabled", [False, True])
def test_free_recheck_never_invokes_generation(repo, make_figure, log, monkeypatch, paid_disabled):
    brief, _ = make_figure(kind="banner")
    config = settings("one", ["rejected", "rejected", "generated"])
    config.worktree, config.lock_path, config.lock_timeout_s = repo, repo.parent / "images.lock", 1
    config.script = Path(__file__).resolve().parents[4] / "tools/learning_image.py"
    api = executor.module(config.script)
    spec = {"id": "one-forces", "learner": "one", "target": "unused", "role": "banner"}
    job = config.ledger()["jobs"]["one-forces"]
    job.update(id=spec["id"], logical=api.logical_target(spec), fingerprint=api.job_fingerprint(spec))
    job["attempts"][-1].update(number=3, sha256="a" * 64)
    monkeypatch.setattr(generate.plans, "build_job", lambda *a: spec)
    monkeypatch.setattr(generate.plans, "keep", lambda *a: None)
    monkeypatch.setattr(generate.plans, "write_job", lambda *a: None)
    monkeypatch.setattr(generate, "_preview", lambda *a: {"preview": "cached.webp"})
    monkeypatch.setattr(generate, "_attempts", lambda *a: pytest.fail("free recheck tried paid generation"))
    answer = generate.generate(config, brief["id"], log=log, paid_disabled=paid_disabled)
    assert answer["state"] == "generated" and answer["number"] == 3
    assert answer["preview"] == "cached.webp" and len(job["attempts"]) == 3


@pytest.mark.parametrize("note", [None, "Repair it"])
def test_repair_handler_only_allows_assigned_free_recheck(repo, make_figure, monkeypatch, note):
    from school_notes2.flows import handlers
    brief, _ = make_figure(kind="banner")
    task = phase.create(repo.parent, "one", "notes", "cron", "prepared")
    task.update(mode="repair", pending_figures=[{"commission": brief}])
    calls = []
    ctx = SimpleNamespace(image_settings=lambda: "settings", log=None)
    monkeypatch.setattr(handlers.image_generate, "generate", lambda *a, **kw: calls.append((a, kw)) or {"state": "generated"})
    result = handlers.generate(ctx, task, brief["id"], note)
    assert result["state"] == ("generated" if note is None else "disabled")
    assert len(calls) == (1 if note is None else 0)
    if calls:
        assert calls[0][1]["paid_disabled"] is True
    assert handlers.generate(ctx, task, "unassigned", None)["state"] == "disabled"
