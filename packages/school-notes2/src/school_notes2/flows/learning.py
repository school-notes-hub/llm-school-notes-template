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
from ..wiki.pages import read_page, resolve, wiki_pages
from . import checks, journal, steps
from .context import Ctx


def observation_date(task: Task, today: date | None = None) -> date:
    """Pin the date before checking or generating, also across midnight and resume."""
    if not task.get("learning_date"):
        task.update(learning_date=(today or date.today()).isoformat())
    return date.fromisoformat(task.get("learning_date"))


def validate(ctx: Ctx, task: Task) -> None:
    """Inspect metadata page by page before any whole-wiki consumer or tool write."""
    problems = []
    for rel in sorted(wiki_pages(ctx.notes_path)):
        problems += [steps.wiki_check.item(rel, None, m) for m in
                     _metadata_problems(rel, safefs.read_text(ctx.notes_path, rel), ctx.notes_path)]
    if problems:
        _classify(ctx, task, problems)


def _classify(ctx, task, problems):
    changed = steps.llm_snapshot(ctx, task)
    base = steps.base_reader(ctx, task)
    def read_old(repo, rel):
        text = base(rel)
        if text is None:
            raise FileNotFoundError(rel)
        return frontmatter.split(text.decode("utf-8", "replace"))
    outside, routed = [], []
    for problem in problems:
        rel = problem["file"]
        old = base(rel)
        previous = _metadata_problems(rel, old.decode("utf-8", "replace"), ctx.notes_path, read_old) if old else []
        if problem["message"] not in previous:
            dependency = _banner_dependency(ctx.notes_path, rel, problem["message"])
            if dependency in changed:
                problem = {**problem, "file": dependency, "message": f"{rel}: {problem['message']}"}
            elif rel not in changed:
                outside.append(problem)
        else:
            outside.append(problem)
        routed.append(problem)
    checks.tool_errors(ctx, task, routed)
    if outside:
        raise NeedsOwner("invalid metadata predating this run: " + "; ".join(
            f"{p['file']}: {p['message']}" for p in outside),
            todo="repair the listed pages in `school-notes chat`", details={"items": outside})
    raise steps.CheckFailed(routed)


def _banner_dependency(repo, rel, message):
    try:
        meta = read_page(repo, rel).meta
    except (ValueError, OSError):
        return None
    try:
        banners.body(repo, rel, meta)
    except (ValueError, OSError) as exc:
        if str(exc) == message and isinstance(meta.get("banner_from"), str):
            return resolve(rel, meta["banner_from"])
    return None


def _metadata_problems(rel: str, text: str, repo=None, banner_reader=read_page) -> list[str]:
    try:
        meta = frontmatter.split(text).meta
    except (ValueError, yaml.YAMLError):
        return ["frontmatter is not valid YAML or not a mapping"]
    messages = drafts.problems(meta) + decisions.decision_problems(meta)
    if lesson_log.is_lesson(rel, meta):
        try:
            lesson_log.source_line(meta)
        except ValueError as exc:
            messages.append(str(exc))
    if repo is not None and not messages:
        try:
            banners.body(repo, rel, meta, read=banner_reader)
        except (ValueError, OSError) as exc:
            messages.append(str(exc))
    return messages


def migrate(ctx: Ctx, task: Task) -> None:
    """Replay-safe hotfix bookkeeping, before assignment or generated-page writes."""
    from ..reader import verdicts
    from ..review import generated, repair_migration
    journal.settle(ctx, task)
    records = verdicts.rekeyed(ctx.notes_path)
    if records is not None:
        journal.write(ctx, task, verdicts.PATH, json.dumps(records, ensure_ascii=False, indent=2) + "\n", whole=True)
    for rel, text in repair_migration.updates(ctx.notes_path):
        journal.write(ctx, task, rel, text, whole=True)
    for rel, text in generated.owner_updates(ctx.notes_path):
        journal.write(ctx, task, rel, text, whole=True)


def refresh(ctx: Ctx, task: Task, *, today: date | None = None) -> None:
    repo = ctx.notes_path
    migrate(ctx, task)
    today = observation_date(task, today)
    validate(ctx, task)
    journal.settle(ctx, task)
    linked = drafts.lesson_keys(repo)
    for rel in sorted(wiki_pages(repo)):
        old = safefs.read_text(repo, rel)
        meta = read_page(repo, rel).meta
        new = banners.update(repo, rel, old)
        new = drafts.update(new, linked.get(rel, []), today)
        if lesson_log.is_lesson(rel, meta):
            new = lesson_log.after_header(new, lesson_log.BLOCK, lesson_log.source_line(meta))
        if new != old:
            journal.write(ctx, task, rel, new, whole=False)
    overview = decisions.overview(repo)
    if not safefs.exists(repo, decisions.OVERVIEW) or safefs.read_text(repo, decisions.OVERVIEW) != overview:
        journal.write(ctx, task, decisions.OVERVIEW, overview, whole=True)
