"""Bounded hourly source-free correction runs, using the ordinary P1/P2/P6 chain."""

from ..git import repos, workbranch
from ..figures import pending, migration_gate
from ..log import today
from ..review import files, repair_migration
from ..sources import calls
from ..state import phase, safefs
from . import correction, correction_figures, steps


def next_task(ctx):
    if sum(t.kind == "notes" and t.get("mode") == "fix" and
           (t.data["created"][:10] == today() or t.phase == "done" and t.data["updated"][:10] == today())
           for t in phase.all_tasks(ctx.task_root(), ctx.name)) >= ctx.cfg.limits.fix_runs_per_day:
        return None
    # fetch.start has inspected Drive; refresh main before selecting review closures.
    repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s)
    wt = ctx.worktree("notes")
    base = repos.rev(wt, "refs/remotes/origin/main")
    wt.run("switch", "--detach", base)
    reviews = [i for i in files.open_items(ctx.notes_path, "cron") if not migration_gate.concerns(ctx.notes_path, i)]
    limit = ctx.cfg.limits.review_closures_per_run
    for page, group in calls.review_groups(reviews, repo=ctx.notes_path).items():
        if len(group) > limit:
            ctx.log.event("fix.page_over_limit", target=page, count=len(group), limit=limit)
    items = calls.select_reviews(reviews, limit, repo=ctx.notes_path)
    entries = pending.load(ctx.notes_path)
    was_owner = {e["commission"]["id"] for e in entries if e["owner_required"]}
    waiting = correction_figures.assignable(ctx, entries)
    owners = [e for e in entries if e["owner_required"] and e["commission"]["id"] not in was_owner]
    if not items and not waiting and not owners and not next(repair_migration.updates(ctx.notes_path), None):
        return None
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base=base, preparation_base=base, open_review_items=items,
                max_agents=ctx.cfg.limits.max_agents, attempt=1, pending_figures=waiting, figure_owners=owners)
    return task


def prepare(ctx, task):
    if task.phase != "moved":
        return
    workbranch.start(ctx.worktree("notes"), task.run_id, task.get("base"), interactive=False)
    workbranch.reset_workdir(ctx.notes_path)
    from . import learning
    learning.migrate(ctx, task)
    # Reopened legacy items join this first repair run, after the journaled migration.
    reviews = [i for i in files.open_items(ctx.notes_path, "cron") if not migration_gate.concerns(ctx.notes_path, i)]
    task.update(open_review_items=calls.select_reviews(reviews, ctx.cfg.limits.review_closures_per_run, repo=ctx.notes_path))
    written = correction_figures.persist_owners(ctx, task.get("figure_owners", []))
    steps.record_tool_files(task, ctx.notes_path, written)
    image_subjects = [{"plan_id": e["commission"]["id"], "page": e["commission"]["page"]}
                      for e in task.get("pending_figures", [])]
    grouping = calls.assignments(ctx.notes_path, [], [], task.get("open_review_items"), image_subjects,
                                 review_limit=ctx.cfg.limits.review_closures_per_run)
    for call in grouping:
        call["pending_images"] = []
    waiting = pending.for_subjects(ctx.notes_path, {c["subject"] for c in grouping},
                                   allowed={e["commission"]["id"] for e in task.get("pending_figures", [])})
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.set_phase("prepared", calls=grouping, ranges=calls.ranges(grouping) or [[0, 0]], packages=[], pages=[],
                   pending_images=[], pending_figures=waiting, writing_k=1, skip_writer=not grouping,
                   correction_before=str(root / "before"), dot_git=safefs.read_text(ctx.notes_path, ".git"))
