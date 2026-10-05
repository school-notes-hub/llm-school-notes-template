"""Bind independent rejection to the paid candidate, without changing its cost."""

from ..figures import commissions, context, migration_gate
from ..state.files import write_json
from ..wiki.pages import sha256
from . import budget, plans


def record(settings, briefs, receipt):
    rejected = {v["id"]: v for v in receipt.get("review", {}).get("figures", [])
                if v["verdict"] in ("repair", "reject")}
    for brief in sorted(briefs, key=lambda b: b["id"]):
        verdict = rejected.get(brief["id"])
        if not verdict or migration_gate.concerns(settings.worktree, brief):
            continue
        candidate = commissions.candidate(settings.worktree, brief)
        if not candidate.get("asset") or context.verdict_key(settings.worktree, brief, candidate) != verdict["key"]:
            continue
        key = plans.job_id(settings.learner, brief["id"])
        if key not in settings.ledger().get("jobs", {}):
            continue
        digest = sha256(settings.worktree, candidate["asset"])
        with budget.images_lock(settings.lock_path, settings.lock_timeout_s):
            ledger = settings.ledger()
            job = ledger.get("jobs", {}).get(plans.job_id(settings.learner, brief["id"]), {})
            changed = False
            for attempt in job.get("attempts", []):
                if attempt["state"] == "generated" and digest in (attempt.get("sha256"), attempt.get("preview_sha256")):
                    attempt.update(state="rejected", figure_verdict=verdict)
                    changed = True
            if changed:
                write_json(settings.state_dir / "ledger.json", ledger)
