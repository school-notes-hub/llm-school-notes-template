"""Source-free correction runs, using the ordinary writer → check → recheck → commit chain."""

from ..git import repos, workbranch
from ..figures import pending, migration_gate
from ..review import files
from ..sources import calls
from ..state import phase, safefs
from . import correction_figures, fix_progress, steps


def next_task(ctx):
    # fetch.start has inspected Drive; refresh main before selecting review closures.
    repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s)
    wt = ctx.worktree("notes")
    base = repos.rev(wt, "refs/remotes/origin/main")
    wt.run("switch", "--detach", base)
    items = [i for i in files.open_items(ctx.notes_path, "cron") if not migration_gate.concerns(ctx.notes_path, i)]
    entries = pending.load(ctx.notes_path)
    was_owner = {e["commission"]["id"] for e in entries if e["owner_required"]}
    waiting = correction_figures.assignable(ctx, entries)
    owners = [e for e in entries if e["owner_required"] and e["commission"]["id"] not in was_owner]
    items, waiting = fix_progress.available(ctx, items, waiting)
    waiting = fix_progress.runnable_images(ctx, waiting)
    if not owners and not items and not waiting:
        return None  # A pending bookkeeping migration alone never starts a run (R5).
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base=base, preparation_base=base, open_review_items=items,
                max_agents=ctx.cfg.limits.max_agents, attempt=1, pending_figures=waiting, figure_owners=owners,
                fix_work=fix_progress.keys(items, waiting))
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
    reviews, _ = fix_progress.available(ctx, reviews, [])
    task.update(open_review_items=reviews)
    written = correction_figures.persist_owners(ctx, task.get("figure_owners", []))
    steps.record_tool_files(task, ctx.notes_path, written)
    waiting = task.get("pending_figures", [])
    correction_figures.start(ctx.notes_path, waiting)
    grouping = calls.fix_assignments(ctx.notes_path, reviews, waiting)
    task.update(fix_work=fix_progress.keys(reviews, waiting), assigned_work=[])
    task.set_phase("prepared", calls=grouping, ranges=calls.ranges(grouping) or [[0, 0]], packages=[], pages=[],
                   pending_images=[], pending_figures=waiting, writing_k=1, skip_writer=not grouping,
                   dot_git=safefs.read_text(ctx.notes_path, ".git"))
