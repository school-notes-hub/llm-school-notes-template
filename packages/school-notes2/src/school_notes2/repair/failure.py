"""Two failed repairs leave an owner item and let the persisted queue continue (T-077)."""

from ..git import discard, repos
from ..notify import Notice
from ..state import safefs
from ..state.errors import BadWork
from ..wiki import frontmatter
from . import queue


def handle(ctx, task, exc) -> bool:
    if task is None or task.get("mode") != "repair" or task.get("queue_only") or not isinstance(exc, BadWork):
        return False
    from ..flows import policy
    policy.on_error(exc, task=task, student=ctx.name, step="repair", log=ctx.log, mailer=None)
    if task.data["llm_failures"] >= 2:
        task.data["needs_owner"] = None
        task.set_phase("moved", repair_failed=True)
    return True


def restore(ctx, task):
    if not task.get("repair_failed"):
        return
    if not task.get("repair_discarded"):
        bundle = discard.discard(ctx.worktree("notes"), task.run_id, ctx.cfg.root / "archive" / ctx.name)
        task.update(repair_discarded=True, repair_bundle=str(bundle) if bundle else None,
                    base=repos.rev(ctx.worktree("notes"), "refs/remotes/origin/main"),
                    tool_writes={}, tool_parts={}, tool_hashes={}, learning_pending=None)
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
        {"status": "owner", "items": {"R1": "owner"}, "item_details": {
            "R1": {"file": topic, "origin": "repair", "round": 1, "chain": 0}}})
    safefs.write_text(ctx.notes_path, rel, text)
    steps.record_tool_files(task, ctx.notes_path, [rel])
    task.update(repair_owner_item=rel)


def notify(ctx, task):
    if task.get("repair_owner_item"):
        ctx.mailer.send_once(Notice(ctx.name, f"repair_owner:{task.run_id}", task.run_id,
                                    "repair", "owner", f"{task.get('repair_topic')}: két sikertelen átdolgozás.",
                                    f"Dönts a {task.get('repair_owner_item')} R1 tételéről; a sor többi eleme folytatódik."))
