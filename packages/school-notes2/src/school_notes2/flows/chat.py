"""`school-notes chat <learner> [codex|claude]` (plan 5.8): the owner's session.

The launcher runs on the host: it takes the lock (waiting if needed), lets the owner settle
a stopped run in the terminal, prepares a run, and starts the same container and MCP as
cron with the interactive template. The LLM starts `fetch`/`finish` itself through MCP."""

import sys

from ..llm import launch
from ..mcp.redact import redact
from ..schemas import errors as schema_errors
from ..state import phase
from ..state.errors import NeedsOwner, SnError, Transient, WaitingQuota
from ..state import safefs
from ..state.files import write_json
from . import checks, clear, fetch as fetch_flow
from . import finish as finish_flow
from . import handlers, policy, run as run_flow, setup, steps, writer
from .context import Ctx
from .operation import entry
from .session import mcp


@entry("chat")
def chat(ctx: Ctx, harness_name: str | None, ask=input, say=print) -> int:
    lock = ctx.lock()
    lock.acquire("chat", on_wait=lambda h: say(f"A zárat {h.get('kind')} tartja "
                                               f"{h.get('since')} óta; várok… (Ctrl-C: kilépés)"))
    task = None
    try:
        setup.ensure(ctx)
        task = phase.open_task(ctx.task_root(), ctx.name, "notes")
        if task is not None and not _settle(ctx, task, ask, say):
            return 0
        task = phase.open_task(ctx.task_root(), ctx.name, "notes") or interactive_fetch(ctx)
        try:
            _launch(ctx, task, harness_name)
        finally:
            if task.get("question"):     # also after Ctrl-C or a failed launch (5.3)
                _after_question_session(ctx, phase.load(task.dir))
        return 0
    except Exception as exc:  # noqa: BLE001 - one error policy for every entry point (8)
        fresh = phase.load(task.dir) if task is not None else None   # jobs may have written
        policy.on_error(exc, task=fresh, student=ctx.name, step="chat", log=ctx.log,
                        mailer=None, interactive=True)
        say(f"Hiba: {exc}")
        return 1
    finally:
        lock.release()


def _settle(ctx: Ctx, task: phase.Task, ask, say) -> bool:
    """A stopped or cron run: the owner decides here, outside the container (5.8).

    The stop is cleared only after the owner confirmed what happens next, so a declined
    take-over leaves a conflict or a question with the owner, never with cron."""
    stop = task.data.get("needs_owner")
    if stop:
        say(f"A futás ({task.run_id}) áll: {stop['reason']}\nTeendő: {stop['todo']}")
        if task.get("conflict_files"):
            say("Ütköző fájlok: " + ", ".join(task.get("conflict_files")))
        for q in task.get("question") or []:
            say(f"Kérdés: {q.get('text')}")
        choice = ask("[f]olytatás, [e]ldobás vagy [k]ilépés? ").strip().lower()
        if choice.startswith("e"):
            clear.discard(ctx, task)
            return True
        if not choice.startswith("f"):
            return False
    if task.get("question"):
        # 5.3: the session answers the question for range k; the run stays a cron run.
        task.clear_needs_owner()
        return True
    if task.mode == "cron":
        if not ask(f"Nyitott automatikus futás ({task.run_id}, {task.phase}). Átveszed? [i/n] "
                   ).strip().lower().startswith("i"):
            return False
        task.data["mode"] = "interactive"
    if stop:
        task.clear_needs_owner()
    task.save()
    return True


def interactive_fetch(ctx: Ctx) -> phase.Task:
    """A run for the session: ready packages, or none (repairs and free editing, 5.2)."""
    drive = _drive_or_none(ctx)
    task = fetch_flow.start(ctx, "interactive", drive)
    run_flow.ctx_bind(ctx, task)
    fetch_flow.advance(ctx, task, lambda: drive)
    return task


def _drive_or_none(ctx: Ctx):
    try:
        return fetch_flow.drive_client(ctx)
    except SnError as exc:
        ctx.log.event("drive.client", "offline", message=str(exc)[:200])
        return None


def _launch(ctx: Ctx, task: phase.Task, harness_name: str | None) -> None:
    role, harness = _role_for(ctx, harness_name)
    if task.phase == "waiting_quota":
        task.set_phase(task.get("quota_phase"))
    if task.phase in ("downloading", "downloaded", "moved"):
        if task.get("mode") == "repair":
            from . import repair
            repair.prepare(ctx, task)
        else:
            fetch_flow.advance(ctx, task, lambda: _drive_or_none(ctx))
    n = len(task.get("ranges"))
    k = min(task.get("writing_k", 1), n)
    if task.phase == "prepared":
        task.set_phase("writing", writing_k=k)
    from . import correction_chat
    if not correction_chat.resume_inputs(ctx, task):
        writer.write_inputs(ctx, task, k)
    h = handlers.build(ctx, None, fetch=lambda: session_fetch(ctx),
                       finish=lambda: session_finish(ctx))
    print(f"Munkamappa: {ctx.notes_path}  (futás: {task.run_id})", file=sys.stderr)
    checks.begin(task)
    with mcp(ctx, task.dir, "interactive", h, lambda: _current_run(ctx)) as sessdir:
        launch.run_interactive(learner=ctx.name, run_id=task.run_id, role=role, harness=harness,
                               image=ctx.image_tag(),
                               mounts=launch.Mounts(work=ctx.notes_path, sessdir=sessdir),
                               log=ctx.log, allowed_domains=ctx.cfg.provider_domains, max_agents=ctx.cfg.limits.max_agents,
                           lease_dir=ctx.cfg.state_dir / "agent-leases")


