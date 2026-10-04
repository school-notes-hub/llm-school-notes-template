"""The MCP operations of one session (plan 7.5), wired to the flows."""

from ..evidence import records
from ..git import workbranch
from ..images import accept as image_accept
from ..images import generate as image_generate
from ..log import now_iso
from ..mcp.server import Handlers
from ..schemas import errors as schema_errors
from ..state import phase
from ..state.errors import NeedsOwner
from ..state import safefs
from ..wiki import check as wiki_check
from ..wiki import public
from ..wiki.check_result import check_result
from . import fetch as fetch_flow
from . import status as status_flow
from . import steps
from .context import Ctx


def build(ctx: Ctx, task_dir=None, *, fetch=None, finish=None) -> Handlers:
    """`task_dir` names the run (cron). Interactive sessions pass None: the current run is
    the learner's open notes task, which a new `fetch` replaces. The task is reloaded per
    call because background jobs run in their own processes."""

    def task():
        if task_dir is not None:
            return phase.load(task_dir)
        found = phase.open_task(ctx.task_root(), ctx.name, "notes")
        if found is None:
            raise NeedsOwner("there is no open run in this session", todo="call fetch first")
        return found

    return Handlers(
        check=lambda: check(ctx, task()),
        image_generate=lambda plan_id, note: image_generate.generate(
            ctx.image_settings(), plan_id, note, log=ctx.log),
        image_accept=lambda plan_id, review: accept(ctx, task(), plan_id, review),
        status=lambda: status_flow.summary(ctx),
        fetch=fetch, finish=finish)


def check(ctx: Ctx, task) -> dict:
    """The writer's own check at the end of its work: guard, result.json, changed files.
    Applies unambiguous auto-fixes and refreshes tool-rendered learning metadata."""
    problems: list[dict] = []
    try:
        steps.guard_step(ctx, task)
    except steps.CheckFailed as exc:
        problems += exc.items
    problems += steps.order_step(ctx, task)
    result = safefs.read_json(ctx.notes_path, f"{workbranch.WORKDIR}/result.json")
    if result is not None:
        invalid = schema_errors("result", result)
        if invalid:
            problems += [wiki_check.item(".school-notes/result.json", None, e) for e in invalid]
        else:
            fetch = fetch_flow.fetch_json(task, task.get("writing_k", len(task.get("ranges"))))
            listed = {(i["file"], i["item_id"]) for i in fetch["open_review_items"]}
            problems += check_result(ctx.notes_path, result, fetch, listed,
                                     ctx.cfg.limits.review_closures_per_run, whole_run=False)
    problems += wiki_check.check_files(ctx.notes_path, steps.changed_paths(ctx, task))
    if not wiki_check.errors(problems):
        from . import learning
        try:
            learning.refresh(ctx, task)
        except steps.CheckFailed as exc:
            problems += exc.items
    problems += public_problems(ctx.notes_path)
    steps.write_check_items(ctx, problems)
    errors = wiki_check.errors(problems)
    return {"ok": not errors, "errors": len(errors), "problems": problems[:50]}


def public_problems(repo) -> list[dict]:
    """What finish's public.json step would refuse (a new image with no rights record, a copy
    of a source photo), reported now, so the writer fixes it in the same call."""
    try:
        public.build(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo)))
    except public.PublicError as exc:
        return [wiki_check.item(p, None, exc.reason) for p in exc.paths]
    return []


def accept(ctx: Ctx, task, plan_id: str, review: dict) -> dict:
    role, _ = ctx.cfg.role("writer")
    verifier = f"{role.model}/{role.effort}"
    evidence: list[str] = []

    def append_evidence(page: str, entry: dict) -> None:
        record = records.Entry(page=page, image=entry["image"], locator=entry["entry_id"],
                               observed=entry["observed"], decision=entry["decision"],
                               note=entry.get("description", ""), checks=entry.get("checks"))
        evidence.extend(records.append(ctx.notes_path, [record], run_id=task.run_id,
                                       checker=verifier, at=now_iso(), kind=f"image:{plan_id}"))

    answer = image_accept.accept(ctx.image_settings(), plan_id, review, verifier=verifier,
                                 append_evidence=append_evidence, log=ctx.log)
    written = [w["path"] for w in answer.get("tool_writes", [])] + evidence
    steps.record_tool_files(task, ctx.notes_path, written)
    return answer
