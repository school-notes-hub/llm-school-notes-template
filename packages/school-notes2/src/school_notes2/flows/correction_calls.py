"""Isolate fix call failures; prior successful calls survive a bounded retry."""

import copy
import shutil

from ..state import safefs
from . import correction, steps


def isolated(task):
    return task.get("mode") == "fix" and task.mode != "interactive" and bool(task.get("calls"))


def run(ctx, task, k, invoke):
    root = task.dir / f"call-{k}"
    correction.snapshot(ctx.notes_path, root)
    if not safefs.is_file(root, "task.json"):
        safefs.write_json(root, "task.json", task.data["data"])
    while True:
        failure = safefs.read_json(root, "failure.json")
        if failure:
            if not failure.get("restored"):
                # A 2.5.0 receipt (no `unusable` key) was a check failure: keep the work too.
                if failure.get("unusable"):
                    restore(ctx, task, root, failure)
                else:
                    continue_work(ctx, task, root, failure)
            if failure["count"] >= 2:
                candidate = safefs.read_json(root, "candidate.json")
                if not failure.get("unusable") and candidate is not None:
                    from . import machine_findings
                    machine_findings.record(ctx, task, failure["items"])
                    return candidate
                return failed_result(task, k)
        try:
            return invoke()
        except steps.CheckFailed as exc:
            steps.checks.record_failure(ctx, task, exc, "writer.check_preserved")
            from ..wiki.check import SECRET_MESSAGE
            unusable = any(i["message"].startswith(SECRET_MESSAGE + " ") for i in exc.items)
            safefs.write_json(root, "failure.json", {
                "count": (failure or {}).get("count", 0) + 1, "items": exc.items,
                "preserve": not unusable, "unusable": unusable})
        except (steps.BadWork, ValueError) as exc:
            # Only an invalid result.json is unusable output; any other writer failure
            # keeps the call's files and continues (fix-45: no discard, no stop).
            from ..schemas import validate
            try:
                validate("result", safefs.read_json(ctx.notes_path, ".school-notes/result.json"))
            except ValueError:
                unusable = True
            else:
                unusable = False
            ctx.log.event("writer.call_failed", reason=str(exc)[:300], call=k, unusable=unusable)
            safefs.write_json(root, "failure.json", {
                "count": (failure or {}).get("count", 0) + 1, "items": [],
                "preserve": not unusable, "unusable": unusable})


def continue_work(ctx, task, root, failure):
    counts = dict(task.get("fix_calls", {}))
    counts[str(task.get("writing_k", 1))] = 0
    task.update(writer_output_key=None, fix_calls=counts, writer_check={"count": 0, "warnings": []})
    safefs.unlink(ctx.notes_path, ".school-notes/result.json")
    steps.write_check_items(ctx, failure["items"])
    safefs.write_json(root, "failure.json", {**failure, "restored": True})


def cleanup(task, k):
    """Only a durable result permits deleting the call rollback, including on resume."""
    root = task.dir / f"call-{k}"
    if root.exists():
        shutil.rmtree(root)


def restore(ctx, task, root, failure):
    ctx.log.event("writer.unusable_rollback", reason="unusable output", call=task.get("writing_k", 1))
    correction.restore(ctx.notes_path, root)
    before = safefs.read_json(root, "task.json")
    # Invocation identities and assigned work remain monotonic across a rollback.
    kept = {key: task.get(key) for key in ("writer_invocation", "assigned_work", "failed_fix_calls")
            if task.get(key) is not None}
    task.data["data"] = {**copy.deepcopy(before), **kept}
    counts = dict(task.get("fix_calls", {}))
    counts[str(task.get("writing_k", 1))] = 0
    task.update(writer_output_key=None, fix_calls=counts, writer_check={"count": 0, "warnings": []})
    safefs.unlink(ctx.notes_path, ".school-notes/result.json")
    steps.write_check_items(ctx, failure["items"])
    safefs.write_json(root, "failure.json", {**failure, "restored": True})


def failed_result(task, k):
    assigned = task.get("calls", [])
    call = assigned[k - 1] if k <= len(assigned) else {}
    task.update(failed_fix_calls=sorted(set(task.get("failed_fix_calls", [])) | {k}))
    return {"status": "done", "review_closure": [
        {"file": i["file"], "item_id": i["item_id"], "status": "open",
         "note": "A hívás kétszer hibás kimenetet adott; a tétel nyitva maradt."}
        for i in call.get("open_review_items", [])]}


def successful_fetch(ctx, task, supplied):
    """Failed calls have no accepted figure/infographic output to validate."""
    from . import fetch
    failed = task.get("failed_fix_calls", [])
    if not failed:
        return supplied
    successful = [fetch.fetch_json(task, k, grade=ctx.student.grade, repo=ctx.notes_path)
                  for k in range(1, len(task.get("calls")) + 1) if k not in failed]
    items = {(i["file"], i["item_id"]) for f in successful for i in f["open_review_items"]}
    figures = {e["commission"]["id"] for f in successful for e in f.get("pending_figures", [])}
    pages = {p for f in successful for p in f.get("infographic_pages", [])}
    return {**supplied, "open_review_items": [i for i in supplied["open_review_items"]
                                            if (i["file"], i["item_id"]) in items],
            "pending_figures": [e for e in supplied.get("pending_figures", [])
                                           if e["commission"]["id"] in figures],
            **({"infographic_pages": [p for p in supplied["infographic_pages"] if p in pages]}
               if "infographic_pages" in supplied else {})}


def failed_keys(task):
    calls = task.get("calls", [])
    return sorted({i["file"] + "#" + i["item_id"] for k in task.get("failed_fix_calls", [])
                   for i in calls[k - 1].get("open_review_items", [])})
