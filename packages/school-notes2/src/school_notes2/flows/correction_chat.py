"""Durable P4 handoff to the existing interactive writer, without another container."""

from ..llm.argv import prompt
from ..schemas import validate
from ..state import phase, safefs
from ..state.errors import BadWork
from . import correction_round, fetch, inspection, writer


def active(task):
    if task.mode != "interactive" or task.phase != "correcting":
        return None
    return phase.load(correction_round.root(task) / "writer")


def result(ctx, child):
    if not child.get("interactive_ready"):
        writer.write_inputs(ctx, child, 1)
        child.update(interactive_ready=True)
        return None
    try:
        value = safefs.read_json(ctx.notes_path, ".school-notes/result.json")
        if value is None:
            return None  # Repeating finish/fetch must not consume or erase the handoff.
        validate("result", value)
    except ValueError as exc:
        raise BadWork(str(exc)) from None
    return value


def handoff(ctx, items):
    return {"state": "review_items", "open_review_items": items,
            "prompt": prompt("fix", grade=ctx.student.grade)}


def resume_inputs(ctx, task):
    child = active(task)
    if child is None or not child.get("interactive_ready"):
        return False
    safefs.write_json(ctx.notes_path, ".school-notes/fetch.json",
                      fetch.fetch_json(child, 1, grade=ctx.student.grade, repo=ctx.notes_path))
    writer.write_changes(ctx, child)
    return True


def restore_inputs(ctx, task):
    safefs.write_json(ctx.notes_path, ".school-notes/fetch.json", fetch.fetch_json(
        task, min(task.get("writing_k", 1), len(task.get("ranges"))), grade=ctx.student.grade, repo=ctx.notes_path))
    root = correction_round.root(task)
    path = ".school-notes/result.json"
    if safefs.is_file(root, "before/" + path):
        safefs.write_bytes(ctx.notes_path, path, safefs.read_bytes(root, "before/" + path))
    else:
        safefs.unlink(ctx.notes_path, path)
