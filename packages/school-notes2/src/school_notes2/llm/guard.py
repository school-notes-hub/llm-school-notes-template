"""Quota admission and T-125 accounting around a single role call."""

from dataclasses import replace

from ..state.errors import WaitingQuota


CHECKING = ("reader-1", "recheck", "figure-review")


def headless(run, invoke):
    from ..flows.operation import CURRENT
    from . import quota, timeouts
    from .launch import TimedOut
    run = replace(run, role=run.role.for_stage(run.role_name))
    current = CURRENT.get()
    if current:
        ctx, manual, cache = current
        configured = ctx.cfg.roles.get(timeouts.role_name(run.role_name))
        if run.role_name in ("reader-1", "recheck") and "reviewer" in ctx.cfg.roles:
            configured, _ = ctx.cfg.role("reader")
        if configured and run.role_name not in ("writer", "fix", "reviewer"):
            run = replace(run, role=configured.for_stage(run.role_name), harness=ctx.cfg.harnesses[configured.harness])
        if timeouts.blocked(ctx, run):
            timeouts.stopped(ctx, run)
            if run.role_name in CHECKING:
                raise _suspended(run)
            raise TimedOut("A szerep tulajdonosi döntésre vár.", details={"suspended": True})
        quota.check(ctx, run, manual, cache)
    try:
        outcome = invoke(run)
    except WaitingQuota:
        if current:
            quota.wait(ctx, run, cache)
        raise
    except TimedOut as exc:
        if current:
            exc.details["count"] = timeouts.record(ctx, run)
            if exc.details["count"] >= 2 and run.role_name in CHECKING:
                raise _suspended(run) from exc
        raise
    if current:
        timeouts.success(ctx, run)
    return outcome


def _suspended(run):
    from . import timeouts
    from .launch import Suspended
    role = timeouts.role_name(run.role_name)
    return Suspended(f"two timeouts in a row: the {role} role is suspended",
                     todo=f"raise its time limit, then school-notes status --clear {run.learner} {role} --continue",
                     details={"suspended": True, "role": role})


def interactive(kwargs, invoke):
    from .launch import RoleRun, DEFAULT_PROVIDER_DOMAINS
    from ..flows.operation import CURRENT
    from . import quota
    current = CURRENT.get()
    if current:
        ctx, manual, cache = current
        run = RoleRun(ctx.name, kwargs["run_id"], "writer", kwargs["role"], kwargs["harness"],
                      kwargs["image"], kwargs["mounts"], ctx.notes_path / ".school-notes/result.json",
                      "result", ctx.cfg.root / "tasks" / ctx.name / kwargs["run_id"], ctx.student.grade,
                      allowed_domains=kwargs.get("allowed_domains", DEFAULT_PROVIDER_DOMAINS),
                      max_agents=kwargs.get("max_agents", ctx.cfg.limits.max_agents))
        quota.check(ctx, run, manual, cache)
    try:
        return invoke(**kwargs)
    except WaitingQuota:
        if current:
            quota.wait(ctx, run, cache)
        raise
