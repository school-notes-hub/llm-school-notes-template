"""Route failed repair output; retain recovery of pre-upgrade owner-queue checkpoints."""

from contextlib import nullcontext

from ..notify import Notice
from ..notify import pending
from ..review.repair_migration import POLICY
from ..state import safefs
from ..state.errors import BadWork
from ..wiki import frontmatter
from . import queue


def handle(ctx, task, exc) -> bool:
    if task is None or task.get("mode") != "repair" or task.get("queue_only") or not isinstance(exc, BadWork):
        return False
    from ..flows import operation, policy
    with nullcontext() if operation.CURRENT.get() else operation.scope(ctx):
        policy.on_error(exc, task=task, student=ctx.name, step="repair", log=ctx.log, mailer=None)
    return True


def restore(ctx, task):
    """A pre-upgrade failed handoff: the topic goes to the owner; nothing is discarded."""
    if not task.get("repair_failed"):
        return
    data = queue.load(ctx.notes_path)
    for item in data["items"]:
        if item["page"] == task.get("repair_topic"):
            item["status"] = "owner"
    task.update(queue_only=True, repair_queue=data,
                repair_queue_absent=not safefs.is_file(ctx.notes_path, queue.PATH))


def write_item(ctx, task):
    if not task.get("repair_failed"):
        return
    from ..flows import steps
    rel = f"docs/review/{task.run_id}-repair.md"
    topic = task.get("repair_topic")
    text = frontmatter.set_keys(
        f"# Egyszeri javítás\n\n### R1 - {topic}\n\nKét sikertelen átdolgozás; tulajdonosi döntés szükséges.\n",
        {"status": "owner", "repair_policy": POLICY, "items": {"R1": "owner"}, "item_details": {
            "R1": {"file": topic, "origin": "repair", "round": 1, "chain": 0}}})
    safefs.write_text(ctx.notes_path, rel, text)
    steps.record_tool_files(task, ctx.notes_path, [rel])
    task.update(repair_owner_item=rel)


def notify(ctx, task):
    if task.get("repair_owner_item"):
        pending.send(ctx, Notice(ctx.name, f"repair_owner:{task.run_id}", task.run_id,
                                    "repair", "owner", f"{task.get('repair_topic')}: két sikertelen átdolgozás.",
                                    f"Dönts a {task.get('repair_owner_item')} R1 tételéről; a sor többi eleme folytatódik."))
