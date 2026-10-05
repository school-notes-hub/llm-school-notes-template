"""Check response, invocation accounting and file provenance (repair plan 5.3, 8)."""

import hashlib
from pathlib import Path
from collections import Counter

from ..review import warnings as verdicts
from ..state import safefs
from ..state.errors import SnError
from ..wiki import source_refs
from ..wiki.check import errors, item

LIMIT = {"limit_reached": True, "message": "Check limit reached: write result.json and stop."}


def begin(task) -> None:
    """A launcher invocation or a new interactive run starts its own budget."""
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


def record_failure(ctx, task, exc, step):
    """Consumed failures need the same evidence as those reaching the error policy."""
    ctx.log.error(step, exc)
    task.update(last_check_problems=ordered(exc.items))


def identify(items: list[dict], repo=None) -> list[dict]:
    counts, out, lines = Counter(), [], {}
    for i in ordered(items):
        if i.get("severity") == "warning" and "id" not in i:
            rel, n = i["file"], i.get("line")
            if repo is not None and rel not in lines:
                lines[rel] = (safefs.read_text(repo, rel).splitlines()
                              if safefs.is_file(repo, rel) else [])
            content = lines.get(rel, [])
            raw = content[n - 1] if n and 0 < n <= len(content) else ""
            digest = source_refs.line_hash(f"{raw}:{i['message']}")
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
    state["warnings"] = [i["id"] for i in items if i.get("severity") == "warning"
                         and i.get("kind") != "inherited-check"]
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
    from ..wiki import footnotes
    out, counts, footnote_counts = [], {}, {}
    wt = ctx.worktree("notes")
    for rel in sorted(set(paths)):
        if not rel.startswith("wiki/") or not rel.endswith((".md", ".svg")) or not safefs.is_file(ctx.notes_path, rel):
            continue
        old = wt.run("show", f"{base_of(task)}:{rel}", check=False)
        text = safefs.read_text(ctx.notes_path, rel)
        previous = old.stdout.decode("utf-8", "replace") if old.returncode == 0 else ""
        if task.get("correction_before"):
            before = Path(task.get("correction_before"))
            previous = safefs.read_text(before, rel) if safefs.is_file(before, rel) else ""
        if rel != "wiki/log.md":
            counts[rel] = footnote_counts[rel] = 0
        out += source_refs.scan(rel, text, previous,
                                full=task.get("mode") == "repair")
        out += footnotes.scan(rel, text, previous, full=task.get("mode") == "repair")
    counts.update(Counter(i["file"] for i in out if i.get("kind") != "public_footnote"))
    footnote_counts.update(Counter(i["file"] for i in out if i.get("kind") == "public_footnote"))
    counts = dict(sorted(counts.items()))
    task.update(source_ref_counts=counts, public_footnote_counts=dict(sorted(footnote_counts.items())))
    ctx.log.event("check.source_refs", counts=counts)
    ctx.log.event("check.public_footnotes", counts=dict(sorted(footnote_counts.items())))
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
        found = [i for i in found if not (i.get("kind") == "browser-link" and i.get("target") in authored)
                 and (i["file"] in task.get("tool_writes", {}) or i["file"] not in authored)]
    if found:
        exc = SnError("check failed on unchanged tool output", details={"items": found},
                      todo="repair the tool; do not ask the writer to change generated output")
        from ..notify import incidents
        incidents.record(ctx, "program", "check", task=task, exc=exc)
        raise exc


def after_writer(ctx, task, result: dict, items: list[dict]) -> list[dict]:
    """New warnings after the last own check are reviewer work, never bad writer work."""
    decided = {i["id"] for i in result.get("warnings", [])}
    warnings = [{**i, "unhandled": i["id"] not in decided} for i in identify(items, ctx.notes_path)
                if i.get("severity") == "warning"]
    task.update(check_warnings=[i for i in warnings if i.get("kind") != "inherited-check"])
    return warnings


def build_dependencies(ctx, task, items):
    """A changed link target and its referring page go back to the same repair round."""
    if not any(i.get("kind") == "browser-link" and i.get("target") for i in items):
        return ordered(items)
    from . import steps
    authored = steps.llm_snapshot(ctx, task)
    out = list(items)
    for problem in items:
        target = problem.get("target")
        if problem.get("kind") == "browser-link" and target in authored and target != problem["file"]:
            out.append({**problem, "file": target,
                        "message": f"{problem['file']}: {problem['message']}"})
    return ordered(out)


def browser_warnings(ctx, task, items):
    """Only notice-only edits excuse an inherited browser defect, never a changed target."""
    import re
    from . import steps
    from ..wiki import markers
    base = steps.base_reader(ctx, task)
    notice_only = set()
    for page in steps.changed_paths(ctx, task):
        if not page.endswith(".md") or not safefs.is_file(ctx.notes_path, page):
            continue
        old = base(page)
        if old is None:
            continue
        old = old.decode("utf-8", "replace")
        new = safefs.read_text(ctx.notes_path, page)
        if not any(markers.is_notice(name) for text in (old, new) for _, _, name in markers.spans(text)):
            continue
        def clean(text):
            names = {name for _, _, name in markers.spans(text) if markers.is_notice(name)}
            return re.sub(r"\n{2,}", "\n\n", markers.remove(text, names)).strip()
        if old != new and clean(old) == clean(new):
            notice_only.add(page)
    changed = set(steps.changed_paths(ctx, task)) - notice_only
    warnings = [{**i, "severity": "warning"} for i in items
                if i["file"] in notice_only and i.get("target") not in changed]
    if warnings:
        saved = task.get("browser_warnings", [])
        saved = ordered([dict(i) for i in {str(sorted(i.items())): i for i in saved + warnings}.values()])
        task.update(browser_warnings=saved)
        ctx.log.event("site.browser_warning", "warning", items=warnings)
    return [i for i in items if {**i, "severity": "warning"} not in warnings]
