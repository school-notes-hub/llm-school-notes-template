"""One writer call with one failure counter; a failed call never takes other work with it.

After a failure the writer continues once on its own files with the error list (check.json,
also a result.json schema error). Only output that is still unusable after that – a secret,
metadata or block markers the tool cannot process, a path-guard violation – is undone, from
the call's pre-call bytes. A missing or invalid result.json never undoes the wiki edits: the
call's items stay open and the content check and the recheck judge the files. Other remaining
errors become items for the next run and the call's work is kept. A call that failed twice
leaves its items open; the rest of the run goes on."""

import shutil

from ..llm import launch
from ..state import safefs
from ..state.errors import BadWork, WaitingQuota
from . import steps

PREFIXES = ("wiki", "docs", "publication", "tools", ".school-notes")
LIMIT = 2


def isolated(task):
    return task.get("mode") == "fix" and task.mode != "interactive" and bool(task.get("calls"))


def snapshot(repo, root):
    root.mkdir(parents=True, exist_ok=True)
    saved = safefs.read_json(root, "snapshot.json")
    if saved is not None:
        return saved
    paths = sorted({p for prefix in PREFIXES for p in safefs.walk_files(repo, prefix)})
    for path in paths:
        safefs.write_bytes(root, "before/" + path, safefs.read_bytes(repo, path))
    safefs.write_json(root, "snapshot.json", paths)
    return paths


def restore(repo, root):
    paths = safefs.read_json(root, "snapshot.json")
    current = {p for prefix in PREFIXES for p in safefs.walk_files(repo, prefix)}
    for path in sorted(current - set(paths)):
        safefs.unlink(repo, path)
    for path in paths:
        safefs.write_bytes(repo, path, safefs.read_bytes(root, "before/" + path))


def run(ctx, task, k, invoke, recover):
    """`invoke()` runs the writer and checks its output; `recover()` checks a result.json
    left by an interrupted call (None when there is none)."""
    root = task.dir / f"call-{k}"
    snapshot(ctx.notes_path, root)
    state = safefs.read_json(root, "call.json")
    if state is None:  # A 2.5.x call interrupted mid-way left only its old crash counter.
        state = {"failures": 0, "running": bool(task.get("fix_calls", {}).get(str(k))), "items": []}
    candidate = None
    if state["running"]:  # Interrupted (crash, kill, transient): reuse valid output first.
        state["running"] = False
        try:
            candidate = recover()
        except steps.CheckFailed as exc:
            state = _failed(ctx, root, state, exc.items, unusable=_unusable(exc.items))
            if not state["unusable"]:
                safefs.write_json(root, "candidate-kept.json", True)
        except (BadWork, ValueError) as exc:
            items = [_result_error(exc)] + _file_problems(ctx, task)
            state = _failed(ctx, root, state, items, unusable=_unusable(items))
        else:
            if candidate is None:
                state = _failed(ctx, root, state, [], unusable=False)
            else:
                return _done(root, state, candidate)
    while state["failures"] < LIMIT:
        safefs.write_json(root, "call.json", {**state, "running": True})
        try:
            result = invoke()
        except steps.CheckFailed as exc:
            steps.checks.record_failure(ctx, task, exc, "writer.check_preserved")
            state = _failed(ctx, root, state, exc.items, unusable=_unusable(exc.items))
            if not state["unusable"]:
                safefs.write_json(root, "candidate-kept.json", True)
        except (BadWork, ValueError) as exc:
            ctx.log.event("writer.call_failed", reason=str(exc)[:300], call=k)
            items = [_result_error(exc)] + _file_problems(ctx, task)
            state = _failed(ctx, root, state, items, unusable=_unusable(items))
        except launch.TimedOut as exc:
            if not isolated(task) or exc.details.get("suspended") or exc.details.get("count", 0) >= 2:
                safefs.write_json(root, "call.json", {**state, "running": False})
                raise  # The timeout policy: retry in a later round; two in a row stop for the owner.
            ctx.log.event("writer.call_timeout", call=k)
            state = {**state, "failures": LIMIT, "running": False, "unusable": False}
            safefs.write_json(root, "call.json", state)
        except WaitingQuota:
            safefs.write_json(root, "call.json", {**state, "running": False})
            raise
        else:
            if result.get("status") == "question" and isolated(task):
                ctx.log.event("writer.call_question", call=k, questions=result.get("questions", []))
                return _done(root, state, asked_result(task, k, result.get("questions", [])))
            return _done(root, state, result)
    candidate = safefs.read_json(root, "candidate.json") if safefs.is_file(root, "candidate-kept.json") else None
    if candidate is not None and not state.get("unusable"):
        from . import machine_findings
        machine_findings.record(ctx, task, state["items"])
        return _done(root, state, candidate)
    if not isolated(task):
        from ..state.errors import NeedsOwner
        # A continued run starts this call afresh, on the files as they are now.
        safefs.write_json(root, "call.json", {**state, "failures": 0, "running": False})
        kept = ("its unusable output was undone (secret, metadata, block markers or path guard); "
                "its other files are as before the call") if state.get("unusable") else "its files are kept"
        raise NeedsOwner(f"the writer call failed twice; {kept}",
                         todo="continue the run in `school-notes chat`", details={"items": state["items"][:20]})
    return _done(root, state, failed_result(task, k, "A hívás kétszer sikertelen volt; a tétel nyitva maradt."))


