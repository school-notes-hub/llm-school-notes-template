"""The writer call per range (plan 5.3): fetch.json, changes.json, fixed prompt, result."""


from ..git import workbranch
from ..llm import launch
from ..mcp.jobs import JobStore
from ..schemas import validate
from ..state.errors import BadWork
from ..state import safefs
from ..state.files import read_json, write_json
from ..state.phase import Task
from . import checks
from . import fetch as fetch_flow
from .context import Ctx
from .session import mcp


def write_inputs(ctx: Ctx, task: Task, k: int) -> None:
    """fetch.json and changes.json for range k; the old result.json is removed (5.3)."""
    root, workdir = ctx.notes_path, workbranch.WORKDIR
    safefs.write_json(root, f"{workdir}/fetch.json", fetch_flow.fetch_json(task, k))
    write_changes(ctx, task)
    safefs.unlink(root, f"{workdir}/result.json")


def write_changes(ctx: Ctx, task: Task) -> None:
    from .steps import base_of
    changed = workbranch.changed_files(ctx.worktree("notes"), base_of(task))
    data = {"base": task.get("base"), "changed": changed}
    validate("changes", data)
    safefs.write_json(ctx.notes_path, f"{workbranch.WORKDIR}/changes.json", data)


def run_ranges(ctx: Ctx, task: Task, handlers) -> str:
    """Call the writer for each remaining range; returns 'done' or 'question'."""
    role, harness = ctx.cfg.role("writer")
    n = len(task.get("ranges"))
    k = task.get("writing_k", 1)
    while k <= n:
        task.set_phase("writing", writing_k=k)
        write_inputs(ctx, task, k)
        result = _call(ctx, task, k, role, harness, handlers)
        write_json(task.dir / f"result-{k}.json", result)
        if result["status"] == "question":
            task.update(question=result.get("questions", []))
            return "question"
        k += 1
        task.update(writing_k=k)
    return "done"


def _call(ctx: Ctx, task: Task, k: int, role, harness, handlers) -> dict:
    checks.begin(task)
    with mcp(ctx, task.dir, "cron", handlers, lambda: task.run_id) as sessdir:
        run = launch.RoleRun(
            learner=ctx.name, run_id=task.run_id, role_name="writer", role=role,
            harness=harness, image=ctx.image_tag(),
            mounts=launch.Mounts(work=ctx.notes_path, sessdir=sessdir),
            output_host=ctx.notes_path / workbranch.WORKDIR / "result.json",
            schema="result", task_dir=task.dir, label=str(k),
            allowed_domains=ctx.cfg.provider_domains)
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
             "notebook_drawings", "figure_requests", "warnings", "coverage")
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
    return merged
