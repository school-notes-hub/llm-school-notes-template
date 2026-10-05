"""`school-notes nightly <learner>` (plan 5.6): one independent review of the day's commits."""

from .. import VERSION
from ..llm import launch
from ..log import now_iso, today
from ..review import close as review_close
from ..review import nightly as review
from ..state import phase, safefs
from ..state.errors import Prerequisite
from . import cleanup, policy, prereq, setup
from .context import Ctx
from .operation import entry


@entry("nightly")
def nightly(ctx: Ctx) -> int:
    lock = ctx.lock()
    if not lock.try_acquire("nightly"):
        ctx.log.event("nightly.skip", "locked", target=str(lock.holder()))
        return 0
    task = None
    original_log = ctx.log
    try:
        setup.ensure(ctx)
        tasks = [t for t in phase.all_tasks(ctx.task_root(), ctx.name) if t.kind == "review"]
        for previous in tasks:
            if previous.phase == "done":
                _notify_owners(ctx, previous)
        from . import transient_retry
        if any(t.open and not transient_retry.resume(t) for t in tasks):
            ctx.log.event("nightly.skip", "transient_wait")
            return 0
        if any(t.open and t.data.get("needs_owner") for t in tasks):
            ctx.log.event("nightly.skip", "needs_owner")
            return 0
        _retire_legacy(ctx, tasks)
        task = review.pending_close(tasks) or _unfinished(tasks)
        if task is None:
            task = review.prepare(ctx.task_root(), ctx.name, ctx.bare(), ctx.worktree("review"),
                                  fetch_timeout=ctx.cfg.timeouts.fetch_s, max_agents=ctx.cfg.limits.max_agents,
                                  log=ctx.log)
        if task is not None:
            ctx.log = ctx.log.bind(run_id=task.run_id)
            if task.get("max_agents") is None:
                task.update(max_agents=ctx.cfg.limits.max_agents)
            if task.phase == "waiting_quota":
                task.set_phase(task.get("quota_phase"))
            if task.phase in ("prepared", "reviewing"):
                _review(ctx, task)              # 8.2: the same range as recorded
            if task.phase in review.ACTIVE:
                _close(ctx, task)
            policy.on_success(task)
        cleanup.old_tasks(ctx)
        return 0
    except Exception as exc:  # noqa: BLE001 - one documented outcome per error (8.1)
        policy.on_error(exc, task=task, student=ctx.name, step="nightly", log=ctx.log,
                        mailer=ctx.mailer)
        return 1
    finally:
        ctx.log = original_log
        lock.release()


def _unfinished(tasks: list[phase.Task]):
    """An interrupted review (no review.json yet) resumes instead of a new one."""
    for task in tasks:
        if task.open and task.phase in ("prepared", "reviewing", "waiting_quota") and task.get("diff_review") \
                and not task.data.get("closed"):
            return task
    return None


def _retire_legacy(ctx: Ctx, tasks: list[phase.Task]) -> None:
    """A 2.5.x topic review is closed unapplied; the marker did not move, so the new diff
    review covers the same commits (only review output, never notes work, is redone)."""
    for task in tasks:
        if task.open and not task.get("diff_review"):
            ctx.log.event("nightly.legacy_retired", target=task.run_id, phase=task.phase)
            task.data["closed"] = True
            task.save()


def _prerequisites(ctx: Ctx) -> None:
    prereq.disk(ctx.cfg.root, ctx.cfg.limits.min_free_gb)
    prereq.podman()
    role, harness = ctx.cfg.role("reviewer")
    if not launch.login_ok(learner=ctx.name, run_id="", role="reviewer", harness=harness,
                           image=ctx.image_tag(), log=ctx.log,
                           allowed_domains=ctx.cfg.provider_domains, max_agents=ctx.cfg.limits.max_agents,
                           lease_dir=ctx.cfg.state_dir / "agent-leases"):
        raise Prerequisite(f"the {harness.name} login in the container expired",
                           todo=f"log in once: `school-notes login {ctx.name} reviewer`")


def _review(ctx: Ctx, task: phase.Task) -> None:
    from ..review import call
    if not task.get("input_ready"):
        review.write_input(task, ctx.bare(), ctx.worktree("review"))
    ctx.worktree("review").run("switch", "--detach", "--discard-changes", task.get("H"))
    _prerequisites(ctx)
    task.set_phase("reviewing")
    configured, harness = ctx.cfg.role("reviewer")
    run = launch.RoleRun(ctx.name, task.run_id, "reviewer", configured, harness, ctx.image_tag(),
                         launch.Mounts(), task.dir / "out/review.json", "nightly", task.dir,
                         grade=ctx.student.grade, label="diff", allowed_domains=ctx.cfg.provider_domains,
                         max_agents=task.get("max_agents", ctx.cfg.limits.max_agents),
                         lease_dir=ctx.cfg.state_dir / "agent-leases")
    work = ctx.worktree("review").work_tree
    receipt = call.run(work, task.dir, {"items": task.get("items", [])}, run, log=ctx.log)
    if receipt["status"] != "reviewed":
        # The marker stays: the next night reviews the same (larger) range.
        ctx.log.event("nightly.failed", "error", reason=receipt.get("reason", ""))
        if receipt.get("timeout_count", 0) >= 2:
            task.mark_needs_owner("Két egymás utáni éjszakai időtúllépés.",
                                  f"Állítsd be az időkorlátot; school-notes status --clear {ctx.name} reviewer --continue",
                                  "timeout")
            return
        task.data["closed"] = True
        task.save()
        return
    findings, notes = review.triage(receipt["review"], safefs.read_text(task.dir, "in/diff.patch"), work)
    safefs.write_json(task.dir, "review.json", {"findings": findings, "owner_notes": notes,
                                                "items": receipt["review"]["items"]})
    task.set_phase("reviewed")


def _notify_owners(ctx: Ctx, task: phase.Task) -> None:
    from .run import owner_items
    if task.get("notify_owner_items") and not task.get("owners_notified"):
        if owner_items(ctx, task, task.get("notify_owner_items")):
            task.update(owners_notified=True)


def _close(ctx: Ctx, task: phase.Task) -> None:
    role, _ = ctx.cfg.role("reviewer")
    ident = review_close.Identity(ctx.name, f"{role.model}/{role.effort}", VERSION, today(),
                                  now_iso())
    t = review_close.Timeouts(ctx.cfg.timeouts.fetch_s, ctx.cfg.timeouts.push_s,
                              ctx.cfg.timeouts.ls_remote_s)
    review_close.close(task, ctx.bare(), ctx.worktree("review"), ident, t)
    _notify_owners(ctx, task)
