"""`finish` (plan 5.4): content steps 1–9, then the Git order G0–G9 with the site hooks."""

import hashlib
import re
from pathlib import Path

from .. import VERSION
from ..git import finish as git_finish
from ..git import workbranch
from ..site import build as site_build
from ..site import publish as site_publish
from ..state.errors import NeedsOwner, SnError
from ..state import safefs
from ..state.phase import Task
from ..wiki import markers
from . import checks, steps
from .context import Ctx

LOG_LINE = re.compile(r"^\s*[*-]\s+(?:\*\*[^*]+\*\*:\s*)?(.*)$")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def finish(ctx: Ctx, task: Task, *, notify_owner_items) -> str | dict:
    """Run a notes task from `finishing` (or a later Git phase) to `done`.

    Raises steps.CheckFailed (the writer must fix check.json), NeedsOwner, Transient."""
    from ..figures import licenses
    licenses.preflight(ctx.notes_path)
    try:
        return _finish(ctx, task, notify_owner_items)
    except git_finish.EditedDuringFinish:
        task.set_phase("writing", review_complete=False, attempt=task.get("attempt", 1) + 1)
        raise


def _finish(ctx, task, notify_owner_items):
    wt = ctx.worktree("notes")
    start = _snapshot(ctx, task)
    edits = {"replacements": []} if task.mode == "interactive" else None
    from . import review_phases
    if task.phase in ("prepared", "writing", "finishing") and not task.get("review_complete"):
        prepared = steps.content_steps(ctx, task)
        notify_owner_items(prepared.new_owner)
        if prepared.question:
            raise NeedsOwner("the writer asked a blocking question",
                             todo="answer it in `school-notes chat`",
                             details={"questions": prepared.result.get("questions", [])})
        task.set_phase("figures", inspection_result=prepared.result,
                       attempt=task.get("attempt", 1), max_agents=task.get("max_agents", ctx.cfg.limits.max_agents))
    if task.phase in (*review_phases.PHASES, "waiting_quota"):
        review_phases.advance(ctx, task, notify_owner_items, edits)
    elif task.get("rebase") == "conflict":
        steps.guard_step(ctx, task)
        steps.regenerate(ctx, task)
    from . import repair, report
    if task.phase == "finishing":
        repair.complete(ctx, task)
    hooks = git_finish.Hooks(
        regenerate=lambda: steps.regenerate(ctx, task),
        build=lambda commit: _build(ctx, task, commit),
        publish=lambda record: _publish(ctx, task, record),
        message=lambda: message(ctx, task),
        snapshot=lambda: _snapshot(ctx, task, start),
        empty_blocks=markers.empty_all,
        rerecord=lambda paths: steps.rerecord(ctx, task, paths),
        final_keys=lambda: review_phases.final_keys(ctx, task),
        extra_paths=("references",) if task.mode == "interactive" else ())
    t = git_finish.Timeouts(ctx.cfg.timeouts.fetch_s, ctx.cfg.timeouts.push_s,
                            ctx.cfg.timeouts.ls_remote_s)
    for page, before, after in (edits or {}).get("replacements", []):
        if start.get(page) != before:
            raise git_finish.EditedDuringFinish("files changed before figure replacement")
        if after is None:
            start.pop(page, None)
        else:
            start[page] = after
    state = git_finish.run(task, wt, hooks, t, start)
    if state in ("done", "committed"):
        report.completion(ctx, task)
    return state


def _snapshot(ctx: Ctx, task: Task, authored=()) -> dict:
    """5.4/9 guards against a session editing during finish; cron has no session."""
    if task.mode != "interactive":
        return {}
    snapshot = steps.llm_snapshot(ctx, task)
    snapshot.update(_candidate_snapshot(ctx.notes_path))
    # Accepted candidate bytes become tool-owned, but were authored before finish.
    # Keep comparing those bytes even after the insertion records their ownership.
    for rel in sorted((set(authored) & set(task.get("tool_writes", {}))) - set(snapshot)):
        snapshot[rel] = steps._llm_hash(rel, safefs.read_bytes(ctx.notes_path, rel)) \
            if safefs.is_file(ctx.notes_path, rel) else None
    # P2 may replace the candidate metadata with a failure. Keep its original asset
    # in this invocation's comparison even then, including assets unchanged at base.
    for rel in sorted(p for p in set(snapshot) | set(authored) if p.startswith("wiki/assets/")):
        snapshot[rel] = hashlib.sha256(safefs.read_bytes(ctx.notes_path, rel)).hexdigest() \
            if safefs.is_file(ctx.notes_path, rel) else None
    return dict(sorted(snapshot.items()))


def _candidate_snapshot(repo):
    out = {}
    for path in safefs.walk_files(repo, ".school-notes/figures"):
        if not path.endswith("/figure.json"):
            continue
        try:
            candidate = safefs.read_json(repo, path)
            asset = candidate.get("asset") if isinstance(candidate, dict) else None
            if isinstance(asset, str) and asset.startswith("wiki/assets/"):
                out[asset] = hashlib.sha256(safefs.read_bytes(repo, asset)).hexdigest() if safefs.is_file(repo, asset) else None
        except (ValueError, OSError):
            continue  # Candidate contract errors belong to check/P2.
    return out


def renderer(ctx: Ctx) -> site_build.Renderer:
    t = ctx.cfg.timeouts
    return site_build.Renderer(
        study_site=ctx.release() / "packages" / "study-site", browser=ctx.cfg.browser,
        pdf_cache=ctx.cfg.state_dir / "pdf-cache" / ctx.name, build_s=t.build_s,
        browser_check_s=t.browser_check_s, check_public_s=t.check_public_s)


def _build(ctx: Ctx, task: Task, commit: str) -> dict:
    """G5. A content problem holds the publication and becomes an item for the next run;
    the notes commit itself is kept and pushed (no rollback, no new attempt)."""
    site = ctx.worktree("site")
    try:
        site_publish.fetch_gh_pages(site, ctx.log, fetch_s=ctx.cfg.timeouts.fetch_s,
                                    ls_remote_s=ctx.cfg.timeouts.ls_remote_s)
        changed = site_publish.changed_since_publish(ctx.bare(), site, commit)
    except SnError as exc:      # the site repo's trouble never stops the notes run (5.10)
        ctx.log.event("site.changed_since_publish", "error", message=str(exc)[:200])
        changed = None          # the browser check then visits every page
    try:
        record = site_build.build(ctx.bare(), commit, task.dir, renderer(ctx), changed=changed, log=ctx.log)
    except site_build.BuildContentError as exc:
        problems = checks.ordered(exc.problems)
        checks.tool_errors(ctx, task, problems)
        from . import machine_findings
        machine_findings.record(ctx, task, problems)
        task.update(build_problems=problems)
        ctx.log.event("site.build_held", "warning", problems=problems[:20])
        return {"commit": commit, "held": True}
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
    import json
    from . import writer
    requests = writer.merge(writer.results(task, required=False)).get("review_requests", []) if task.get("ranges") else []
    # The writer's request for a targeted nightly check travels unchanged with the commit.
    material = ("School-Notes-Review-Request: " + json.dumps(requests, ensure_ascii=False) + "\n") if requests else ""
    return (f"notes({ctx.name}): {title}\n\nRun-Id: {task.run_id}\nKind: notes\n"
            f"Tool: school-notes {VERSION}\nWriter: {role.model}/{role.effort}\n"
            f"School-Notes-Run: {task.get('mode') or ('chat' if task.mode == 'interactive' else 'run')}\n" + material)


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
