"""P4: one subject-scoped fix pass, with an atomic snapshot receipt for rollback."""

import copy

from ..review import files, relations
from ..sources import calls
from ..state import phase, safefs
from ..state.errors import BadWork, Transient, WaitingQuota
from ..wiki import frontmatter
from . import handlers, inspection, steps, writer

PREFIXES = ("wiki", "docs", "publication", "tools", ".school-notes")


def all_items(ctx, task):
    path = task.get("inspection_report")
    if not path:
        return []
    text = safefs.read_text(ctx.notes_path, path)
    items = frontmatter.split(text).meta.get("items", {})
    selected = [{"file": path, "item_id": key, "status": status,
                 "round": relations.details(text, key)["round"],
                 "chain": relations.details(text, key)["chain"], "key": path + "#" + key}
                for key, status in items.items() if status == "open" and relations.details(text, key)["chain"] == 0]
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
                               pending_images=[], skip_writer=False, effective_result=None,
                               correction_parent=task.run_id, correction_before=str(root / "before"),
                               paid_disabled=task.get("mode") == "repair")
    child.dir.mkdir(parents=True, exist_ok=True)
    child.save()
    return child


def run(ctx, task):
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
                outcome = writer.run_ranges(ctx, child, handlers.build(ctx, child.dir))
                if outcome == "question":
                    raise BadWork("fix pass asked a blocking question")
                result = writer.merge(writer.results(child))
                _scope(ctx, root, items)
                # Validate/check first; persist before applying any closure.
                steps.guard_step(ctx, child)
                steps.check_changed(ctx, child, result=result)
                saved = {"status": "done", "result": result, "warnings": child.get("check_warnings", []),
                         "tool_state": {k: child.get(k, {}) for k in ("tool_writes", "tool_parts", "tool_hashes")}}
            except WaitingQuota:
                raise
            except (BadWork, Transient) as exc:
                saved = {"status": "rollback", "reason": str(exc)}
        safefs.write_json(root, "receipt.json", saved)
    if saved["status"] == "rollback":
        restore(ctx.notes_path, root)
        task.update(correction_result={"status": "done"}, correction_rolled_back=True)
        return
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