def _role_for(ctx: Ctx, harness_name: str | None):
    """The writer's role, or – for the other harness – the model of the role that already
    uses that harness family (Claude Code in a session runs the reviewer's model)."""
    role, harness = ctx.cfg.role("writer")
    if not harness_name or harness_name == harness.name:
        return role, harness
    for other in ctx.cfg.roles.values():
        if other.harness.split("-")[0] == harness_name:
            return other, ctx.cfg.harnesses[harness_name]
    raise NeedsOwner(f"no role uses the {harness_name} harness", todo="see config.toml [roles]")


def _current_run(ctx: Ctx) -> str:
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    return task.run_id if task else ""


def _after_question_session(ctx: Ctx, task: phase.Task) -> None:
    """5.3: the session's result.json replaces result-<k>; cron goes on with range k+1.
    A question the session did not settle goes back to the owner."""
    try:
        saved = save_session_result(ctx, task) if task.get("question") else True
    except steps.CheckFailed:
        task.mark_needs_owner("the session result lacks warning decisions",
                              f"complete it in `school-notes chat {ctx.name}`", "needs_owner")
        return
    if not saved:
        task.mark_needs_owner("the blocking question is still open",
                              f"answer it in `school-notes chat {ctx.name}`", "needs_owner")


def save_session_result(ctx: Ctx, task: phase.Task) -> bool:
    """Store a valid `done` result.json of a question session as result-<k>, once.

    For an earlier range the file is removed, so a second call (MCP finish, then the end
    of the session) cannot store it again as range k+1. For the last range the run becomes
    interactive: the session finishes it and keeps correcting its own result.json."""
    task = phase.load(task.dir)
    if not task.get("question"):
        return False
    own = safefs.read_json(ctx.notes_path, ".school-notes/result.json")
    if own is None or schema_errors("result", own) or own.get("status") != "done":
        return False
    problems = checks.accounting(task, own)
    if problems:
        steps.write_check_items(ctx, problems)
        raise steps.CheckFailed(problems)
    n = len(task.get("ranges"))
    k = min(task.get("writing_k", 1), n)
    write_json(task.dir / f"result-{k}.json", own)
    if k < n:
        safefs.unlink(ctx.notes_path, ".school-notes/result.json")
    else:
        task.data["mode"] = "interactive"
    task.update(writing_k=k + 1, question=None)
    return True


def session_fetch(ctx: Ctx) -> dict:
    """MCP `fetch` in a session: continue an unfinished run, or start a new one (5.8)."""
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    if task is None:
        task = interactive_fetch(ctx)
        checks.begin(task)
    elif task.phase in ("downloading", "downloaded", "moved"):
        if task.get("mode") == "repair":
            from . import repair
            repair.prepare(ctx, task)
        else:
            fetch_flow.advance(ctx, task, lambda: _drive_or_none(ctx))
    from . import correction_chat
    if not correction_chat.resume_inputs(ctx, task):
        writer.write_inputs(ctx, task, min(task.get("writing_k", 1), len(task.get("ranges"))))
    supplied = correction_chat.active(task) or task
    return {"run_id": task.run_id, "phase": task.phase, "pages": len(supplied.get("pages", [])),
            "open_review_items": len(supplied.get("open_review_items", []))}


def session_finish(ctx: Ctx) -> dict:
    """MCP `finish`: the same function as cron; problems go back to the session."""
    task = phase.open_task(ctx.task_root(), ctx.name, "notes")
    if task is None:
        raise NeedsOwner("there is no open run to finish", todo="call fetch first")
    if task.phase == "waiting_quota":
        task.set_phase(task.get("quota_phase"))
    ctx.lock().note("finish")       # this detached job holds the inherited lock (7.8)
    n = len(task.get("ranges"))
    if (task.mode == "cron" and not task.get("skip_writer") and not task.get("question")
            and task.get("writing_k", 1) <= n):
        return {"state": "saved", "message": "the remaining ranges continue in cron"}
    try:
        if task.get("question"):
            if not save_session_result(ctx, task):
                return {"state": "question_open", "message": "write a result.json with status done"}
            task = phase.load(task.dir)
            if task.get("writing_k") <= len(task.get("ranges")):
                return {"state": "saved", "message": "the remaining ranges continue in cron"}
        if task.get("no_push"):
            task.update(no_push=False)
        state = finish_flow.finish(ctx, task, notify_owner_items=lambda items: run_flow.owner_items(
            ctx, task, items))
    except (WaitingQuota, launch.TimedOut) as exc:
        policy.on_error(exc, task=task, student=ctx.name, step="finish", log=ctx.log,
                        mailer=ctx.mailer, interactive=True)
        return {"state": exc.kind, "message": str(exc), "phase": task.phase}
    except steps.CheckFailed as exc:
        steps.write_check_items(ctx, exc.items)
        task.set_phase("writing", review_complete=False, attempt=task.get("attempt", 1) + 1)
        return {"state": "check_failed", **checks.response(exc.items)}
    except finish_flow.git_finish.EditedDuringFinish:
        return {"state": "edited", "message": "files changed during finish; call finish again"}
    except Transient as exc:
        task.record_error("transient", str(exc))
        return {"state": "transient_error", "message": str(exc)}
    if isinstance(state, dict):
        return {**state, "run_id": task.run_id}
    return {"state": state, "run_id": task.run_id, "published": task.get("published"),
            **({"correction_rolled_back": True, "reason": task.get("correction_rollback_reason"),
                "items": task.get("correction_rollback_items", []),
                "rejected_patch": task.get("correction_rejected_patch")}
               if task.get("correction_rolled_back") else {}),
            "owner_notes": redact(writer.merge(writer.results(task, required=False))["owner_notes"])}
