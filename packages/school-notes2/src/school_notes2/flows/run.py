"""`school-notes run <learner>` (plan 5.1): the hourly cron entry point."""

from datetime import datetime

from ..git import workbranch
from ..images import generate as image_generate
from ..images import pending as image_pending
from ..images import plans as image_plans
from ..llm import launch
from ..log import TZ
from ..notify import Notice
from ..notify import pending as owner_notices
from ..state import phase
from ..state.errors import NeedsOwner, Prerequisite
from ..state.phase import Task
from . import fetch as fetch_flow
from . import finish as finish_flow
from . import handlers, policy, prereq, publish, setup, writer
from .context import Ctx
from .operation import entry


@entry("run")
def run(ctx: Ctx) -> int:
    lock = ctx.lock()
    if not lock.try_acquire("run"):
        ctx.log.event("run.skip", "locked", target=str(lock.holder()))
        _lock_alert(ctx, lock.holder())
        return 0
    task = None
    try:
        setup.ensure(ctx)
        owner_notices.retry(ctx)
        _settle_images(ctx)
        task = phase.open_task(ctx.task_root(), ctx.name, "notes")
        from . import last_error
        from ..state.files import read_json
        previous = read_json(ctx.cfg.state_dir / ctx.name / "last-error.json", {})
        recheck = previous.get("step") == "run" and previous.get("class") == "prerequisite"
        if recheck:
            _prerequisites(ctx, task)
            last_error.clear(ctx, "run")
        if not _may_run(ctx, task):
            if task is not None and task.get("no_push"):
                return 0
            publish.catch_up(ctx)        # 8.3: the kinds are independent
            return 0
        if not recheck:
            _prerequisites(ctx, task)
        if task is None:
            task = _new_task(ctx)
        last_error.clear(ctx, "run")  # Prerequisites and Drive listing succeeded, even without new work.
        if task is None:
            publish.catch_up(ctx)
            return 0
        task = ctx_bind(ctx, task)
        advance(ctx, task)
        policy.on_success(task)
        image_notices(ctx)
        return 0
    except Exception as exc:  # noqa: BLE001 - every error has one documented outcome (8.1)
        from ..repair import failure
        if failure.handle(ctx, task, exc):
            return 1
        policy.on_error(exc, task=task, student=ctx.name, step="run", log=ctx.log,
                        mailer=ctx.mailer)
        return 1
    finally:
        lock.release()


def ctx_bind(ctx: Ctx, task: Task) -> Task:
    ctx.log = ctx.log.bind(run_id=task.run_id, run_log=task.dir / "run.log")
    return task


def _may_run(ctx: Ctx, task: Task | None) -> bool:
    """5.1/1–2: needs-owner, an open interactive run, or stray edits keep cron away."""
    if task is not None and task.get("no_push"):
        _daily(ctx, "no_push", task.run_id, f"Visszatartott próba; fázis: {task.phase}. A cron vár.",
               f"Nézd meg, majd school-notes finish {ctx.name}; vagy status --clear {ctx.name} notes --discard.")
        return False
    from . import transient_retry
    if not transient_retry.resume(task):
        ctx.log.event("run.skip", "transient_wait", target=task.run_id)
        return False
    if task is not None and task.data.get("needs_owner"):
        owner = task.data["needs_owner"]
        if owner["class"] == "program" and owner.get("release") != policy.release(ctx):
            task.clear_needs_owner()
    if task is not None and task.data.get("needs_owner"):
        ctx.log.event("run.skip", "needs_owner", target=task.run_id)
        return False
    if task is not None and task.mode == "interactive":
        _daily(ctx, "interactive_open", task.run_id, "an interactive run was left without finish",
               "finish or discard it in `school-notes chat`")
        return False
    if task is None and workbranch.worktree_dirty(ctx.worktree("notes")):
        _daily(ctx, "worktree_dirty", "", "the notes worktree has changes outside any run",
               "take them over or discard them in `school-notes chat`")
        return False
    return True


def _prerequisites(ctx: Ctx, task: Task | None) -> None:
    prereq.disk(ctx.cfg.root, ctx.cfg.limits.min_free_gb)
    prereq.podman()
    role, harness = ctx.cfg.role("writer")
    if not launch.login_ok(learner=ctx.name, run_id=task.run_id if task else "", role="writer",
                           harness=harness, image=ctx.image_tag(), log=ctx.log,
                           allowed_domains=ctx.cfg.provider_domains, max_agents=ctx.cfg.limits.max_agents,
                           lease_dir=ctx.cfg.state_dir / "agent-leases"):
        raise Prerequisite(f"the {harness.name} login in the container expired",
                           todo=f"log in once: `school-notes login {ctx.name} writer`")


