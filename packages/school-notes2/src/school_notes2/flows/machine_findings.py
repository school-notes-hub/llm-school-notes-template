"""Durable machine errors join the next correction round; publication still checks."""

import hashlib
import json

from ..reader import report
from ..review import files, relations
from ..state import safefs
from . import checks, inherited_check, steps


def record(ctx, task, problems):
    problems = checks.ordered(problems)
    if not problems:
        return
    path = task.get("inspection_report") or f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    known = relations.inventory(ctx.notes_path)["items"]
    active = {i.get("hit_id") for i in known.values() if i.get("status") in ("open", "owner")}
    findings = []
    for problem in problems:
        if not problem["file"].startswith("wiki/") or problem.get("severity", "error") != "error":
            continue  # Only wiki pages are fixed in a writer round; the rest stays in machine_problems.
        # The line is not part of the key: an edit above the error must not make a new item.
        stable = {"file": problem["file"], "message": problem["message"]}
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = "machine-check:" + digest
        if key in active:
            continue
        active.add(key)
        findings.append({"file": problem["file"], "quote": inherited_check.quote(ctx.notes_path, problem),
                         "problem": problem["message"], "category": "szerkezeti", "severity": "hiba",
                         "origin": "check", "chain": 1, "relates_to": None, "hit_id": key})
    pending = {json.dumps(i, sort_keys=True): i for i in task.get("machine_problems", []) + problems}
    task.update(machine_problems=checks.ordered(list(pending.values())))
    if not findings:
        return
    if not safefs.is_file(ctx.notes_path, path):
        files.write_review(ctx.notes_path, task.data["created"][:10], {"verdict": "ok", "findings": []},
                           "check", task.get("base"), task.get("base"), path=ctx.notes_path / path)
    label = "machine-check:" + hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()
    report.append(ctx.notes_path, path, findings, [], label)
    task.update(inspection_report=path)
    steps.record_tool_files(task, ctx.notes_path, [path])
