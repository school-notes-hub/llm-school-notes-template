"""Replayable tool writes: record before replacement and recover interrupted writes."""

import hashlib

from ..state import safefs
from ..state.phase import Task
from ..state.errors import NeedsOwner
from ..wiki import guard
from .context import Ctx


def settle(ctx: Ctx, task: Task) -> None:
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


def write(ctx: Ctx, task: Task, rel: str, text: str, *, whole: bool) -> None:
    key = "tool_writes" if whole else "tool_parts"
    recorded = dict(task.get(key, {}))
    recorded[rel] = hashlib.sha256(text.encode()).hexdigest() if whole else guard.parts_hash(text)
    old = safefs.read_text(ctx.notes_path, rel) if safefs.exists(ctx.notes_path, rel) else None
    before = None if old is None else (
        hashlib.sha256(old.encode()).hexdigest() if whole else guard.parts_hash(old))
    task.update(**{key: recorded}, learning_pending={"path": rel, "whole": whole, "before": before})
    safefs.write_text(ctx.notes_path, rel, text)
    from . import steps
    steps.record_tool_files(task, ctx.notes_path, [rel])
    task.update(learning_pending=None)
