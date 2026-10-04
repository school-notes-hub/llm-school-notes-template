"""The MCP operations of one session (plan 7.5), wired to the flows."""

from ..git import workbranch
from ..images import generate as image_generate
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
from . import call_scope, checks, steps
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
        image_generate=lambda plan_id, note: generate(ctx, task(), plan_id, note),
        status=lambda: status_flow.summary(ctx),
        fetch=fetch, finish=finish)


def check(ctx: Ctx, task) -> dict:
    """The writer's own check at the end of its work: guard, result.json, changed files.
    Applies unambiguous auto-fixes and refreshes tool-rendered learning metadata."""
    if not checks.take(task):
        return dict(checks.LIMIT)
    problems: list[dict] = []
    try:
        steps.guard_step(ctx, task)
    except steps.CheckFailed as exc:
        problems += exc.items
    from . import learning
    metadata_valid = True
    try:
        problems += steps.check_items(ctx, task)
    except steps.CheckFailed as exc:
        metadata_valid = False
        problems += exc.items
    if metadata_valid:
        problems += steps.order_step(ctx, task)
    result = safefs.read_json(ctx.notes_path, f"{workbranch.WORKDIR}/result.json")
    if result is not None:
        invalid = schema_errors("result", result)
        if invalid:
            problems += [wiki_check.item(".school-notes/result.json", None, e) for e in invalid]
        else:
            fetch = fetch_flow.fetch_json(task, task.get("writing_k", len(task.get("ranges"))),
                                         grade=ctx.student.grade)
            listed = {(i["file"], i["item_id"]) for i in fetch["open_review_items"]}
            problems += check_result(ctx.notes_path, result, fetch, listed,
                                     ctx.cfg.limits.review_closures_per_run, whole_run=False)
    if not wiki_check.errors(problems):
        try:
            learning.refresh(ctx, task)
        except steps.CheckFailed as exc:
            problems += exc.items
    if metadata_valid:
        problems += public_problems(ctx.notes_path)
    problems = checks.identify(call_scope.current(ctx, task, problems), ctx.notes_path)
    steps.write_check_items(ctx, problems)
    checks.tool_errors(ctx, task, problems)
    checks.remember(task, problems)
    return checks.response(problems)


def public_problems(repo) -> list[dict]:
    """What finish's public.json step would refuse (a new image with no rights record, a copy
    of a source photo), reported now, so the writer fixes it in the same call."""
    try:
        public.build(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo)))
    except public.PublicError as exc:
        return [wiki_check.item(p, None, exc.reason) for p in exc.paths]
    return []


def generate(ctx, task, plan_id, note):
    if task.get("mode") == "repair" or task.get("paid_disabled"):
        return {"state": "disabled", "message": "Repair uses free local figures; paid generation is disabled."}
    return image_generate.generate(ctx.image_settings(), plan_id, note, log=ctx.log)
