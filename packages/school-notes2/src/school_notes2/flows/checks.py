"""Check response and file provenance (repair plan 5.3, 8). Warnings never need a decision."""

import hashlib
from collections import Counter

from ..state import safefs
from ..state.errors import SnError
from ..wiki.check import errors


def ordered(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: (i.get("severity", "error") != "error", i["file"],
                                        i.get("line") or 0, i["message"], i.get("id", "")))


def record_failure(ctx, task, exc, step):
    """Consumed failures need the same evidence as those reaching the error policy."""
    ctx.log.error(step, exc)
    task.update(last_check_problems=ordered(exc.items))


def identify(items: list[dict], repo=None) -> list[dict]:
    """A content-derived, deterministic id per warning (file, line text, message)."""
    counts, out, lines = Counter(), [], {}
    for i in ordered(items):
        if i.get("severity") == "warning" and "id" not in i:
            rel, n = i["file"], i.get("line")
            if repo is not None and rel not in lines:
                lines[rel] = (safefs.read_text(repo, rel).splitlines()
                              if safefs.is_file(repo, rel) else [])
            content = lines.get(rel, [])
            raw = content[n - 1] if n and 0 < n <= len(content) else ""
            digest = hashlib.sha256(f"{raw}:{i['message']}".encode()).hexdigest()
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
        found = [i for i in found if i["file"] in task.get("tool_writes", {}) or i["file"] not in authored]
    if found:
        exc = SnError("check failed on unchanged tool output", details={"items": found},
                      todo="repair the tool; do not ask the writer to change generated output")
        from ..notify import incidents
        incidents.record(ctx, "program", "check", task=task, exc=exc)
        raise exc
