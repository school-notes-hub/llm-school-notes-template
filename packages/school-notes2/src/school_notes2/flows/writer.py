"""The writer call per range (plan 5.3): fetch.json, changes.json, fixed prompt, result."""


from ..git import workbranch
from ..llm import launch
from ..mcp.jobs import JobStore
from ..schemas import validate
from ..state.errors import BadWork, Transient, WaitingQuota
from ..state import safefs
from ..state.files import read_json, write_json
from ..state.phase import Task
from . import generation_receipts
from . import call_scope, checks
from . import fetch as fetch_flow
from .context import Ctx
from .session import mcp


def write_inputs(ctx: Ctx, task: Task, k: int) -> None:
    """fetch.json and changes.json for range k; the old result.json is removed (5.3)."""
    from ..figures import licenses, rechecks
    licenses.preflight(ctx.notes_path)
    root, workdir = ctx.notes_path, workbranch.WORKDIR
    fetch = fetch_flow.fetch_json(task, k, grade=ctx.student.grade, repo=ctx.notes_path)
    if task.get("assigned_work") is not None:
        from .fix_progress import keys
        task.update(assigned_work=sorted(set(task.get("assigned_work")) |
                    set(keys(fetch.get("open_review_items", []), fetch.get("pending_figures", [])))))
    rechecks.record(ctx, task, fetch.get("pending_figures", []))
    safefs.write_json(root, f"{workdir}/fetch.json", fetch)
    write_changes(ctx, task)
    call_scope.write_check(ctx, task, k)
    safefs.unlink(root, f"{workdir}/result.json")


def write_changes(ctx: Ctx, task: Task) -> None:
    from .steps import base_of
    changed = workbranch.changed_files(ctx.worktree("notes"), base_of(task))
    data = {"base": task.get("base"), "changed": changed}
    validate("changes", data)
    safefs.write_json(ctx.notes_path, f"{workbranch.WORKDIR}/changes.json", data)


def run_ranges(ctx: Ctx, task: Task, handlers) -> str:
    """Call the writer for each remaining range; returns 'done' or 'question'."""
    from . import correction_calls
    role, harness = ctx.cfg.role("writer")
    if task.get("max_agents") is None:
        task.update(max_agents=ctx.cfg.limits.max_agents)
    from . import writer_identity
    writer_identity.ensure(ctx, task)
    call_scope.invalidate(task)
    n = len(task.get("ranges"))
    k = task.get("writing_k", 1)
    while k <= n:
        task.set_phase("writing", writing_k=k)
        result = read_json(task.dir / f"result-{k}.json")
        if result is None or result["status"] == "question":
            if correction_calls.isolated(task):
                result = correction_calls.run(ctx, task, k, lambda: _range(ctx, task, k, role, harness, handlers))
            else:
                result = _range(ctx, task, k, role, harness, handlers)
            from ..figures import infographics
            infographics.remember(task, result, ctx.notes_path)
            write_json(task.dir / f"result-{k}.json", result)
        if result["status"] == "done":
            correction_calls.cleanup(task, k)
        from . import fix_scope
        fix_scope.recover(ctx, task)
        if not correction_calls.isolated(task):
            fix_scope.check_dependencies(ctx, task)
        if result["status"] == "question":
            task.update(question=result.get("questions", []))
            return "question"
        k += 1
        task.update(writing_k=k)
    return "done"


def _range(ctx, task, k, role, harness, handlers):
    from . import correction_calls, steps, fix_scope, writer_identity
    result = _fix_resume(ctx, task, k) if task.get("mode") == "fix" else None
    if result is None:
        write_inputs(ctx, task, k)
        result = _invoke(ctx, task, k, role, harness, handlers)
    writer_identity.remember(ctx, task, k, result)
    fix_scope.recover(ctx, task)
    try:
        _check_call(ctx, task, k, result)
        if not correction_calls.isolated(task):
            fix_scope.check_dependencies(ctx, task)
    except steps.CheckFailed as exc:
        steps.write_check_items(ctx, exc.items)
        raise
    return result


def _call(ctx: Ctx, task: Task, k: int, role, harness, handlers) -> dict:
    checks.begin(task)
    with mcp(ctx, task.dir, "cron", handlers, lambda: task.run_id) as sessdir:
        run = launch.RoleRun(
            learner=ctx.name, run_id=task.run_id, role_name="fix" if task.get("mode") == "fix" else "writer", role=role,
            harness=harness, image=ctx.image_tag(),
            mounts=launch.Mounts(work=ctx.notes_path, sessdir=sessdir),
            output_host=ctx.notes_path / workbranch.WORKDIR / "result.json",
            schema="result", task_dir=task.dir, grade=ctx.student.grade, label=str(k),
            allowed_domains=ctx.cfg.provider_domains,
            max_agents=task.get("max_agents", ctx.cfg.limits.max_agents), lease_dir=ctx.cfg.state_dir / "agent-leases")
        try:
            outcome = launch.run_headless(
                run, log=ctx.log, snapshot=lambda: launch.tree_fingerprint(ctx.notes_path))
        finally:
            # A job the writer left behind (check, image) must not run beside finish.
            JobStore(task.dir / "jobs", ctx.log).stop_all(30)
            # The MCP handlers saved the run meanwhile (tool writes, closures); a later save
            # from this stale copy would drop them.
            task.reload()
    from . import steps
    from . import writer_identity
    writer_identity.remember(ctx, task, k, outcome.output)
    from . import fix_scope
    fix_scope.recover(ctx, task)
    problems = checks.accounting(task, outcome.output)
    if problems:
        steps.write_check_items(ctx, problems)
        raise steps.CheckFailed(problems)
    return outcome.output


