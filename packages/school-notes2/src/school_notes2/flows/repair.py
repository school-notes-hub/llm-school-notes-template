"""Explicit repair and queue building; no Drive or paid image calls (plan 11)."""

import json

from ..git import repos, workbranch
from ..repair import queue
from ..sources import cards
from ..state import phase, safefs
from ..state.errors import NeedsOwner
from . import policy, setup, steps
from .context import Ctx
from .operation import entry


@entry("repair")
def repair(ctx: Ctx, *, topic: str | None = None, build_queue: bool = False,
           no_push: bool = False) -> int:
    from . import run
    lock = ctx.lock()
    lock.acquire("repair")
    task = None
    try:
        setup.ensure(ctx)
        existing = phase.open_task(ctx.task_root(), ctx.name, "notes")
        if existing is not None:
            if existing.get("mode") != "repair" or existing.get("repair_topic") != topic or bool(
                    existing.get("repair_request_queue", existing.get("queue_only"))) != build_queue:
                raise NeedsOwner("another notes run is open", todo="finish or discard it first")
            if existing.data.get("needs_owner"):
                raise NeedsOwner("repair needs an owner decision", todo="continue or discard it via status")
            task = existing
            # Resuming the same command never implicitly lifts --no-push.
        else:
            task = start(ctx, topic=topic, build_queue=build_queue, no_push=no_push)
        run.ctx_bind(ctx, task)
        run.advance(ctx, task)
        policy.on_success(task)
        return 0
    except Exception as exc:  # noqa: BLE001 - the shared run error policy
        from ..repair import failure
        if failure.handle(ctx, task, exc):
            return 1
        policy.on_error(exc, task=task, student=ctx.name, step="repair", log=ctx.log,
                        mailer=ctx.mailer if task is not None else None)
        return 1
    finally:
        lock.release()


def start(ctx, *, topic=None, build_queue=False, no_push=False):
    wt = ctx.worktree("notes")
    changed = workbranch.changed_files(wt, "HEAD")
    if changed and not (build_queue and all(c["path"] == queue.PATH for c in changed)):
        raise NeedsOwner("the notes worktree has changes outside repair", todo="finish or discard them first")
    # Use the local main snapshot. A normal finish fetches/rebases; a trial stays local.
    base = repos.rev(wt, "refs/remotes/origin/main")
    previous = queue.load(ctx.notes_path) if build_queue else None
    if changed:
        _priority_edits(wt, previous)
    if not build_queue:
        from ..repair.preflight import require_ready
        require_ready(wt, base, topic)
    task = phase.create(ctx.task_root(), ctx.name, "notes", "cron", "moved")
    task.update(mode="repair", repair_topic=topic, queue_only=build_queue,
                repair_request_queue=build_queue, no_push=no_push,
                base=base, preparation_base=base, queue_previous=previous)
    return task


def prepare(ctx, task):
    if task.phase != "moved":
        return
    from ..repair import failure
    failure.restore(ctx, task)
    repo = ctx.notes_path
    workbranch.start(ctx.worktree("notes"), task.run_id, task.get("base"), interactive=False)
    workbranch.reset_workdir(repo)
    data = task.get("repair_queue")
    if data is None:
        data = queue.build(repo, task.get("queue_previous")) if task.get("queue_only") else queue.load(repo)
        task.update(repair_queue=data)
    calls, targets = [], []
    if not task.get("queue_only"):
        book = queue.inventory(repo)
        rel = task.get("repair_topic")
        queue.require_ready(rel, data, book)
        targets = [{"page": rel, "kind": book[rel].meta.get("type", "concept"),
                    "sources": queue.sources(repo, rel, book), "related": queue.related(rel, book)}]
        subject = rel.split("/")[1]
        call = {"subject": subject, "packages": [], "seqs": [],
                "open_review_items": [], "pending_images": []}
        card = cards.load(repo, subject)
        if card is not None:
            call["card"] = card
        calls = [call]
    if task.get("queue_only") and not task.get("repair_queue_absent"):
        safefs.write_json(repo, queue.PATH, data)
        steps.record_tool_files(task, repo, [queue.PATH])
    failure.write_item(ctx, task)
    from ..figures import pending as figure_pending
    pending_figures = figure_pending.for_subjects(repo, {c["subject"] for c in calls})
    task.set_phase("prepared", calls=calls, repair_targets=targets, packages=[], pages=[],
                   pending_figures=pending_figures,
                   ranges=[[0, 0]], open_review_items=[], pending_images=[],
                   skip_writer=bool(task.get("queue_only")), dot_git=safefs.read_text(repo, ".git"))


def complete(ctx, task):
    """Mark completion in the same commit as the page; a trial affects only its branch."""
    if task.get("mode") != "repair" or task.get("queue_only"):
        return
    data = queue.load(ctx.notes_path)
    for item in data["items"]:
        if item["page"] == task.get("repair_topic"):
            item["status"] = "done"
            from . import journal
            journal.write(ctx, task, queue.PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n", whole=True)
            return


def next_task(ctx):
    item = queue.next_item(queue.load(ctx.notes_path))
    return start(ctx, topic=item["page"]) if item else None


def _priority_edits(wt, current):
    old = wt.run("show", f"HEAD:{queue.PATH}", check=False)
    before = json.loads(old.stdout) if old.returncode == 0 else None
    def without_priority(data):
        return {**data, "items": [{k: v for k, v in row.items() if k not in ("priority", "urgent")}
                                  for row in data["items"]]}
    if before is None or without_priority(before) != without_priority(current):
        raise NeedsOwner("only priority and urgent may be edited before repair --queue",
                         todo="restore queue states and inventory; edit priority and urgent only")
