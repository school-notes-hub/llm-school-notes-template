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


def record(ctx, task):
    if task.get("mode") != "fix":
        return
    known = relations.inventory(ctx.notes_path)["items"]
    closed = sum(known.get(i["file"] + "#" + i["item_id"], {}).get("status")
                 in ("fixed", "disagree", "question", "settled", "owner") for i in task.get("open_review_items", []))
    remaining = {e["commission"]["id"] for e in pending.load(ctx.notes_path)}
    accepted = sum(e["commission"]["id"] not in remaining for e in task.get("pending_figures", []))
    task.update(fix_progress=closed + accepted)
    from . import correction_figures
    waiting = task.get("pending_figures", [])
    only_waiting = not task.get("open_review_items") and all(
        pending.generated(ctx.notes_path, e["commission"]) and not correction_figures.awaiting(ctx, e["commission"])
        for e in waiting) and image_wait(ctx, waiting)
    if closed + accepted == 0 and not only_waiting:
        set_aside.record(ctx, task, "no-progress")
