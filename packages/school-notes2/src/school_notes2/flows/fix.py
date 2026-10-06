"""Source-free correction runs, using the ordinary writer → check → recheck → commit chain."""

from ..git import repos, workbranch
from ..figures import pending, migration_gate
from ..review import files
from ..sources import calls
from ..state import phase, safefs
from . import correction_figures, fix_progress, orphan_places, reopen, steps, textbook_lines


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
    from . import unchecked
    recheck_only = (not owners and not items and not waiting and not reopen.pending(ctx)
                    and not orphan_places.new(ctx.notes_path) and not textbook_lines.new(ctx.notes_path))
    if recheck_only and (getattr(ctx, "recheck_started", False) or not unchecked.startable(ctx)):
        # Pages past their last recheck tell the owner once even when no run starts (e.g. a
        # page exhausted under 2.6.0); a pending bookkeeping migration alone starts no run (R5).
        unchecked.notify(ctx)
        return None
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    if recheck_only:
        # Only carried pages: one such run per round, and it is no progress of the round.
        ctx.recheck_started = True
        task.update(recheck_only=True)
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
    # The owner's reopened items and figures (`status --reopen`) join this run's work.
    written, figures = reopen.apply(ctx, task)
    steps.record_tool_files(task, ctx.notes_path, written)
    # A figure place no figure belongs to becomes a machine item of this run (fix-50/4).
    orphan_places.record(ctx, task)
    # A 🔖 textbook line without lesson or page number becomes one too (fix-52).
    textbook_lines.record(ctx, task)
    # Reopened legacy items join this first repair run, after the journaled migration.
    reviews = [i for i in files.open_items(ctx.notes_path, "cron") if not migration_gate.concerns(ctx.notes_path, i)]
    reviews, _ = fix_progress.available(ctx, reviews, [])
    task.update(open_review_items=reviews)
    written = correction_figures.persist_owners(ctx, task.get("figure_owners", []))
    steps.record_tool_files(task, ctx.notes_path, written)
    waiting = task.get("pending_figures", [])
    known = {e["commission"]["id"] for e in waiting}
    waiting = sorted(waiting + [e for e in pending.load(ctx.notes_path)
                                if e["commission"]["id"] in figures and e["commission"]["id"] not in known],
                     key=pending.assignment_order)
    task.update(pending_figures=waiting)
    correction_figures.start(ctx.notes_path, waiting)
    grouping = calls.fix_assignments(ctx.notes_path, reviews, waiting)
    task.update(fix_work=fix_progress.keys(reviews, waiting), assigned_work=[])
    task.set_phase("prepared", calls=grouping, ranges=calls.ranges(grouping) or [[0, 0]], packages=[], pages=[],
                   pending_images=[], pending_figures=waiting, writing_k=1, skip_writer=not grouping,
                   dot_git=safefs.read_text(ctx.notes_path, ".git"))
