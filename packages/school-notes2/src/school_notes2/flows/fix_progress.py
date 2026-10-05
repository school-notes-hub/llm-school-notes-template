"""Time brake: work that made no progress in a run waits 24 hours, per item (#21, Fable 15)."""

from datetime import datetime, timedelta

from ..figures import pending
from ..images import budget
from ..log import TZ
from ..review import relations
from ..state.files import read_json, write_json

PARK = timedelta(hours=24)
CLOSED = ("fixed", "disagree", "question", "settled", "owner")


def keys(items, waiting):
    return sorted({i["file"] + "#" + i["item_id"] for i in items} |
                  {"figure:" + e["commission"]["id"] for e in waiting})


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "parked.json"


def parked(ctx, now=None):
    now = now or datetime.now(TZ)
    return {key for key, until in read_json(path(ctx), {}).items()
            if datetime.fromisoformat(until) > now}


def available(ctx, items, waiting):
    stopped = parked(ctx)
    return ([i for i in items if i["file"] + "#" + i["item_id"] not in stopped],
            [e for e in waiting if "figure:" + e["commission"]["id"] not in stopped])


def image_wait(ctx, waiting):
    """Temporary spending/unknown stops are not failed repair attempts."""
    generated = [e for e in waiting if pending.generated(ctx.notes_path, e["commission"])]
    if not generated:
        return False
    settings = ctx.image_settings()
    ledger = settings.ledger()
    return bool(budget.unknown_calls(ledger)) or not budget.budget_left(
        ledger, settings.today(), settings.daily_usd, settings.reservation_usd, settings.monthly_usd)


def runnable_images(ctx, waiting):
    from . import correction_figures
    if not image_wait(ctx, waiting):
        return waiting
    return [e for e in waiting if not pending.generated(ctx.notes_path, e["commission"])
            or correction_figures.awaiting(ctx, e["commission"])]


def record(ctx, task, now=None):
    """Park each assigned key without progress for 24 hours; progressed keys are freed."""
    if task.get("mode") != "fix" or task.phase == "done":
        return
    work = sorted(set(task.get("fix_work", [])) | set(task.get("assigned_work", [])))
    known = relations.inventory(ctx.notes_path)["items"]
    remaining = {e["commission"]["id"]: e for e in pending.load(ctx.notes_path)}
    previous = {e["commission"]["id"]: e for e in task.get("pending_figures", [])}
    now = now or datetime.now(TZ)
    state = {k: v for k, v in read_json(path(ctx), {}).items() if datetime.fromisoformat(v) > now}
    stalled = []
    for key in work:
        if key.startswith("figure:"):
            fid = key[7:]
            entry = remaining.get(fid)
            moved = entry is None or entry["runs"] > previous.get(fid, {}).get("runs", 0)
        else:
            item = known.get(key, {})
            # A writer decision recorded in this run is progress, even if P5 reopened it.
            moved = item.get("status") in CLOSED or task.run_id in item.get("repair_runs", [])
        if moved:
            state.pop(key, None)
        else:
            stalled.append(key)
            state[key] = (now + PARK).isoformat()
    write_json(path(ctx), dict(sorted(state.items())))
    task.update(fix_stalled=stalled)
    if stalled:
        ctx.log.event("fix.parked", items=stalled, hours=24)
