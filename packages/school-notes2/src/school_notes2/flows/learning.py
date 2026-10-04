"""Tool-written lesson pointers, draft notices and the private decision overview.

No new phase: each deterministic write is recorded BEFORE replacement so a crash
between writes (or before replacement) can resume through the normal path guard.
"""

import hashlib
import json
from datetime import date

import yaml

from ..state import safefs
from ..state.phase import Task
from ..state.errors import NeedsOwner
from ..wiki import decisions, drafts, frontmatter, guard, lesson_log
from ..wiki.pages import read_page, wiki_pages
from . import checks, steps
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
                     _metadata_problems(rel, safefs.read_text(ctx.notes_path, rel))]
    if problems:
        checks.tool_errors(ctx, task, problems)
        changed = steps.llm_snapshot(ctx, task)
        wt, base = ctx.worktree("notes"), steps.base_of(task)
        previous = {}
        for rel in sorted({p["file"] for p in problems} & changed.keys()):
            old = wt.run("show", f"{base}:{rel}", check=False)
            previous[rel] = _metadata_problems(rel, old.stdout.decode("utf-8", "replace")) \
                if old.returncode == 0 else []
        outside = [p for p in problems if p["file"] not in changed or
                   p["message"] in previous.get(p["file"], [])]
        if outside:
            raise NeedsOwner("invalid metadata predating this run: " + "; ".join(
                f"{p['file']}: {p['message']}" for p in outside),
                todo="repair the listed pages in `school-notes chat`", details={"items": outside})
        raise steps.CheckFailed(problems)


def _metadata_problems(rel: str, text: str) -> list[str]:
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
    return messages


def migrate(ctx: Ctx, task: Task) -> None:
    """Replay-safe hotfix bookkeeping, before assignment or generated-page writes."""
    from ..reader import verdicts
    from ..review import generated
    _settle_pending(ctx, task)
    records = verdicts.rekeyed(ctx.notes_path)
    if records is not None:
        _write(ctx, task, verdicts.PATH, json.dumps(records, ensure_ascii=False, indent=2) + "\n", whole=True)
    for rel, text in generated.owner_updates(ctx.notes_path):
        _write(ctx, task, rel, text, whole=True)


def refresh(ctx: Ctx, task: Task, *, today: date | None = None) -> None:
    repo = ctx.notes_path
    migrate(ctx, task)
    today = observation_date(task, today)
    validate(ctx, task)
    linked = drafts.lesson_keys(repo)
    for rel in sorted(wiki_pages(repo)):
        old = safefs.read_text(repo, rel)
        meta = read_page(repo, rel).meta
        new = drafts.update(old, linked.get(rel, []), today)
        if lesson_log.is_lesson(rel, meta):
            new = lesson_log.after_header(new, lesson_log.BLOCK, lesson_log.source_line(meta))
        if new != old:
            _write(ctx, task, rel, new, whole=False)
    overview = decisions.overview(repo)
    if not safefs.exists(repo, decisions.OVERVIEW) or safefs.read_text(repo, decisions.OVERVIEW) != overview:
        _write(ctx, task, decisions.OVERVIEW, overview, whole=True)


def _settle_pending(ctx: Ctx, task: Task) -> None:
    pending = task.get("learning_pending")
    if not pending:
        return
    rel, whole = pending["path"], pending["whole"]
    key = "tool_writes" if whole else "tool_parts"
    recorded = dict(task.get(key, {}))
    text = safefs.read_text(ctx.notes_path, rel) if safefs.exists(ctx.notes_path, rel) else None
    actual = None if text is None else (
        hashlib.sha256(text.encode()).hexdigest() if whole else guard.parts_hash(text))
    if actual == pending["before"]:
        if actual is None:
            recorded.pop(rel, None)
        else:
            recorded[rel] = actual
    elif actual != recorded.get(rel):
        raise NeedsOwner(f"interrupted tool write was edited: {rel}",
                         todo="inspect the worktree in `school-notes chat`")
    hashes = dict(task.get("tool_hashes", {}))
    if text is not None and actual != pending["before"]:
        hashes[rel] = hashlib.sha256(text.encode()).hexdigest()
    task.update(**{key: recorded}, tool_hashes=hashes, learning_pending=None)


def _write(ctx: Ctx, task: Task, rel: str, text: str, *, whole: bool) -> None:
    key = "tool_writes" if whole else "tool_parts"
    recorded = dict(task.get(key, {}))
    recorded[rel] = hashlib.sha256(text.encode()).hexdigest() if whole else guard.parts_hash(text)
    old = safefs.read_text(ctx.notes_path, rel) if safefs.exists(ctx.notes_path, rel) else None
    before = None if old is None else (
        hashlib.sha256(old.encode()).hexdigest() if whole else guard.parts_hash(old))
    task.update(**{key: recorded}, learning_pending={"path": rel, "whole": whole, "before": before})
    safefs.write_text(ctx.notes_path, rel, text)
    steps.record_tool_files(task, ctx.notes_path, [rel])
    task.update(learning_pending=None)
