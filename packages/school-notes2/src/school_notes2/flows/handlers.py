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
from . import generation_receipts
from . import fetch as fetch_flow
from . import status as status_flow
from . import checks, steps
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
    """The writer's own check, as often as it likes: guard, result.json, changed files.
    Refreshes tool-rendered learning metadata. Warnings never need a decision."""
    from ..figures import licenses
    licenses.preflight(ctx.notes_path)
    problems: list[dict] = []
    try:
        steps.guard_step(ctx, task)
    except steps.CheckFailed as exc:
        checks.record_failure(ctx, task, exc, "check.guard")
        problems += exc.items
    from . import learning
    content = steps.check_items(ctx, task)
    problems += content
    metadata_valid = not wiki_check.blocking(content)
    result = safefs.read_json(ctx.notes_path, f"{workbranch.WORKDIR}/result.json")
    if result is not None:
        invalid = schema_errors("result", result)
        if invalid:
            problems += [wiki_check.item(".school-notes/result.json", None, e) for e in invalid]
        else:
            fetch = fetch_flow.fetch_json(task, task.get("writing_k", len(task.get("ranges"))),
                                         grade=ctx.student.grade, repo=ctx.notes_path)
            listed = {(i["file"], i["item_id"]) for i in fetch["open_review_items"]}
            problems += check_result(ctx.notes_path, result, fetch, listed,
                                     ctx.cfg.limits.review_closures_per_run, whole_run=False,
                                     base_content=steps.base_reader(ctx, task),
                                     generated=lambda rel: generation_receipts.rights(ctx)(rel))
    if not wiki_check.errors(problems):
        try:
            learning.refresh(ctx, task)
        except steps.CheckFailed as exc:
            checks.record_failure(ctx, task, exc, "check.refresh")
            problems += exc.items
    if metadata_valid:
        problems += public_problems(ctx.notes_path, generation_receipts.rights(ctx),
                                    generation_receipts.changed_svgs(ctx, task))
    problems = checks.identify(problems, ctx.notes_path)
    steps.write_check_items(ctx, problems)
    checks.tool_errors(ctx, task, problems)
    return checks.response(problems)


def public_problems(repo, generated=lambda _: None, svgs=()) -> list[dict]:
    """What finish's public.json step would refuse (a new image with no rights record, a copy
    of a source photo), reported now, so the writer fixes it in the same call. The SVGs the
    run changed (`svgs`) get their provenance receipt in finish."""
    try:
        public.build(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo), generated,
                                         public.writer_svg_rights(repo, svgs)))
    except public.PublicError as exc:
        return [wiki_check.item(p, None, exc.reason) for p in exc.paths]
    return []


def generate(ctx, task, plan_id, note):
    if task.get("mode") == "repair" or task.get("paid_disabled"):
        assigned = {e["commission"]["id"] for e in task.get("pending_figures", [])}
        if plan_id not in assigned or note:
            return {"state": "disabled", "message": "Repair uses free local figures; paid generation is disabled."}
        return image_generate.generate(ctx.image_settings(), plan_id, log=ctx.log, paid_disabled=True)
    result = image_generate.generate(ctx.image_settings(), plan_id, note, log=ctx.log)
    from . import image_notices
    image_notices.threshold(ctx)
    return result
