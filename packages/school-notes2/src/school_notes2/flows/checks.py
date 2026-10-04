"""Check response, invocation accounting and file provenance (repair plan 5.3, 8)."""

import hashlib
from collections import Counter

from ..review import warnings as verdicts
from ..state import safefs
from ..state.errors import SnError
from ..wiki import source_refs
from ..wiki.check import errors, item

LIMIT = {"limit_reached": True, "message": "Check limit reached: write result.json and stop."}


def begin(task) -> None:
    """Only the launcher starts an invocation; MCP fetch/check cannot reset its budget."""
    task.update(writer_check={"count": 0, "warnings": []})


def take(task) -> bool:
    state = dict(task.get("writer_check", {"count": 0, "warnings": []}))
    if state["count"] >= 3:
        return False
    state["count"] += 1
    task.update(writer_check=state)  # Before any work, also if this check crashes.
    return True


def ordered(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: (i.get("severity", "error") != "error", i["file"],
                                        i.get("line") or 0, i["message"], i.get("id", "")))


def identify(items: list[dict]) -> list[dict]:
    counts, out = Counter(), []
    for i in ordered(items):
        if i.get("severity") == "warning" and "id" not in i:
            digest = source_refs.line_hash(f"{i.get('line')}:{i['message']}")
            counts[(i["file"], digest)] += 1
            i = {**i, "id": f"{i['file']}:{digest}:{counts[(i['file'], digest)]}"}
        out.append(i)
    return out


def response(items: list[dict]) -> dict:
    items = ordered(items)
    n = len(errors(items))
    return {"ok": n == 0, "errors": n, "warnings": len(items) - n,
            "truncated": len(items) > 50, "full_list": ".school-notes/check.json",
            "problems": items[:50]}


def remember(task, items: list[dict]) -> None:
    state = dict(task.get("writer_check", {"count": 0}))
    state["warnings"] = [i["id"] for i in items if i.get("severity") == "warning"]
    task.update(writer_check=state)


def accounting(task, result: dict) -> list[dict]:
    ids = [i["id"] for i in result.get("warnings", [])]
    missing = sorted(set(task.get("writer_check", {}).get("warnings", [])) - set(ids))
    out = [item(".school-notes/result.json", None, f"warnings: missing decision for {i}") for i in missing]
    if len(ids) != len(set(ids)):
        out.append(item(".school-notes/result.json", None, "warnings: duplicate decision ids"))
    return out


def source_warnings(ctx, task, paths: list[str]) -> list[dict]:
    from .steps import base_of
    out, counts = [], {}
    wt = ctx.worktree("notes")
    for rel in sorted(set(paths)):
        if not rel.startswith("wiki/") or not rel.endswith((".md", ".svg")) or not safefs.is_file(ctx.notes_path, rel):
            continue
        old = wt.run("show", f"{base_of(task)}:{rel}", check=False)
        text = safefs.read_text(ctx.notes_path, rel)
        if rel != "wiki/log.md":
            counts[rel] = 0
        out += source_refs.scan(rel, text, old.stdout.decode("utf-8", "replace") if old.returncode == 0 else "",
                                full=task.get("mode") == "repair")
    counts.update(Counter(i["file"] for i in out))
    counts = dict(sorted(counts.items()))
    task.update(source_ref_counts=counts)
    ctx.log.event("check.source_refs", counts=counts)
    return verdicts.pending(ctx.notes_path, out)


def tool_errors(ctx, task, items: list[dict]) -> None:
    """Only exact, last-written whole-file hashes establish tool responsibility."""
    recorded = {**task.get("tool_writes", {}), **task.get("tool_hashes", {})}
    found = [i for i in errors(items) if i["file"] in recorded and
             safefs.is_file(ctx.notes_path, i["file"]) and
             hashlib.sha256(safefs.read_bytes(ctx.notes_path, i["file"])).hexdigest() == recorded[i["file"]]]
    if found:
        from .steps import llm_snapshot
        authored = llm_snapshot(ctx, task)
        # A metadata stamp does not transfer ownership of the author's prose.
        found = [i for i in found if i["file"] in task.get("tool_writes", {})
                 or i["file"] not in authored]
    if found:
        raise SnError("check failed on unchanged tool output", details={"items": found},
                      todo="repair the tool; do not ask the writer to change generated output")


def after_writer(ctx, task, result: dict, items: list[dict]) -> list[dict]:
    """New warnings after the last own check are reviewer work, never bad writer work."""
    decided = {i["id"] for i in result.get("warnings", [])}
    warnings = [{**i, "unhandled": i["id"] not in decided} for i in identify(items)
                if i.get("severity") == "warning"]
    task.update(check_warnings=warnings)
    return warnings
