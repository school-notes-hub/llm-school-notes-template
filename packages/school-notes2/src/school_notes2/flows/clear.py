"""`school-notes status --clear <learner> notes|review|publish --continue|--discard` (8.3).

Only the owner, only on the host. Continue resets the counters and resumes from the
recorded phase; a blocking question and a content conflict continue only in `chat`."""

from .. import VERSION
from ..git import discard as git_discard
from ..notify import incidents
from ..log import now_iso, today
from ..review import close as review_close
from ..state import phase
from ..state.errors import NeedsOwner
from .context import Ctx
from .operation import entry


@entry("clear")
def clear(ctx: Ctx, kind: str, action: str) -> str:
    from ..llm import timeouts
    if kind == "unchecked":
        if action != "continue":
            return "Ellenőrizetlen oldal csak --continue paranccsal oldható fel."
        from . import unchecked
        pages = unchecked.reset(ctx)
        return f"ellenőrizetlen oldalak: a következő kör újraellenőrzi ({len(pages)} oldal várt rád)"
    if kind in timeouts.ROLES:
        if action != "continue":
            return "Időtúllépési szerep csak --continue paranccsal oldható fel."
        timeouts.clear(ctx, kind)
        if kind == "reviewer":
            from ..state.files import write_json
            write_json(ctx.cfg.state_dir / ctx.name / "nightly-cleared.json", {"at": now_iso()})
        task_kind = "review" if kind == "reviewer" else "notes"
        task = phase.open_task(ctx.task_root(), ctx.name, task_kind)
        # A writer's or a checking role's suspension stopped the notes run (fix-49), the
        # reviewer's the night: the run continues from its phase.
        stop = (task.data.get("needs_owner") or {}) if task is not None else {}
        if stop.get("class") == "timeout" and stop.get("role", "reviewer" if kind == "reviewer" else "writer") == kind:
            incidents.resolve(ctx, "task:" + task.run_id)
            task.clear_needs_owner()
            task.update(blocked_topics=[], timeout_day=None)
        return f"{kind}: az időtúllépési felfüggesztés feloldva"
    task = phase.open_task(ctx.task_root(), ctx.name, kind)
    if task is None:
        return f"nincs nyitott {kind} futás"
    if action == "continue":
        if kind == "notes" and (task.get("rebase") == "conflict" or task.get("question")):
            return "kérdés vagy tartalmi ütközés: csak `school-notes chat`-ben folytatható"
        if task.get("stuck"):
            # The owner raised the reviewer timeout: the marker closes, next night retries.
            task.data["data"].update(closure_reason="retry_nightly", ended_at=now_iso())
            task.data["closed"] = True
            incidents.resolve(ctx, "task:" + task.run_id)
            task.clear_needs_owner()
            return f"{task.run_id}: a következő éjszaka újra próbálja (emelt időkorláttal)"
        incidents.resolve(ctx, "task:" + task.run_id)
        task.clear_needs_owner()
        return f"{task.run_id}: folytatható a(z) {task.phase} fázistól"
    lock = ctx.lock()
    lock.acquire("discard", on_wait=lambda h: print(f"várok a zárra ({h.get('kind')})…"))
    try:
        discard(ctx, task)
    finally:
        lock.release()
    return f"{task.run_id}: eldobva"


def discard(ctx: Ctx, task: phase.Task) -> None:
    """Notes: bundle, reset; review: close the stuck commit as not reviewed; publish: close."""
    if task.kind == "notes":
        bundle = git_discard.discard(ctx.worktree("notes"), task.run_id,
                                     ctx.cfg.root / "archive" / ctx.name)
        task.update(bundle=str(bundle) if bundle else task.get("bundle"))
    elif task.kind == "review" and task.get("stuck"):
        role, _ = ctx.cfg.role("reviewer")
        ident = review_close.Identity(ctx.name, f"{role.model}/{role.effort}", VERSION, today(),
                                      now_iso())
        task.set_phase("closing")
        review_close.discard_timeout(task, ctx.bare(), ctx.worktree("review"), ident,
                                     task.get("commits")[0])
    elif task.kind == "review" and task.phase not in ("prepared", "reviewing"):
        raise NeedsOwner("a reviewed range is being closed; it cannot be discarded",
                         todo="`--continue` instead")
    incidents.resolve(ctx, "task:" + task.run_id)
    task.data["data"].update(closure_reason="discarded", ended_at=now_iso())
    task.data["closed"] = True
    task.data["needs_owner"] = None
    task.save()
