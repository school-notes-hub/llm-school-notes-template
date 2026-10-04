"""Tool-written lesson pointers, draft notices and the private decision overview.

No new phase: each deterministic write is recorded BEFORE replacement so a crash
between writes (or before replacement) can resume through the normal path guard.
"""

import hashlib
from datetime import date

from ..state import safefs
from ..state.phase import Task
from ..wiki import decisions, drafts, frontmatter, guard, lesson_log
from ..wiki.pages import wiki_pages
from . import steps
from .context import Ctx


def refresh(ctx: Ctx, task: Task, *, today: date | None = None) -> None:
    repo = ctx.notes_path
    # Pin the observation date across crashes/resume, including across midnight.
    if not task.get("learning_date"):
        task.update(learning_date=(today or date.today()).isoformat())
    today = date.fromisoformat(task.get("learning_date"))
    linked = drafts.lesson_keys(repo)
    for rel in sorted(wiki_pages(repo)):
        old = safefs.read_text(repo, rel)
        meta = frontmatter.split(old).meta
        invalid = drafts.problems(meta)
        if invalid:
            raise steps.CheckFailed([steps.wiki_check.item(rel, None, m) for m in invalid])
        new = drafts.update(old, linked.get(rel, []), today)
        if lesson_log.is_lesson(rel, meta):
            try:
                new = lesson_log.after_header(new, lesson_log.BLOCK, lesson_log.source_line(meta))
            except (ValueError, TypeError, AttributeError) as exc:
                raise steps.CheckFailed([steps.wiki_check.item(rel, None, str(exc))]) from exc
        if new != old:
            _write(ctx, task, rel, new, whole=False)
    try:
        overview = decisions.overview(repo)
    except decisions.DecisionError as exc:
        raise steps.CheckFailed([steps.wiki_check.item(exc.page, None, m) for m in exc.problems]) from exc
    if not safefs.exists(repo, decisions.OVERVIEW) or safefs.read_text(repo, decisions.OVERVIEW) != overview:
        _write(ctx, task, decisions.OVERVIEW, overview, whole=True)
    if task.get("learning_pending"):
        task.update(learning_pending=None)


def _write(ctx: Ctx, task: Task, rel: str, text: str, *, whole: bool) -> None:
    key = "tool_writes" if whole else "tool_parts"
    recorded = dict(task.get(key, {}))
    recorded[rel] = hashlib.sha256(text.encode()).hexdigest() if whole else guard.parts_hash(text)
    old = safefs.read_text(ctx.notes_path, rel) if safefs.exists(ctx.notes_path, rel) else None
    before = None if old is None else (
        hashlib.sha256(old.encode()).hexdigest() if whole else guard.parts_hash(old))
    task.update(**{key: recorded}, learning_pending={"path": rel, "whole": whole, "before": before})
    safefs.write_text(ctx.notes_path, rel, text)
    task.update(learning_pending=None)
