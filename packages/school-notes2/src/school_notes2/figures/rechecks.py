"""Two free review assignments per commission, retained even after rollback."""

from ..images import plans
from ..images.generate import awaiting_review
from ..state.files import read_json, write_json
from . import migration_gate, pending

PATH = "figure-rechecks.json"
LIMIT = 2


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / PATH


def exhausted(ctx, figure_id):
    return len(read_json(path(ctx), {}).get(figure_id, [])) >= LIMIT


def record(ctx, task, entries):
    if not entries or migration_gate.blocked(ctx.notes_path):
        return
    generated = [e["commission"] for e in entries if pending.generated(ctx.notes_path, e["commission"])]
    if not generated:
        return
    settings = ctx.image_settings()
    jobs = settings.ledger().get("jobs", {})
    ids = sorted(b["id"] for b in generated
                 if awaiting_review(jobs.get(plans.job_id(settings.learner, b["id"]), {"attempts": []})))
    if not ids:
        return
    saved = read_json(path(ctx), {})
    # Ranges of one writer assignment and its crash retries share one receipt.
    # P4 has a distinct child run ID and therefore consumes its own assignment.
    assignment = task.run_id
    changed = False
    for fid in ids:
        previous = saved.get(fid, [])
        if assignment in previous:
            continue
        if len(previous) >= LIMIT:
            raise ValueError(f"free figure review assignments exhausted: {fid}")
        saved[fid] = sorted([*previous, assignment])
        changed = True
    if changed:
        write_json(path(ctx), dict(sorted(saved.items())))
