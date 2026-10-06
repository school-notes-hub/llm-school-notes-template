"""Machine errors the writer left on wiki pages become items for the next run."""

import hashlib
import json

from ..reader import report
from ..review import files, relations
from ..state import safefs
from . import checks, journal


def record(ctx, task, problems):
    problems = checks.ordered(problems)
    if not problems:
        return
    known = relations.inventory(ctx.notes_path)["items"]
    active = {i.get("hit_id") for i in known.values() if i.get("status") in ("open", "owner")}
    findings = []
    for problem in problems:
        if not problem["file"].startswith("wiki/") or problem.get("severity", "error") != "error":
            continue  # Only wiki pages are fixed by a writer; the rest is logged.
        # The line is not part of the key: an edit above the error must not make a new item.
        stable = {"file": problem["file"], "message": problem["message"]}
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = "machine-check:" + digest
        if key in active:
            continue
        active.add(key)
        findings.append({"file": problem["file"], "line": problem.get("line"), "quote": quote(ctx.notes_path, problem),
                         "problem": problem["message"], "category": "szerkezeti", "severity": "hiba",
                         "origin": "check", "chain": 1, "relates_to": None, "hit_id": key})
    others = [p for p in problems if not p["file"].startswith("wiki/")]
    if others:
        ctx.log.event("check.not_items", "warning", items=others[:20])
    append(ctx, task, findings)


def append(ctx, task, findings):
    """The findings become items of this run's report (created when missing)."""
    if not findings:
        return
    path = task.get("inspection_report") or f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    # Recorded before each write (journal), so a crash can never restore it away.
    write = lambda repo, rel, text: journal.write(ctx, task, rel, text, whole=True)
    journal.settle(ctx, task)
    if not safefs.is_file(ctx.notes_path, path):
        files.write_review(ctx.notes_path, task.data["created"][:10], {"verdict": "ok", "findings": []},
                           "check", task.get("base"), task.get("base"), path=ctx.notes_path / path, write=write)
    label = "machine-check:" + hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()
    report.append(ctx.notes_path, path, findings, [], label, write=write)
    task.update(inspection_report=path)


def quote(repo, problem):
    n = problem.get("line")
    if not n:
        return ""
    lines = safefs.read_text(repo, problem["file"]).splitlines() if safefs.is_file(repo, problem["file"]) else []
    return lines[n - 1] if 0 < n <= len(lines) else ""
