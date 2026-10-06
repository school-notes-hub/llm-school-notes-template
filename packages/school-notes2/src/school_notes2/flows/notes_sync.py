"""The idle notes worktree follows the local origin/main (fix-51).

`ready()`, the status and the next run's selection read the notes worktree. The nightly
review commits and pushes from the review worktree, and a run's Drive check or a release
fetches origin/main; until something moved the notes worktree, it showed the older commit:
a nightly item was invisible ("0 nyitott tétel", "lezárult").

Purely mechanical and safe: only with the learner lock held, only when no notes run is open,
only from a clean worktree, only a fast-forward to the local origin/main (no fetch), with a
plain `switch` that refuses to overwrite anything. Finished work is never discarded."""

from ..git import repos, workbranch
from ..state import phase

MAIN = "refs/remotes/origin/main"


def catch_up(ctx) -> str:
    """Move the idle notes worktree to origin/main; returns the outcome (logged when it acted
    or refused). Never raises: a failure leaves the worktree as it was."""
    try:
        outcome = _catch_up(ctx)
    except Exception as exc:  # noqa: BLE001 - the caller's own result must not change
        ctx.log.event("notes.catch_up", "error", level="warning", message=str(exc)[:200])
        return "error"
    if outcome not in ("current", "busy"):
        ctx.log.event("notes.catch_up", outcome)
    return outcome


def _catch_up(ctx) -> str:
    if not (ctx.notes_path / ".git").exists():
        return "current"
    if phase.open_task(ctx.task_root(), ctx.name, "notes") is not None:
        return "busy"                     # an open run owns the worktree, even between steps
    wt = ctx.worktree("notes")
    if not repos.has_ref(wt, MAIN):
        return "current"
    head, main = repos.rev(wt, "HEAD"), repos.rev(wt, MAIN)
    if head == main:
        return "current"
    if workbranch.worktree_dirty(wt):
        return "refused_dirty"            # edits outside a run: `school-notes chat` decides
    if not repos.is_ancestor(wt, head, main):
        return "refused_diverged"         # a commit not on origin/main is never left behind
    wt.run("switch", "--detach", main, timeout=600)
    return "moved"


def behind(ctx) -> int | None:
    """Status (read-only): commits of the local origin/main the idle notes worktree lacks;
    None when a run is open or the refs are missing."""
    try:
        if phase.open_task(ctx.task_root(), ctx.name, "notes") is not None:
            return None
        wt = ctx.worktree("notes")
        return int(wt.out("rev-list", "--count", f"HEAD..{MAIN}").strip() or 0)
    except Exception:  # noqa: BLE001 - status never fails on a missing worktree or ref
        return None
