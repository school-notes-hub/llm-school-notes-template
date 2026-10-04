"""P4: one subject-scoped fix pass, with an atomic snapshot receipt for rollback."""

import copy

from ..llm import launch

from ..review import files, relations
from ..sources import calls
from ..state import phase, safefs
from ..state.errors import BadWork, Transient, WaitingQuota
from ..wiki import frontmatter
from . import checks, handlers, inspection, steps, writer

PREFIXES = ("wiki", "docs", "publication", "tools", ".school-notes")


def all_items(ctx, task):
    path = task.get("inspection_report")
    if not path:
        return []
    text = safefs.read_text(ctx.notes_path, path)
    items = frontmatter.split(text).meta.get("items", {})
    pages = {p for u in task.get("inspection_units", []) for p in u["pages"]}
    selected = [{"file": path, "item_id": key, "status": status,
                 "round": relations.details(text, key)["round"],
                 "chain": relations.details(text, key)["chain"], "key": path + "#" + key}
                for key, status in items.items() if status == "open" and relations.details(text, key)["chain"] == 0
                and (not relations.details(text, key).get("outside_assignment")
                     or relations.details(text, key).get("file") in pages)]
    return selected


def assigned(ctx, task):
    # P1 and P4 share the run's closure capacity.
    selected = all_items(ctx, task)
    used = sum(c["status"] != "open" for c in task.get("inspection_result", {}).get("review_closure", []))
    return calls.select_reviews(selected, max(0, ctx.cfg.limits.review_closures_per_run - used))


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


def child_task(ctx, task, root, items):
    child = phase.load(root / "writer")
    if child is not None:
        return child
    data = copy.deepcopy(task.data)
    data.update(run_id=f"{task.run_id}-fix-a{task.get('attempt', 1)}", mode="cron", phase="writing")
    child = phase.Task(root / "writer", data)
    grouping = calls.assignments(ctx.notes_path, [], [], items, [], review_limit=len(items))
    child.data["data"].update(mode="fix", packages=[], pages=[], calls=grouping,
                               ranges=calls.ranges(grouping), writing_k=1, open_review_items=items,
                               pending_images=[], pending_figures=[], skip_writer=False, effective_result=None,
                               correction_parent=task.run_id, correction_before=str(root / "before"),
                               paid_disabled=task.get("mode") == "repair")
    if task.mode == "interactive":
        child.data["mode"] = "interactive"
        child.data["data"].update(calls=[], ranges=[[0, 0]], writer_check={"count": 0, "warnings": []})
    child.dir.mkdir(parents=True, exist_ok=True)
    child.save()
    return child


def run(ctx, task, edits=None):
    root = inspection.folder(task) / "correction"
    root.mkdir(parents=True, exist_ok=True)
    saved = safefs.read_json(root, "receipt.json")
    if saved is None:
        items = assigned(ctx, task)
        task.update(correction_items=items)
        if not items:
            saved = {"status": "done", "result": {"status": "done"}}
        else:
            snapshot(ctx.notes_path, root)
            child = child_task(ctx, task, root, items)
            try:
                if task.mode == "interactive":
                    from . import correction_chat
                    result = correction_chat.result(ctx, child)
                    if result is None:
                        return correction_chat.handoff(ctx, items)
                else:
                    outcome = writer.run_ranges(ctx, child, handlers.build(ctx, child.dir))
                    if outcome == "question":
                        raise BadWork("fix pass asked a blocking question")
                    result = writer.merge(writer.results(child))
                saved = validated(ctx, child, root, items, result)
            except WaitingQuota:
                raise
            except launch.TimedOut as exc:
                saved = {"status": "rollback", "reason": str(exc)}
                if exc.details.get("count", 0) >= 2 or exc.details.get("suspended"):
                    safefs.write_json(root, "receipt.json", saved)
                    apply(ctx, task, root, saved, edits)
                    raise
            except steps.CheckFailed as exc:
                saved = {"status": "rollback", "reason": str(exc), "items": exc.items[:10]}
            except (BadWork, Transient) as exc:
                saved = {"status": "rollback", "reason": str(exc)}
        if saved["status"] == "rollback" and task.mode == "interactive":
            from .correction_backup import rejected
            rejected(ctx.notes_path, root, PREFIXES, ctx.log)
            saved["rejected_patch"] = (root / "rejected.patch").relative_to(task.dir).as_posix()
        safefs.write_json(root, "receipt.json", saved)
    apply(ctx, task, root, saved, edits)


