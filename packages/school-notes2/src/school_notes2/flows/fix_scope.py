"""Protected-byte recovery and completion of already journaled legacy rollbacks."""

from ..state import safefs
from . import correction, steps

TOOL_STATE = ("tool_writes", "tool_parts", "tool_hashes", "tool_originals")


def recover(ctx, task, root=None, items=None):
    """Assignments never authorize or undo pages; repair only tool-owned bytes."""
    from . import protected
    return protected.restore(ctx, task)


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
    # Kept for callers and old task receipts; no new scope rollback is created.
    return False


def resume(ctx, task):
    root = task.dir / "fix-before"
    saved = safefs.read_json(root, "rollback.json")
    if not saved or task.get("fix_scope_rolled_back"):
        return
    correction.restore(ctx.notes_path, root)
    owner_notes(ctx, task, root)
    state = safefs.read_json(root, "tool-state.json")
    if state is not None:
        # A 2.5.0 receipt has no originals: later records must not outlive the rollback.
        task.update(**{"tool_originals": {}, **state}, learning_pending=None)
    else:  # A pre-upgrade snapshot has files, but no separate tool-state receipt.
        paths = sorted({p for key in TOOL_STATE for p in task.get(key, {})})
        refresh_records(ctx, task, paths)
        task.update(learning_pending=None)
    ctx.log.event("fix.scope_rollback", reason=saved["reason"])
    task.set_phase("figures", fix_scope_rolled_back=True, skip_writer=True, pending_figures=[],
                   scope_owner_items=[],
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


def dependency_items(ctx, root):
    # Old scope-restores receipts are evidence only, never a new check gate.
    return []


def check_dependencies(ctx, task):
    return None


def related_errors(ctx, root, problems, *, require_all=True):
    return False
