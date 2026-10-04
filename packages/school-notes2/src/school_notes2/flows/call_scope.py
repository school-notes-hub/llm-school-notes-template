"""Route finish defects to durable subject calls, without blaming another writer."""

from ..review import relations
from ..sources import calls
from ..state import safefs
from ..state.errors import SnError


def subjects(ctx, items):
    embedded = relations.related_pages(ctx.notes_path) if any(
        i["file"].startswith("wiki/assets/") for i in items) else {}
    return {i["file"]: calls.subject(i["file"], embedded) for i in items}


def current(ctx, task, items, k=None):
    assigned = task.get("calls", [])
    if not assigned or (task.mode == "interactive" and task.get("mode") != "repair"):
        return items
    k = k or task.get("writing_k", 1)
    name = assigned[min(k, len(assigned)) - 1]["subject"]
    known = {c["subject"] for c in assigned}
    located = subjects(ctx, items)
    # Unlocated invocation errors (e.g. its result.json) still belong to this call.
    return [i for i in items if located[i["file"]] == name or located[i["file"]] not in known]


def retry(ctx, task, items):
    from . import steps
    steps.write_check_items(ctx, items)
    assigned = task.get("calls", [])
    if not assigned:  # Saved runs from before subject assignments keep their old range.
        groups = {str(len(task.get("ranges"))): items}
    else:
        located, groups, unassigned = subjects(ctx, items), {}, []
        for item in items:
            name = located[item["file"]]
            k = next((n for n, c in enumerate(assigned, 1) if name and c["subject"] == name), None)
            if k is None:
                unassigned.append(item)
            else:
                groups.setdefault(str(k), []).append(item)
        if unassigned:
            raise SnError("finish errors cannot be assigned to a writer call",
                          details={"items": unassigned}, todo="inspect the finish check and repair the tool")
    pending = sorted(map(int, groups))
    if not pending or task.get("skip_writer"):
        raise SnError("finish failed without a writer assignment", details={"items": items})
    # Persist before invalidating checkpoints. Resume repeats only unfinished calls.
    task.set_phase("writing", writing_k=pending[0], retry_calls=pending, retry_items=groups)
    invalidate(task)


def invalidate(task):
    pending = task.get("retry_calls", [])
    if pending:
        for k in pending:
            (task.dir / f"result-{k}.json").unlink(missing_ok=True)
        task.update(retry_calls=[])


def write_check(ctx, task, k):
    from . import steps
    pending = dict(task.get("retry_items", {}))
    items = pending.pop(str(k), None)
    if items is None:
        items = safefs.read_json(ctx.notes_path, ".school-notes/check.json") or []
    steps.write_check_items(ctx, current(ctx, task, items, k))
    if pending != task.get("retry_items", {}):
        task.update(retry_items=pending)