def _unusable(items):
    from ..wiki.check import blocking
    return bool(blocking(items))


def _file_problems(ctx, task):
    """The call's files are judged on their own when its result.json is unusable: only a
    blocking problem among them (secret, metadata, markers, path guard) undoes them."""
    problems = []
    for operation in (lambda: steps.guard_step(ctx, task), lambda: steps.check_changed(ctx, task)):
        try:
            operation()
        except steps.CheckFailed as exc:
            problems += exc.items
    return problems


def _result_error(exc):
    """The result.json problem, in check.json form, for the writer's second attempt."""
    from ..wiki.check import item
    return item(".school-notes/result.json", None, f"result.json: {exc}"[:2000])


def _failed(ctx, root, state, items, *, unusable):
    """Count the failure; undo output only if it is still unusable at the last attempt."""
    if unusable and state["failures"] + 1 >= LIMIT:
        ctx.log.event("writer.unusable_rollback", call=root.name)
        restore(ctx.notes_path, root)
        safefs.unlink(root, "candidate-kept.json")
    safefs.unlink(ctx.notes_path, ".school-notes/result.json")
    steps.write_check_items(ctx, items)
    state = {**state, "failures": state["failures"] + 1, "running": False, "items": items, "unusable": unusable}
    safefs.write_json(root, "call.json", state)
    return state


def _done(root, state, result):
    safefs.write_json(root, "call.json", {**state, "running": False, "done": True})
    return result


def cleanup(task, k):
    """Only a durable result permits deleting the call's pre-call bytes."""
    root = task.dir / f"call-{k}"
    if root.exists():
        shutil.rmtree(root)


def failed_result(task, k, note):
    assigned = task.get("calls", [])
    call = assigned[k - 1] if k <= len(assigned) else {}
    task.update(failed_fix_calls=sorted(set(task.get("failed_fix_calls", [])) | {k}))
    return {"status": "done", "review_closure": [
        {"file": i["file"], "item_id": i["item_id"], "status": "open", "note": note}
        for i in call.get("open_review_items", [])]}


def asked_result(task, k, questions):
    """The writer asked instead of fixing: the call's items wait for the owner with the
    question (`asked_items`, applied by the closure step), so no later run asks it again."""
    text = " ".join(" ".join(str(q.get("text", "")).split()) for q in questions).strip() or "–"
    result = failed_result(task, k, f"A jegyzetíró kérdést tett fel: {text}")
    asked = dict(task.get("asked_items", {}))
    asked.update({c["file"] + "#" + c["item_id"]: text for c in result["review_closure"]})
    task.update(asked_items=dict(sorted(asked.items())))
    return result


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
    return {**supplied, "open_review_items": [i for i in supplied["open_review_items"]
                                            if (i["file"], i["item_id"]) in items],
            "pending_figures": [e for e in supplied.get("pending_figures", [])
                                           if e["commission"]["id"] in figures]}
