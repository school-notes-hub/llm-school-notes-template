"""P4: the complete work list in resumable calls, with round-local rollback receipts."""

import copy

from ..llm import launch

from ..review import files, relations
from ..sources import calls
from ..state import phase, safefs
from ..state.errors import BadWork, Transient, WaitingQuota
from ..wiki import frontmatter
from . import correction_figures, correction_round, generation_receipts
from .correction_figures import changed_figures
from . import call_scope, checks, handlers, inspection, steps, writer

PREFIXES = ("wiki", "docs", "publication", "tools", ".school-notes")


def all_items(ctx, task):
    from ..figures import migration_gate
    from . import fix_progress
    items = [i for i in files.open_items(ctx.notes_path, "cron")
             if not migration_gate.concerns(ctx.notes_path, i)]
    return fix_progress.available(ctx, items, [])[0]


def assigned(ctx, task):
    return all_items(ctx, task)


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
    data.update(run_id=correction_round.identity(task) + ("-retry" if root.name.endswith("-retry") else ""), mode="cron", phase="writing")
    from ..log import now_iso
    data["created"] = now_iso()
    data.update(retries=0, llm_failures=0, needs_owner=None, last_error=None)
    child = phase.Task(root / "writer", data)
    waiting = task.get("correction_figures", [])
    grouping = calls.fix_assignments(ctx.notes_path, items, waiting)
    correction_figures.start(ctx.notes_path, waiting)
    child.data["data"].update(mode="fix", packages=[], pages=[], calls=grouping,
                               ranges=calls.ranges(grouping), writing_k=1, open_review_items=items,
                               pending_images=[], pending_figures=waiting, skip_writer=False, effective_result=None,
                               correction_parent=task.run_id, correction_before=str(root / "before"),
                               paid_disabled=task.get("mode") == "repair",
                               fix_calls={}, fix_crash_retries=[], writer_invocation=0, writer_output_key=None,
                               counted_bad_outputs=[], retry_calls=[], retry_items={}, retry_link_pages=[],
                               writer_check={"count": 0, "warnings": []}, fix_scope_rolled_back=False)
    if task.mode == "interactive":
        child.data["mode"] = "interactive"
        child.data["data"].update(calls=[], ranges=[[0, 0]], writer_check={"count": 0, "warnings": []})
    child.dir.mkdir(parents=True, exist_ok=True)
    child.save()
    return child


def run(ctx, task, edits=None):
    base = correction_round.root(task)
    roots = (base,) if task.get("fix_scope_rolled_back") and correction_round.number(task) == 1 else (base, base.with_name(base.name + "-retry"))
    for root in roots:
        root.mkdir(parents=True, exist_ok=True)
        saved = safefs.read_json(root, "receipt.json")
        if saved is None:
            saved = execute(ctx, task, root, edits)
            if saved is None or "status" not in saved:
                return saved
            if saved["status"] == "rollback" and task.mode == "interactive":
                from .correction_backup import rejected
                rejected(ctx.notes_path, root, PREFIXES, ctx.log)
                saved["rejected_patch"] = (root / "rejected.patch").relative_to(task.dir).as_posix()
            safefs.write_json(root, "receipt.json", saved)
        from .fix_scope import owner_notes
        owner_notes(ctx, task, root)
        # A retry snapshot proves the first rollback was already applied.
        retry = base.with_name(base.name + "-retry")
        if root == base and safefs.is_file(retry, "snapshot.json"):
            continue
        apply(ctx, task, root, saved, edits)
        if saved["status"] != "rollback" or task.mode == "interactive":
            return
    from . import set_aside
    set_aside.rollback_notice(ctx, task)


def execute(ctx, task, root, edits):
    if task.get("correction_assignment_root") != str(root):
        task.update(correction_items=assigned(ctx, task), correction_figures=correction_figures.waiting(ctx, task),
                    correction_assignment_root=str(root))
    items, waiting = task.get("correction_items"), task.get("correction_figures")
    if not items and not waiting:
        saved = {"status": "done", "result": {"status": "done"}}
    else:
        snapshot(ctx.notes_path, root)
        from .fix_scope import TOOL_STATE
        if not safefs.is_file(root, "tool-state.json"):
            safefs.write_json(root, "tool-state.json", {k: task.get(k, {}) for k in TOOL_STATE})
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
            saved = validated(ctx, child, root, items, result, edits)
        except WaitingQuota:
            raise
        except launch.TimedOut as exc:
            saved = {"status": "rollback", "reason": str(exc)}
            saved["timeout"] = True
        except steps.CheckFailed as exc:
            saved = {"status": "rollback", "reason": str(exc), "items": exc.items[:10]}
        except (BadWork, Transient) as exc:
            saved = {"status": "rollback", "reason": str(exc)}
    return saved


def apply(ctx, task, root, saved, edits=None):
    if saved["status"] == "rollback":
        from .finish import _snapshot
        before = _snapshot(ctx, task) if edits is not None else None
        restore(ctx.notes_path, root)
        if edits is not None:
            edits["restores"].append((before, _snapshot(ctx, task)))
        task.update(correction_result={"status": "done"}, correction_rolled_back=True,
                    correction_rollback_reason=saved["reason"], correction_rollback_items=saved.get("items", []),
                    correction_rejected_patch=saved.get("rejected_patch"))
        state = safefs.read_json(root, "tool-state.json", {})
        task.update(**state, learning_pending=None)
        return
    if task.mode == "interactive":
        from . import correction_chat
        correction_chat.restore_inputs(ctx, task)
    result = saved["result"]
    state = saved.get("tool_state", {})
    if task.get("correction_state_applied") != str(root):
        task.update(**state, correction_state_applied=str(root))
    from . import licensing
    licensing.refresh(ctx, task, result, task.get("pages", []))
    from ..figures import infographics
    infographics.record(ctx, task, result)
    generation_receipts.refresh(ctx, task)
    outcome = files.apply_closure(ctx.notes_path, correction_round.identity(task), result.get("review_closure", []),
                                  task.get("correction_items", []), ctx.cfg.limits.owner_after_open,
                                  automatic=task.mode == "cron")
    steps.record_tool_files(task, ctx.notes_path, outcome.written)
    apply_figures(ctx, task, root, saved)


