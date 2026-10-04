"""`school-notes nightly <learner>` (plan 5.6): one independent review of the day's commits."""

from pathlib import Path

from .. import VERSION
from ..llm import launch
from ..log import now_iso, today
from ..review import close as review_close
from ..review import nightly as review
from ..state import phase
from ..state.errors import Prerequisite
from . import cleanup, policy, prereq, setup
from .context import Ctx
from .operation import entry

RASTERIZE = ["bash", "-c", 'for f in /in/*.svg; do rsvg-convert -o "/out/$(basename "${f%.svg}").png" "$f"'
             ' || exit 1; done']


@entry("nightly")
def nightly(ctx: Ctx) -> int:
    lock = ctx.lock()
    if not lock.try_acquire("nightly"):
        ctx.log.event("nightly.skip", "locked", target=str(lock.holder()))
        return 0
    task = None
    try:
        setup.ensure(ctx)
        tasks = [t for t in phase.all_tasks(ctx.task_root(), ctx.name) if t.kind == "review"]
        for previous in tasks:
            if previous.phase == "done":
                _notify_owners(ctx, previous)
        if any(t.open and t.data.get("needs_owner") for t in tasks):
            ctx.log.event("nightly.skip", "needs_owner")
            return 0
        task = review.pending_close(tasks) or _unfinished(tasks)
        if task is None:
            task = _prepare(ctx, tasks)
        if task is not None:
            if task.get("max_agents") is None:
                task.update(max_agents=ctx.cfg.limits.max_agents)
            if task.phase == "waiting_quota":
                task.set_phase(task.get("quota_phase"))
            if task.phase in ("prepared", "reviewing"):
                _review(ctx, task)              # 8.2: the same H/T as recorded
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
        lock.release()


def _unfinished(tasks: list[phase.Task]):
    """An interrupted review (no review.json yet) resumes instead of a new one."""
    for task in tasks:
        if task.open and task.phase in ("prepared", "reviewing", "waiting_quota") and not task.get("stuck") \
                and not task.data.get("closed"):
            return task
    return None


def _prepare(ctx: Ctx, tasks: list[phase.Task]):
    return review.prepare(ctx.task_root(), ctx.name, ctx.bare(), ctx.worktree("review"),
                          fetch_timeout=ctx.cfg.timeouts.fetch_s, max_agents=ctx.cfg.limits.max_agents,
                          rasterize=lambda svgs, out: _rasterize(ctx, svgs, out))


def _rasterize(ctx: Ctx, svgs: list[Path], out_dir: Path) -> list[Path]:
    """5.6/3: an LLM-written SVG is rendered in a container without network or host files."""
    rc = launch.run_offline(learner=ctx.name, run_id="raster", image=ctx.image_tag(),
                            in_dir=svgs[0].parent, out_dir=out_dir, command=RASTERIZE,
                            log=ctx.log, timeout=ctx.cfg.timeouts.rasterize_s)
    if rc != 0:
        ctx.log.event("review.rasterize", "error", rc=rc)
    return [out_dir / f"{s.stem}.png" for s in svgs if (out_dir / f"{s.stem}.png").is_file()]


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
    if task.get("units") != []:
        _prerequisites(ctx)
    review.resume_prepared(task, ctx.bare(), ctx.worktree("review"),
                           lambda svgs, out: _rasterize(ctx, svgs, out))
    if task.get("topic_review"):
        from . import night_topics
        night_topics.run(ctx, task)
        return
    role, harness = ctx.cfg.role("reviewer")
    out = task.dir / "out"
    out.mkdir(exist_ok=True)
    task.set_phase("reviewing")
    run = launch.RoleRun(
        learner=ctx.name, run_id=task.run_id, role_name="reviewer", role=role, harness=harness,
        image=ctx.image_tag(),
        mounts=launch.Mounts(work=ctx.cfg.worktree(ctx.name, "review"), work_readonly=True,
                             in_dir=task.dir / "in", out_dir=out),
        output_host=out / "review.json", schema="review", task_dir=task.dir, grade=ctx.student.grade,
        label=task.get("T", task.run_id),
        allowed_domains=ctx.cfg.provider_domains,
        max_agents=task.get("max_agents", ctx.cfg.limits.max_agents), lease_dir=ctx.cfg.state_dir / "agent-leases")
    try:
        outcome = launch.run_headless(run, log=ctx.log,
                                      snapshot=lambda: launch.tree_fingerprint(out))
    except launch.TimedOut as exc:
        task.update(timeout_day=today())
        if exc.details.get("count", 0) >= 2 or exc.details.get("suspended"):
            task.update(blocked_topics=[task.get("T")])
            task.mark_needs_owner("Két egymás utáni éjszakai időtúllépés.",
                                  f"Állítsd be az időkorlátot; school-notes status --clear {ctx.name} reviewer --continue",
                                  "timeout")
        return
    review.record_review(task, outcome.output, ctx.cfg.worktree(ctx.name, "review"))
    if task.get("dropped_responses"):
        ctx.log.event("review.dropped_responses", items=task.get("dropped_responses"))


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
