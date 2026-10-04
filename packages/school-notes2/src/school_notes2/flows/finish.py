"""`finish` (plan 5.4): content steps 1–9, then the Git order G0–G9 with the site hooks."""

import re
from pathlib import Path

from .. import VERSION
from ..git import finish as git_finish
from ..git import workbranch
from ..site import build as site_build
from ..site import publish as site_publish
from ..state.errors import NeedsOwner, SnError
from ..state.phase import Task
from ..wiki import markers
from . import checks, steps
from .context import Ctx

LOG_LINE = re.compile(r"^\s*[*-]\s+(?:\*\*[^*]+\*\*:\s*)?(.*)$")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def finish(ctx: Ctx, task: Task, *, notify_owner_items) -> str:
    """Run a notes task from `finishing` (or a later Git phase) to `done`.

    Raises steps.CheckFailed (the writer must fix check.json), NeedsOwner, Transient."""
    wt = ctx.worktree("notes")
    start = None
    if task.phase in ("prepared", "writing", "finishing"):
        task.set_phase("finishing")
        start = _snapshot(ctx, task)
        prepared = steps.content_steps(ctx, task)
        notify_owner_items(prepared.new_owner)
        if prepared.question:
            raise NeedsOwner("the writer asked a blocking question",
                             todo="answer it in `school-notes chat`",
                             details={"questions": prepared.result.get("questions", [])})
    elif task.get("rebase") == "conflict":
        steps.content_steps(ctx, task)          # 6.7: the owner resolved it; check again
    hooks = git_finish.Hooks(
        regenerate=lambda: steps.regenerate(ctx, task),
        build=lambda commit: _build(ctx, task, commit),
        publish=lambda record: _publish(ctx, task, record),
        message=lambda: message(ctx, task),
        snapshot=lambda: _snapshot(ctx, task),
        empty_blocks=markers.empty_all,
        rerecord=lambda paths: steps.rerecord(ctx, task, paths),
        extra_paths=("references",) if task.mode == "interactive" else ())
    t = git_finish.Timeouts(ctx.cfg.timeouts.fetch_s, ctx.cfg.timeouts.push_s,
                            ctx.cfg.timeouts.ls_remote_s)
    return git_finish.run(task, wt, hooks, t, start if start is not None else hooks.snapshot())


def _snapshot(ctx: Ctx, task: Task) -> dict:
    """5.4/9 guards against a session editing during finish; cron has no session."""
    return steps.llm_snapshot(ctx, task) if task.mode == "interactive" else {}


def renderer(ctx: Ctx) -> site_build.Renderer:
    t = ctx.cfg.timeouts
    return site_build.Renderer(
        study_site=ctx.release() / "packages" / "study-site", browser=ctx.cfg.browser,
        pdf_cache=ctx.cfg.state_dir / "pdf-cache" / ctx.name, build_s=t.build_s,
        browser_check_s=t.browser_check_s, check_public_s=t.check_public_s)


def _build(ctx: Ctx, task: Task, commit: str) -> dict:
    """G5. A content error goes back to the writer through check.json (8.1 bad work)."""
    site = ctx.worktree("site")
    try:
        site_publish.fetch_gh_pages(site, ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                                    ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
        changed = site_publish.changed_since_publish(ctx.bare(), site, commit)
    except SnError as exc:      # the site repo's trouble never stops the notes run (5.10)
        ctx.log.event("site.changed_since_publish", "error", message=str(exc)[:200])
        changed = None          # the browser check then visits every page
    try:
        record = site_build.build(ctx.bare(), commit, task.dir, renderer(ctx), changed=changed,
                                  log=ctx.log)
    except site_build.BuildContentError as exc:
        steps.write_check_items(ctx, exc.problems)
        checks.tool_errors(ctx, task, exc.problems)
        raise steps.CheckFailed(exc.problems) from None
    return {"commit": record.commit, "output": str(record.output),
            "duration_s": record.duration_s}


def _publish(ctx: Ctx, task: Task, record: dict) -> None:
    """G8: only when the learner's site is switched on; errors never fail the run."""
    if not ctx.student.publish:
        ctx.log.event("site.publish", "skipped", target="publish = false")
        return
    site = ctx.worktree("site")
    site_publish.fetch_gh_pages(site, ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                                ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
    published = site_publish.publish(
        site, Path(record["output"]) / "site", student=ctx.name, source_commit=record["commit"],
        run_id=task.run_id, tool_version=VERSION, log=ctx.log,
        fetch_s=ctx.cfg.timeouts.fetch_s, push_s=ctx.cfg.timeouts.push_s,
        ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
    task.update(published=published.commit)
    check_live(ctx, Path(record["output"]), record["commit"])


def check_live(ctx: Ctx, build_dir: Path, commit: str) -> None:
    """6.10: poll the live publish.json; a timeout is only a warning."""
    url = site_publish.live_url(build_dir)
    if url:
        site_publish.wait_until_live(url, commit, ctx.log)


def message(ctx: Ctx, task: Task) -> str:
    """The commit message of 6.4."""
    role, _ = ctx.cfg.role("writer")
    title = _log_title(ctx, task) or f"{task.run_id}, {_count(ctx, task)} fájl"
    return (f"notes({ctx.name}): {title}\n\nRun-Id: {task.run_id}\nKind: notes\n"
            f"Tool: school-notes {VERSION}\nWriter: {role.model}/{role.effort}\n")


def _log_title(ctx: Ctx, task: Task) -> str:
    wt = ctx.worktree("notes")
    diff = wt.out("diff", "--no-ext-diff", "--no-textconv", "-U0", task.get("base"), "--",
                  "wiki/log.md", check=False)
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            m = LOG_LINE.match(line[1:])
            if m and m.group(1).strip():
                text = LINK.sub(r"\1", m.group(1)).strip()
                return text if len(text) <= 72 else text[:71].rstrip() + "…"
    return ""


def _count(ctx: Ctx, task: Task) -> int:
    return len(workbranch.changed_files(ctx.worktree("notes"), task.get("base")))