def apply_figures(ctx, task, root, saved):
    result = saved["result"]
    from ..figures import commissions
    figures = {s["brief"]["id"]: s for s in task.get("inspection_figures", [])}
    briefs = [e["commission"] for e in task.get("correction_figures", [])]
    briefs += commissions.validate_assignments(ctx.notes_path, result.get("figures", []))
    for brief in briefs:
        figures[brief["id"]] = {**figures.get(brief["id"], {}), "brief": brief}
    attempts = task.get("correction_attempts", {})
    if str(root) not in attempts:
        assigned_ids = {f["id"] for f in result.get("figures", [])} | {
            e["commission"]["id"] for e in task.get("correction_figures", [])}
        attempts = {**attempts, str(root): {
            fid: fid in assigned_ids and correction_figures.attempted(ctx, phase.load(root / "writer") or task, state["brief"])
            for fid, state in figures.items()}}
        task.update(correction_attempts=attempts)
    for state in figures.values():
        state["attempted"] = attempts[str(root)][state["brief"]["id"]]
        state["candidate"] = inspection.candidate_state(ctx, task, state["brief"])
    task.update(correction_result=result, correction_rolled_back=False,
                correction_warnings=saved.get("warnings", []),
                inspection_figures=[figures[k] for k in sorted(figures)])


def validated(ctx, child, root, items, result, edits=None):
    """Both writers enter the same result, scope, path and content gates."""
    from .fix_scope import recover
    from .finish import _snapshot
    before = _snapshot(ctx, child) if edits is not None else None
    recover(ctx, child, root, items)
    if edits is not None:
        edits["restores"].append((before, _snapshot(ctx, child)))
    problems = checks.accounting(child, result)
    if problems:
        raise steps.CheckFailed(problems)
    from . import fetch
    from ..wiki.check_result import check_result
    supplied = fetch.fetch_json(child, 1, grade=ctx.student.grade, repo=ctx.notes_path, whole_run=True)
    problems = check_result(ctx.notes_path, result, supplied,
                            {(i["file"], i["item_id"]) for i in items}, len(items),
                            base_content=steps.base_reader(ctx, child),
                            generated=lambda rel: generation_receipts.rights(ctx)(rel))
    if problems:
        raise steps.CheckFailed(problems)
    steps.guard_step(ctx, child)
    steps.check_changed(ctx, child, result=result)
    from .fix_scope import check_dependencies
    check_dependencies(ctx, child)
    if result["status"] != "done":
        raise BadWork("fix pass asked a blocking question")
    return {"status": "done", "result": result, "warnings": child.get("check_warnings", []),
            "tool_state": {k: child.get(k, {}) for k in ("tool_writes", "tool_parts", "tool_hashes")}}


def check_scope(ctx, root, items, extra_paths=(), *, restore=False):
    from ..reader import units
    # Use the pre-edit tree: edits must not expand their own authorization.
    repo = root / "before"
    allowed = set(extra_paths)
    details = [relations.details(safefs.read_text(repo, i["file"]), i["item_id"]) for i in items]
    allowed.update(d.get("file") for d in details)
    allowed.update(_value_sources(repo, [d.get("quote") or "" for d in details]))
    embedded = relations.related_pages(repo)
    allowed.update(p for asset in sorted(p for p in allowed if p) for p in embedded.get(asset, []))
    for unit in units.collect(repo, sorted(p for p in allowed if p)):
        allowed.update(unit["pages"] + unit["context"])
    before = set(safefs.read_json(root, "snapshot.json"))
    outside = []
    for path in sorted(before | set(safefs.walk_files(ctx.notes_path, "wiki"))):
        if not path.startswith("wiki/") or path.startswith("wiki/assets/") or path == "wiki/log.md":
            continue
        old = safefs.read_bytes(root, "before/" + path) if path in before else b""
        new = safefs.read_bytes(ctx.notes_path, path) if safefs.is_file(ctx.notes_path, path) else b""
        if path not in allowed and steps._llm_hash(path, old) != steps._llm_hash(path, new):
            outside.append(path)
    if outside and not restore:
        raise BadWork(f"fix changed an unassigned page: {outside[0]}")
    if restore:
        from .fix_scope import restore_pages
        return restore_pages(ctx.notes_path, root, before, outside)
    return []


def _value_sources(repo, quotes, minimum=20):
    """Pages whose own title, description or lesson title appears in a quote: a finding on a
    generated list (an index) is fixed in that page's frontmatter (plan 8.1)."""
    from ..review import generated
    quotes = [" ".join(q.split()) for q in quotes if q.strip()]
    if not quotes:
        return set()
    return {path for path, value in generated._source_values(repo)
            if len(value.strip()) >= minimum and any(" ".join(value.split()) in q for q in quotes)}


def needs_recheck(ctx, task):
    if any(c["status"] in ("fixed", "disagree") for c in task.get("correction_result", {}).get("review_closure", [])):
        return True
    return bool(changed_figures(ctx, task))
