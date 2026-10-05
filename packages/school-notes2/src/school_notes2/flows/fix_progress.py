"""Stop repeated zero-progress repairs until new work or a new release arrives."""

from ..figures import pending
from ..images import budget
from ..review import relations
from . import set_aside


def keys(items, waiting):
    return sorted({i["file"] + "#" + i["item_id"] for i in items} |
                  {"figure:" + e["commission"]["id"] for e in waiting})


def available(ctx, items, waiting):
    stopped = set_aside.blocked(ctx)
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


def record(ctx, task):
    if task.get("mode") != "fix" or task.phase == "done":
        return
    work = set_aside.work(task)
    known = relations.inventory(ctx.notes_path)["items"]
    closed = sum(known.get(key, {}).get("status") in
                 ("fixed", "disagree", "question", "settled", "owner")
                 for key in work if not key.startswith("figure:"))
    remaining = {e["commission"]["id"] for e in pending.load(ctx.notes_path)}
    accepted = sum(key[7:] not in remaining for key in work if key.startswith("figure:"))
    task.update(fix_progress=closed + accepted)
    if closed + accepted:
        set_aside.progressed(ctx, task)
    waiting = [e for e in pending.load(ctx.notes_path) if "figure:" + e["commission"]["id"] in work]
    only_waiting = all(key.startswith("figure:") for key in work) and not runnable_images(ctx, waiting)
    if work and closed + accepted == 0 and not only_waiting:
        set_aside.record(ctx, task, "no-progress")
        task.update(no_progress=True)
        set_aside.no_progress_notice(ctx, task)
