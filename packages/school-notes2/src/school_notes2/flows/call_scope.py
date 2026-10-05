"""Route finish defects to durable subject calls, without blaming another writer."""

from ..review import relations
from ..sources import calls
from ..state import safefs
from ..state.errors import SnError


def subjects(ctx, items):
    embedded = relations.related_pages(ctx.notes_path) if any(
        i["file"].startswith("wiki/assets/") for i in items) else {}
    return {i["file"]: calls.subject(i["file"], embedded) for i in items}


def fix_pages(ctx, task):
    """Route same-subject page groups and first-call figures to their own call."""
    if task.get("mode") != "fix":
        return {}
    known = relations.inventory(ctx.notes_path)["items"]
    pending = {e["commission"]["id"]: e["commission"]["page"] for e in task.get("pending_figures", [])}
    related, assigned = relations.related_pages(ctx.notes_path), {}
    for k, call in enumerate(task.get("calls", []), 1):
        pages = [pending[fid] for fid in call.get("pending_figure_ids", []) if fid in pending]
        pages += [known.get(i["file"] + "#" + i["item_id"], {}).get("file", "")
                  for i in call.get("open_review_items", [])]
        for page in sorted(set(pages) - {""}):
            for path in sorted({page} | set(related.get(page, []))):
                assigned.setdefault(path, set()).add(k)
    for asset, pages in sorted(related.items()):
        owners = {k for p in pages for k in assigned.get(p, [])}
        if owners:
            assigned.setdefault(asset, set()).update(owners)
    return {p: sorted(owners) for p, owners in sorted(assigned.items())}


def current(ctx, task, items, k=None):
    # Checks cover all changes, including pages outside this call's focus.
    return items


def retry(ctx, task, items):
    from . import steps
    steps.write_check_items(ctx, items)
    assigned = task.get("calls", [])
    if not assigned:  # Saved runs from before subject assignments keep their old range.
        groups = {str(len(task.get("ranges"))): items}
    else:
        located, groups, unassigned = subjects(ctx, items), {}, []
        pages = fix_pages(ctx, task)
        for item in items:
            name = located[item["file"]]
            k = next(iter(pages.get(item["file"], [])), None) or next((n for n, c in enumerate(assigned, 1) if name and c["subject"] == name), None)
            if item["file"] == ".school-notes/result.json" or (not name and item["file"].startswith("wiki/")):
                k = 1  # Same fallback as the original subjectless/asset assignment.
            if k is None and item.get("kind") == "browser-link":
                target_subject = calls.subject(item.get("target", ""))
                k = next(iter(pages.get(item.get("target"), [])), None) or next((n for n, c in enumerate(assigned, 1) if c["subject"] == target_subject), None)
            if k is None and item["file"].startswith("wiki/"):
                k = 1
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
    paths = set(task.get("retry_link_pages", []))
    paths.update(p for i in items if i.get("kind") == "browser-link"
                 for p in (i["file"], i.get("target")) if p)
    task.set_phase("writing", writing_k=pending[0], retry_calls=pending, retry_items=groups,
                   retry_link_pages=sorted(paths),
                   attempt=task.get("attempt", 1) + 1, review_complete=False)
    invalidate(task)


def invalidate(task):
    pending = task.get("retry_calls", [])
    if pending:
        for k in pending:
            (task.dir / f"result-{k}.json").unlink(missing_ok=True)
        counts = dict(task.get("fix_calls", {}))
        for k in pending:
            counts[str(k)] = 0
        task.update(retry_calls=[], fix_calls=counts, writer_output_key=None)


def write_check(ctx, task, k):
    from . import steps
    # Upgrade already queued retries before consuming their old per-call items.
    task.update(retry_link_pages=link_pages(task))
    pending = dict(task.get("retry_items", {}))
    items = pending.pop(str(k), None)
    if items is None:
        items = safefs.read_json(ctx.notes_path, ".school-notes/check.json") or []
    steps.write_check_items(ctx, current(ctx, task, items, k))
    if pending != task.get("retry_items", {}):
        task.update(retry_items=pending)


def link_pages(task):
    paths = set(task.get("retry_link_pages", []))
    paths.update(p for items in task.get("retry_items", {}).values() for i in items
                 if i.get("kind") == "browser-link" for p in (i["file"], i.get("target")) if p)
    return sorted(paths)
