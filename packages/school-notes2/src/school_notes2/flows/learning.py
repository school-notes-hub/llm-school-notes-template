"""Tool-written lesson pointers, draft notices and the private decision overview.

No new phase: each deterministic write is recorded BEFORE replacement so a crash
between writes (or before replacement) can resume through the normal path guard.
"""

import json
from datetime import date

import yaml

from ..state import safefs
from ..state.phase import Task
from ..state.errors import NeedsOwner
from ..wiki import banners, decisions, drafts, frontmatter, lesson_log
from ..wiki.pages import read_page, wiki_pages
from . import journal, steps
from .context import Ctx


UNREADABLE = "frontmatter is not valid YAML or not a mapping"


def observation_date(task: Task, today: date | None = None) -> date:
    """Pin the date before checking or generating, also across midnight and resume."""
    if not task.get("learning_date"):
        task.update(learning_date=(today or date.today()).isoformat())
    return date.fromisoformat(task.get("learning_date"))


def validate(ctx: Ctx, task: Task) -> list[dict]:
    """Metadata problems the tool cannot process, on pages this run's author changed.

    A problem that already exists in the base never stops a run (#3): it is logged, and the
    tool's generators skip that page. A new one on an author-changed page is blocking: the
    writer's output for that page is unusable until it is fixed."""
    changed = steps.llm_snapshot(ctx, task)
    base = steps.base_reader(ctx, task)
    new, old = [], []
    for rel in sorted(wiki_pages(ctx.notes_path)):
        messages = _metadata_problems(rel, safefs.read_text(ctx.notes_path, rel))
        if not messages:
            continue
        before = base(rel)
        previous = _metadata_problems(rel, before.decode("utf-8", "replace")) if before is not None else []
        for message in messages:
            problem = steps.wiki_check.item(rel, None, message, kind=steps.wiki_check.BLOCKING)
            (new if rel in changed and message not in previous else old).append(problem)
    unreadable = [p for p in old if p["message"] == UNREADABLE]
    if unreadable:
        # The tool cannot read such a page at all; only this blocks, and only the owner can
        # repair main. Every other old metadata problem is logged and the run goes on (#3).
        raise NeedsOwner("unreadable frontmatter predating this run: " + ", ".join(p["file"] for p in unreadable),
                         todo="repair the listed pages in `school-notes chat`", details={"items": unreadable})
    if old:
        ctx.log.event("learning.old_metadata", "warning", items=old[:20])
    return new


def broken(repo, rel) -> bool:
    return bool(_metadata_problems(rel, safefs.read_text(repo, rel)))


def _metadata_problems(rel: str, text: str) -> list[str]:
    try:
        meta = frontmatter.split(text).meta
    except (ValueError, yaml.YAMLError):
        return [UNREADABLE]
    messages = drafts.problems(meta) + decisions.decision_problems(meta)
    if lesson_log.is_lesson(rel, meta):
        try:
            lesson_log.source_line(meta)
        except ValueError as exc:
            messages.append(str(exc))
    return messages


def migrate(ctx: Ctx, task: Task) -> None:
    """Replay-safe hotfix bookkeeping, before assignment or generated-page writes."""
    from ..reader import verdicts
    from ..review import repair_migration
    journal.settle(ctx, task)
    records = verdicts.rekeyed(ctx.notes_path)
    if records is not None:
        journal.write(ctx, task, verdicts.PATH, json.dumps(records, ensure_ascii=False, indent=2) + "\n", whole=True)
    for rel, text in repair_migration.updates(ctx.notes_path):
        journal.write(ctx, task, rel, text, whole=True)


def refresh(ctx: Ctx, task: Task, *, today: date | None = None) -> None:
    repo = ctx.notes_path
    migrate(ctx, task)
    today = observation_date(task, today)
    journal.settle(ctx, task)
    skipped = {rel for rel in wiki_pages(repo) if broken(repo, rel)}
    linked = drafts.lesson_keys(repo, skip=skipped)
    for rel in sorted(set(wiki_pages(repo)) - skipped):
        old = safefs.read_text(repo, rel)
        meta = read_page(repo, rel).meta
        try:
            new = banners.update(repo, rel, old)
        except (ValueError, OSError) as exc:  # An unusable banner_from is the writer's to fix.
            ctx.log.event("learning.banner_skipped", "warning", target=rel, message=str(exc)[:200])
            new = old
        new = drafts.update(new, linked.get(rel, []), today)
        if lesson_log.is_lesson(rel, meta):
            new = lesson_log.after_header(new, lesson_log.BLOCK, lesson_log.source_line(meta))
        if new != old:
            journal.write(ctx, task, rel, new, whole=False)
    overview = decisions.overview(repo, skip=skipped)
    if not safefs.exists(repo, decisions.OVERVIEW) or safefs.read_text(repo, decisions.OVERVIEW) != overview:
        journal.write(ctx, task, decisions.OVERVIEW, overview, whole=True)
