"""Release without a notes run (plan 5.10, 5.1/6): when origin/main changed in what goes
out (e.g. the owner pushed from the laptop) or the tool version changed."""

from pathlib import Path

from .. import VERSION
from ..git import repos
from ..git.run import with_retries
from ..site import build as site_build
from ..site import publish as site_publish
from ..state import phase
from ..state.files import read_json, write_json
from . import finish as finish_flow
from . import policy
from .context import Ctx


def catch_up(ctx: Ctx) -> None:
    """Build and release origin/main in a `kind: publish` task when it is behind."""
    if not ctx.student.publish:
        return
    task = phase.open_task(ctx.task_root(), ctx.name, "publish")
    if task is not None and task.data.get("needs_owner"):
        return
    try:
        if task is not None and _stale(ctx, task):
            task.data["closed"] = True
            task.save()
            task = None
        if task is None:
            task = _start(ctx)
            if task is None:
                return
        _advance(ctx, task)
        policy.on_success(task)
    except Exception as exc:  # noqa: BLE001 - a release error never stops the notes runs
        policy.on_error(exc, task=task, student=ctx.name, step="publish", log=ctx.log,
                        mailer=ctx.mailer)


def _stale(ctx: Ctx, task) -> bool:
    """A half-done release of an older origin/main must not overwrite a newer one."""
    with_retries(lambda: repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s), log=ctx.log)
    return task.get("source") != repos.rev(ctx.bare(), "refs/remotes/origin/main")


def _start(ctx: Ctx):
    bare, site = ctx.bare(), ctx.worktree("site")
    with_retries(lambda: repos.fetch(bare, ctx.cfg.timeouts.fetch_s), log=ctx.log)
    site_publish.fetch_gh_pages(site, ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                                ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
    main = repos.rev(bare, "refs/remotes/origin/main")
    from . import unchecked
    if unchecked.load(ctx):
        ctx.log.event("site.publish_held", "warning", target=main, reason="unchecked")
        return None  # An unchecked change never goes out; the next run rechecks it.
    held = read_json(_held(ctx), {})
    if held.get("source") == main and held.get("reason") != "unchecked":
        return None  # This commit's build already failed on content; wait for a new one.
    needed, why = site_publish.publish_needed(bare, site, main, VERSION)
    ctx.log.event("site.publish_needed", "yes" if needed else "no", target=why)
    if not needed:
        return None
    task = phase.create(ctx.task_root(), ctx.name, "publish", "cron", "prepared")
    task.update(source=main, changed=site_publish.changed_since_publish(bare, site, main))
    return task


def _advance(ctx: Ctx, task) -> None:
    if task.phase == "prepared":
        try:
            record = site_build.build(ctx.bare(), task.get("source"), task.dir,
                                      finish_flow.renderer(ctx), changed=task.get("changed"),
                                      log=ctx.log)
        except site_build.BuildContentError as exc:
            # Publication waits; the notes run that pushed this commit recorded the
            # problems as items, and a later clean build publishes everything.
            ctx.log.event("site.publish_held", "warning", target=task.get("source"), problems=exc.problems[:20])
            hold(ctx, task.get("source"), "build")
            task.data["closed"] = True
            task.save()
            return
        task.set_phase("built", build={"commit": record.commit, "output": str(record.output)})
    if task.phase in ("built", "pushing"):
        task.set_phase("pushing")
        site = ctx.worktree("site")
        site_publish.fetch_gh_pages(site, ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                                    ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
        build = task.get("build")
        site_publish.publish(site, Path(build["output"]) / "site", student=ctx.name,
                             source_commit=build["commit"], run_id=task.run_id,
                             tool_version=VERSION, log=ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                             push_s=ctx.cfg.timeouts.push_s,
                             ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
        task.set_phase("done")
        released(ctx)
        finish_flow.check_live(ctx, Path(build["output"]), build["commit"])


def _held(ctx: Ctx):
    return ctx.cfg.state_dir / ctx.name / "publish-held.json"


def hold(ctx: Ctx, source: str, reason: str, *, notify: bool = True) -> None:
    """The release waits (`unchecked`, `build` or `public`); the notes commit is pushed anyway.
    `held` shows in the status; the owner gets one mail per held episode (`publish_held`)."""
    if not ctx.student.publish:
        return
    write_json(_held(ctx), {"source": source, "reason": reason})
    if notify:
        from ..notify import incidents
        incidents.record(ctx, "publish_held", reason, scope="publish-held")


def released(ctx: Ctx) -> None:
    """A publication went out: the held state and its incident end."""
    from ..notify import incidents
    _held(ctx).unlink(missing_ok=True)
    incidents.resolve(ctx, "publish-held")
