"""Journal scope repairs before changing files, for P4 and source-free fix runs."""

from pathlib import Path

from ..state import safefs
from . import call_scope, correction, steps

TOOL_STATE = ("tool_writes", "tool_parts", "tool_hashes")


def restore_pages(repo, root, before, outside):
    saved = safefs.read_json(root, "scope-restores.json", [])
    paths = sorted(set(saved) | set(outside))
    if not paths:
        return []
    # The complete list is durable before the first replacement/deletion.
    safefs.write_json(root, "scope-restores.json", paths)
    for path in paths:
        if path in before:
            safefs.write_bytes(repo, path, safefs.read_bytes(root, "before/" + path))
        else:
            safefs.unlink(repo, path)
    return paths


def recover(ctx, task, root=None, items=None):
    if root is None and (task.get("mode") != "fix" or not task.get("correction_before")):
        return []
    root = root or Path(task.get("correction_before")).parent
    items = task.get("open_review_items", []) if items is None else items
    paths = correction.check_scope(ctx, root, items,
                                   [e["commission"]["page"] for e in task.get("pending_figures", [])]
                                   + call_scope.link_pages(task), restore=True)
    if paths:
        refresh_records(ctx, task, paths)
    owner_notes(ctx, task, root)
    return paths


def owner_notes(ctx, task, root):
    paths = safefs.read_json(root, "scope-restores.json", [])
    if not paths:
        return
    note = "A javítás hatókörén kívüli oldalak visszaállítva: " + ", ".join(paths) + "."
    notes = task.get("scope_owner_notes", [])
    if note not in notes:
        ctx.log.event("fix.scope_restored", pages=paths, message=note)
        task.update(scope_owner_notes=notes + [note])


def rollback(ctx, task, exc):
    root = task.dir / "fix-before"
    if task.get("mode") != "fix" or not safefs.read_json(root, "scope-restores.json", []):
        return False
    safefs.write_json(root, "rollback.json", {"reason": str(exc)})
    resume(ctx, task)
    return True


def resume(ctx, task):
    root = task.dir / "fix-before"
    saved = safefs.read_json(root, "rollback.json")
    if not saved or task.get("fix_scope_rolled_back"):
        return
    correction.restore(ctx.notes_path, root)
    owner_notes(ctx, task, root)
    state = safefs.read_json(root, "tool-state.json")
    if state is not None:
        task.update(**state, learning_pending=None)
    else:  # A pre-upgrade snapshot has files, but no separate tool-state receipt.
        paths = sorted({p for key in TOOL_STATE for p in task.get(key, {})})
        refresh_records(ctx, task, paths)
        task.update(learning_pending=None)
    ctx.log.event("fix.scope_rollback", reason=saved["reason"])
    task.set_phase("figures", fix_scope_rolled_back=True, skip_writer=True, pending_figures=[],
                   inspection_result={"status": "done"}, correction_rolled_back=True,
                   correction_rollback_reason=saved["reason"])


def refresh_records(ctx, task, paths):
    # Restoring bytes also restores their machine-part provenance; drop receipts
    # for new pages removed by the rollback, without granting any new scope.
    state = {key: {p: value for p, value in task.get(key, {}).items() if p not in paths}
             for key in TOOL_STATE}
    if (task.get("learning_pending") or {}).get("path") in paths:
        state["learning_pending"] = None
    task.update(**state)
    steps.record_tool_files(task, ctx.notes_path, [p for p in paths if safefs.is_file(ctx.notes_path, p)])