def apply(ctx, task, root, saved, edits=None):
    if saved["status"] == "rollback":
        before = steps.llm_snapshot(ctx, task) if edits is not None else None
        restore(ctx.notes_path, root)
        if edits is not None:
            edits["restores"].append((before, steps.llm_snapshot(ctx, task)))
        task.update(correction_result={"status": "done"}, correction_rolled_back=True,
                    correction_rollback_reason=saved["reason"], correction_rollback_items=saved.get("items", []),
                    correction_rejected_patch=saved.get("rejected_patch"))
        return
    if task.mode == "interactive":
        from . import correction_chat
        correction_chat.restore_inputs(ctx, task)
    result = saved["result"]
    state = saved.get("tool_state", {})
    task.update(**state)
    outcome = files.apply_closure(ctx.notes_path, f"{task.run_id}-fix-a{task.get('attempt', 1)}", result.get("review_closure", []),
                                  task.get("correction_items", []), ctx.cfg.limits.owner_after_open)
    steps.record_tool_files(task, ctx.notes_path, outcome.written)
    from ..figures import commissions
    figures = {s["brief"]["id"]: s for s in task.get("inspection_figures", [])}
    for brief in commissions.validate_assignments(ctx.notes_path, result.get("figures", [])):
        figures[brief["id"]] = {"brief": brief}
    for state in figures.values():
        state["candidate"] = inspection.candidate_state(ctx, task, state["brief"])
    task.update(correction_result=result, correction_rolled_back=False,
                correction_warnings=saved.get("warnings", []),
                inspection_figures=[figures[k] for k in sorted(figures)])


def validated(ctx, child, root, items, result):
    """Both writers enter the same result, scope, path and content gates."""
    _scope(ctx, root, items)
    problems = checks.accounting(child, result)
    if problems:
        raise steps.CheckFailed(problems)
    from . import fetch
    from ..wiki.check_result import check_result
    supplied = fetch.fetch_json(child, 1, grade=ctx.student.grade, whole_run=True)
    problems = check_result(ctx.notes_path, result, supplied,
                            {(i["file"], i["item_id"]) for i in items}, len(items),
                            base_content=steps.base_reader(ctx, child))
    if problems:
        raise steps.CheckFailed(problems)
    steps.guard_step(ctx, child)
    steps.check_changed(ctx, child, result=result)
    if result["status"] != "done":
        raise BadWork("fix pass asked a blocking question")
    return {"status": "done", "result": result, "warnings": child.get("check_warnings", []),
            "tool_state": {k: child.get(k, {}) for k in ("tool_writes", "tool_parts", "tool_hashes")}}


def _scope(ctx, root, items):
    allowed = {i.get("file") for i in items}  # Report paths are tool-owned, never writable.
    allowed.update(relations.details(safefs.read_text(ctx.notes_path, i["file"]), i["item_id"]).get("file")
                   for i in items)
    before = set(safefs.read_json(root, "snapshot.json"))
    for path in sorted(before | set(safefs.walk_files(ctx.notes_path, "wiki"))):
        if not path.startswith("wiki/") or path.startswith("wiki/assets/") or path == "wiki/log.md":
            continue
        old = safefs.read_bytes(root, "before/" + path) if path in before else b""
        new = safefs.read_bytes(ctx.notes_path, path) if safefs.is_file(ctx.notes_path, path) else b""
        if path not in allowed and steps._llm_hash(path, old) != steps._llm_hash(path, new):
            raise BadWork(f"fix changed an unassigned page: {path}")


def needs_recheck(ctx, task):
    if any(c["status"] in ("fixed", "disagree") for c in task.get("correction_result", {}).get("review_closure", [])):
        return True
    return bool(changed_figures(ctx, task))


def changed_figures(ctx, task):
    from ..figures import commissions, context
    changed = []
    for state in task.get("inspection_figures", []):
        brief = state["brief"]
        candidate = commissions.candidate(ctx.notes_path, brief)
        if candidate["state"] != "candidate":
            continue
        receipt = task.get("inspection_receipts", {}).get(brief["id"], {})
        previous = next((v["key"] for v in receipt.get("review", {}).get("figures", []) if v["id"] == brief["id"]), None)
        if context.verdict_key(ctx.notes_path, brief, candidate) != previous:
            changed.append(brief)
    return changed