def results(task: Task, required: bool = True) -> list[dict]:
    """The saved result-<k>.json files in range order (all of them when `required`)."""
    out = []
    for k in range(1, len(task.get("ranges")) + 1):
        data = read_json(task.dir / f"result-{k}.json")
        if data is None:
            if not required:
                continue
            raise BadWork(f"result-{k}.json is missing")
        validate("result", data)
        out.append(data)
    return out


def merge(results_: list[dict]) -> dict:
    """4.5: notes by file with page union, closures last-wins per item, lists concatenated."""
    notes: dict[str, set] = {}
    closures: dict[tuple, dict] = {}
    lists = ("questions", "new_subjects", "checks", "owner_notes", "figures",
             "notebook_drawings", "figure_requests", "warnings", "coverage", "infographic_decisions")
    merged = {"status": "done", **{key: [] for key in lists}}
    for r in results_:
        if r["status"] == "question":
            merged["status"] = "question"
        for key in lists:
            merged[key] += r.get(key, [])
        for note in r.get("notes", []):
            notes.setdefault(note["file"], set()).update(note["pages"])
        for c in r.get("review_closure", []):
            closures[(c["file"], c["item_id"])] = c
    merged["notes"] = [{"file": f, "pages": sorted(p)} for f, p in sorted(notes.items())]
    merged["review_closure"] = [closures[k] for k in sorted(closures)]
    warnings = {w["id"]: w for w in merged["warnings"]}
    merged["warnings"] = [warnings[k] for k in sorted(warnings)]
    decisions = {d["page"]: d for d in merged["infographic_decisions"]}
    merged["infographic_decisions"] = [decisions[p] for p in sorted(decisions)]
    return merged


def _check_call(ctx, task, k, result):
    from . import steps
    from ..wiki.check_result import check_result
    validate("result", result)
    if result["status"] == "question":
        return
    fetch = fetch_flow.fetch_json(task, k, grade=ctx.student.grade, repo=ctx.notes_path)
    listed = {(i["file"], i["item_id"]) for i in fetch["open_review_items"]}
    problems = check_result(ctx.notes_path, result, fetch, listed,
                            ctx.cfg.limits.review_closures_per_run, whole_run=False,
                            base_content=steps.base_reader(ctx, task),
                            generated=lambda rel: generation_receipts.rights(ctx)(rel))
    for operation in (lambda: steps.guard_step(ctx, task),
                      lambda: steps.check_changed(ctx, task, result=result)):
        try:
            operation()
        except steps.CheckFailed as exc:
            problems += exc.items
    problems += steps.order_step(ctx, task)
    problems = call_scope.current(ctx, task, problems, k)
    if problems:
        raise steps.CheckFailed(problems)


def _fix_resume(ctx, task, k):
    """Recover a fix output before write_inputs removes it; one crash retry at most."""
    state = dict(task.get("fix_calls", {}))
    count = state.get(str(k), 0)
    rejected = task.get("writer_output_key") in task.get("counted_bad_outputs", [])
    if count and not rejected:
        result = safefs.read_json(ctx.notes_path, ".school-notes/result.json")
        try:
            validate("result", result)
        except ValueError:
            if count >= 2:
                raise BadWork("fix call interrupted twice without valid output") from None
        else:
            from . import fix_scope
            fix_scope.recover(ctx, task)
            problems = checks.accounting(task, result)
            if problems:
                from .steps import CheckFailed
                raise CheckFailed(problems)
            return result
    if not count:
        safefs.unlink(ctx.notes_path, ".school-notes/result.json")
    if count >= 2:
        raise BadWork("fix call interrupted twice without valid output")
    state[str(k)] = count + 1
    task.update(fix_calls=state)
    return None


def _invoke(ctx, task, k, role, harness, handlers):
    task.update(writer_invocation=task.get("writer_invocation", 0) + 1)
    try:
        try:
            return _call(ctx, task, k, role, harness, handlers)
        except Transient:
            if task.get("mode") != "fix":
                raise
            retried = task.get("fix_crash_retries", [])
            if k in retried:
                raise
            task.update(fix_crash_retries=sorted(retried + [k]))
            return _call(ctx, task, k, role, harness, handlers)
    except BadWork:
        from . import writer_identity
        path = ".school-notes/result.json"
        raw = safefs.read_text(ctx.notes_path, path) if safefs.is_file(ctx.notes_path, path) else None
        writer_identity.remember(ctx, task, k, raw)
        raise
    except (WaitingQuota, launch.TimedOut):
        # Quota waits and T-125 have their own retry policy; never consume the
        # correction's crash budget or recover a failed call's partial output.
        if task.get("mode") == "fix":
            counts = dict(task.get("fix_calls", {}))
            counts[str(k)] = max(0, counts.get(str(k), 0) - 1)
            safefs.unlink(ctx.notes_path, ".school-notes/result.json")
            task.update(fix_calls=counts)
        raise