def _new_task(ctx: Ctx) -> Task | None:
    drive = fetch_flow.drive_client(ctx)
    task = fetch_flow.start(ctx, "cron", drive)
    if task is None:
        from . import fix
        task = fix.next_task(ctx)
    if task is None:
        from . import repair
        task = repair.next_task(ctx)
    return task


def advance(ctx: Ctx, task: Task) -> None:
    """Drive a cron notes task from its recorded phase to `done` (8.2)."""
    from ..figures import licenses
    licenses.preflight(ctx.notes_path)
    if task.phase == "waiting_quota":
        task.set_phase(task.get("quota_phase"))
    if task.phase in ("correcting", "rechecking"):
        # 2.5.x in-run correction rounds no longer exist: their files stay and every
        # change of the run is rechecked once; open items wait for the next run.
        task.set_phase("inspecting", recheck_all=True)
    if task.get("mode") == "fix":
        from . import fix
        fix.prepare(ctx, task)
    elif task.get("mode") == "repair":
        from . import repair
        repair.prepare(ctx, task)
    else:
        fetch_flow.advance(ctx, task, lambda: fetch_flow.drive_client(ctx))
    if task.phase in ("prepared", "writing") and not task.get("skip_writer"):
        if writer.run_ranges(ctx, task, handlers.build(ctx, task.dir)) == "question":
            raise NeedsOwner("the writer asked a blocking question",
                             todo=f"answer it in `school-notes chat {ctx.name}`",
                             details={"questions": task.get("question", [])})
    finish_flow.finish(ctx, task, notify_owner_items=lambda items: owner_items(ctx, task, items))


def owner_items(ctx: Ctx, task: Task, items: list[dict]) -> bool:
    """Drain owner notices through the suppression gate, including legacy tasks."""
    delivered = True
    for item in sorted(items, key=lambda i: (i["file"], i["item_id"])):
        sent = owner_notices.send(ctx, Notice(ctx.name, f"review_owner:{item['file']}:{item['item_id']}",
                               task.run_id, "finish", "owner", f"{item['file']} {item['item_id']}: "
                               + item.get("reason", "stayed open five times"),
                               "settle it in `school-notes chat`"))
        if not sent:
            delivered = False
    return delivered


def image_notices(ctx: Ctx) -> None:
    from . import image_notices as notices
    notices.threshold(ctx)


def _settle_images(ctx: Ctx) -> None:
    for settled in image_generate.settle_unknown(ctx.image_settings(), log=ctx.log):
        ctx.mailer.send(Notice(ctx.name, f"image_settled:{settled.get('job', '')}", "",
                               "images", "image", "an unknown-outcome image call was settled "
                               "after 24 hours (booked as spent)", "nothing to do"))


def _lock_alert(ctx: Ctx, holder: dict) -> None:
    """7.8: a long-held lock stops automatic processing; one e-mail a day."""
    since = holder.get("since")
    if not since:
        return
    age_h = (datetime.now(TZ) - datetime.fromisoformat(since)).total_seconds() / 3600
    limit = ctx.cfg.limits.chat_lock_alert_h if holder.get("kind") == "chat" else _other_limit_h(ctx)
    if age_h > limit:
        _daily(ctx, "lock_held", "", f"the lock is held by {holder.get('kind')} for {age_h:.1f} h",
               "check the session or process holding it")


def _other_limit_h(ctx: Ctx) -> float:
    """The sum of the step time limits of a big run plus one hour (7.8)."""
    t = ctx.cfg.timeouts
    role, _ = ctx.cfg.role("writer")
    seconds = 3 * role.timeout_s + t.build_s + t.browser_check_s + t.push_s + t.fetch_s
    return seconds / 3600 + 1


def _daily(ctx: Ctx, kind: str, run_id: str, message: str, todo: str) -> None:
    ctx.log.event("run.skip", kind, target=run_id)
    if kind == "lock_held":
        from . import last_error
        last_error.record(ctx, "run", kind)
    else:
        ctx.mailer.send(Notice(ctx.name, kind, run_id, "run", "stopped", message, todo))
