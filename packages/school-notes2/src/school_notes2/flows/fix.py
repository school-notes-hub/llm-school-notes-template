"""One source-free correction run per local day, using the ordinary P1/P2/P6 chain."""

from ..git import repos, workbranch
from ..figures import pending
from ..log import today
from ..review import files
from ..sources import calls
from ..state import phase, safefs
from . import correction


def next_task(ctx):
    if any(t.kind == "notes" and t.get("mode") == "fix" and
           (t.data["created"][:10] == today() or t.phase == "done" and t.data["updated"][:10] == today())
           for t in phase.all_tasks(ctx.task_root(), ctx.name)):
        return None
    # fetch.start has inspected Drive; refresh main before selecting review closures.
    repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s)
    wt = ctx.worktree("notes")
    base = repos.rev(wt, "refs/remotes/origin/main")
    wt.run("switch", "--detach", base)
    items = calls.select_reviews(files.open_items(ctx.notes_path, "cron"), ctx.cfg.limits.review_closures_per_run)
    waiting = [e for e in pending.load(ctx.notes_path) if e["runs"] < 3]
    if not items and not waiting:
        return None
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="fix", base=base, preparation_base=base, open_review_items=items,
                max_agents=ctx.cfg.limits.max_agents, attempt=1, pending_figures=waiting)
    return task


def prepare(ctx, task):
    if task.phase != "moved":
        return
    workbranch.start(ctx.worktree("notes"), task.run_id, task.get("base"), interactive=False)
    workbranch.reset_workdir(ctx.notes_path)
    image_subjects = [{"plan_id": e["commission"]["id"], "page": e["commission"]["page"]}
                      for e in task.get("pending_figures", [])]
    grouping = calls.assignments(ctx.notes_path, [], [], task.get("open_review_items"), image_subjects,
                                 review_limit=ctx.cfg.limits.review_closures_per_run)
    for call in grouping:
        call["pending_images"] = []
    waiting = pending.for_subjects(ctx.notes_path, {c["subject"] for c in grouping})
    root = task.dir / "fix-before"
    correction.snapshot(ctx.notes_path, root)
    task.set_phase("prepared", calls=grouping, ranges=calls.ranges(grouping), packages=[], pages=[],
                   pending_images=[], pending_figures=waiting, writing_k=1, skip_writer=False,
                   correction_before=str(root / "before"), dot_git=safefs.read_text(ctx.notes_path, ".git"))
