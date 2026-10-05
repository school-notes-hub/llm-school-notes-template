"""P2/P3 (or P5) once per run: one pass, no in-run correction rounds; no model call after
finalization. Whatever the check finds becomes an item for the next run."""

from ..log import duration
from ..figures import insert, pending, migration_gate
from ..reader import notice_migration, notices, verdicts
from ..review import relations
from ..state import safefs
from ..state.errors import WaitingQuota
from . import correction_figures, inspection, steps

PHASES = ("figures", "inspecting", "correcting", "rechecking", "review_ready")


def advance(ctx, task, notify, edits=None):
    if task.phase == "waiting_quota":
        task.set_phase(task.get("quota_phase"))
    try:
        return _advance(ctx, task, notify, edits)
    except WaitingQuota:
        task.set_phase("waiting_quota", quota_phase=task.phase)
        raise


def resume_legacy_round(task):
    """A 2.5.x task stopped in an in-run correction round: those rounds no longer exist. The
    kept files go through the content steps once more (lesson notes, stamps, evidence, check;
    `writing_k` is past the last range, so no writer starts) and every change of the run is
    rechecked once against the base. The run's closures were applied by 2.5.x already, under
    its round identities, and rechecked there: they are not applied again."""
    legacy = ("correcting", "rechecking")
    if task.phase in legacy or task.phase == "waiting_quota" and task.get("quota_phase") in legacy:
        task.set_phase("writing", review_complete=False, recheck_all=True, closures_applied=True)


def _advance(ctx, task, notify, edits):
    if task.phase == "figures":
        inspection.prepare(ctx, task)
        task.set_phase("inspecting")
    if task.phase == "inspecting":
        inspection.inspect(ctx, task)
        task.set_phase("review_ready")
    if task.phase == "review_ready":
        finalize(ctx, task, edits)
        items = relations.inventory(ctx.notes_path)["items"]
        notify([{"file": k.rsplit("#", 1)[0], "item_id": k.rsplit("#", 1)[1]}
                for k, i in items.items() if i["status"] == "owner"])
        task.set_phase("finishing", review_complete=True)


def finalize(ctx, task, edits=None):
    with duration(ctx.log, "review.finalize"):
        return _finalize(ctx, task, edits)


def _finalize(ctx, task, edits=None):
    repo, written = ctx.notes_path, []
    for state in task.get("inspection_figures", []):
        brief = state["brief"]
        if migration_gate.concerns(repo, brief):
            continue
        receipt = task.get("inspection_receipts", {}).get(brief["id"], {})
        verdict = correction_figures.verdict_for(receipt, brief["id"])
        if verdict.get("verdict") == "accept" and state["candidate"]["state"] == "candidate":
            replacing = edits is not None and brief.get("replaces")
            try:
                before = steps.llm_snapshot(ctx, task).get(brief["page"]) if replacing else None
                written += insert.insert(repo, brief, receipt, at=task.data["created"])
                if replacing:
                    after = steps.llm_snapshot(ctx, task).get(brief["page"])
                    edits["replacements"].append((brief["page"], before, after))
                continue
            except (OSError, ValueError) as exc:
                ctx.log.event("figure.stale", id=brief["id"], reason=str(exc))
        if state["candidate"]["state"] == "no-figure":
            continue
    written += record_figures(ctx, task)
    written += refresh_notices(ctx, task, _notice_pages(ctx, task))
    steps.record_tool_files(task, repo, written)
    steps.generate_all(ctx, task)
    from . import fix_progress
    fix_progress.record(ctx, task)


def record_figures(ctx, task):
    """Pending figures stay pending; after three runs the owner is told (status and one
    mail), never through a review item (A3)."""
    written = []
    for state in task.get("inspection_figures", []):
        brief = state["brief"]
        if migration_gate.concerns(ctx.notes_path, brief):
            continue
        receipt = task.get("inspection_receipts", {}).get(brief["id"], {})
        verdict = correction_figures.verdict_for(receipt, brief["id"])
        if verdict.get("verdict") == "accept" or state["candidate"]["state"] == "no-figure":
            continue
        previous = next((e for e in pending.load(ctx.notes_path) if e["commission"]["id"] == brief["id"]), {})
        exhausted = correction_figures.mark_exhausted(ctx, {"commission": brief})
        entry = pending.record(ctx.notes_path, brief, task.run_id,
            correction_figures.defects(state, receipt, previous.get("defects", [])),
            owner_required=exhausted, review_pending=correction_figures.awaiting(ctx, brief),
            attempted=state["attempted"] if "attempted" in state else correction_figures.attempted(ctx, task, brief),
            log=getattr(ctx, "log", None))
        written += [pending.PATH, migration_gate.MARK]
        if entry["owner_required"] and entry["runs"] >= 3 and not exhausted and getattr(ctx, "mailer", None):
            from ..notify import Notice, pending as owner_notices
            owner_notices.send(ctx, Notice(ctx.name, f"figure_owner:{brief['id']}", "", "figures", "owner",
                f"Az ábramegbízás három próba után is függőben van: {brief['id']} ({brief['page']}).",
                f"Dönts a függő ábráról a school-notes chat {ctx.name} munkamenetben."))
    steps.record_tool_files(task, ctx.notes_path, written)
    return written


def _notice_pages(ctx, task):
    pages = {p for u in task.get("inspection_units", []) for p in u["pages"]}
    pages.update(s["brief"]["page"] for s in task.get("inspection_figures", []))
    path = task.get("inspection_report")
    if path:
        pages.update(i["file"] for key, i in relations.inventory(ctx.notes_path)["items"].items()
                     if key.startswith(path + "#") and i["status"] in ("open", "owner") and i.get("file"))
    return sorted(pages)


def final_keys(ctx, task):
    with duration(ctx.log, "review.final_keys"):
        return _final_keys(ctx, task)


def _final_keys(ctx, task):
    """G4 regeneration and final G5 check: invalidate only, never call a reviewer."""
    from . import learning
    learning.migrate(ctx, task)
    stale = verdicts.invalidate(ctx.notes_path)
    pages = {r["file"] for r in stale}
    pages.update(_notice_pages(ctx, task))
    written = refresh_notices(ctx, task, sorted(pages))
    # Notices may change pages after step 6 (also in an earlier, interrupted call):
    # public.json must describe the pages as they are. Idempotent: no write without a change.
    steps.write_public(ctx, task)
    written = written + ["publication/public.json"]
    steps.record_tool_files(task, ctx.notes_path, written +
                           ([verdicts.PATH] if safefs.is_file(ctx.notes_path, verdicts.PATH) else []))
    ctx.log.event("review.final_keys", invalidated=len(stale))
    return stale


def refresh_notices(ctx, task, pages):
    from . import journal
    journal.settle(ctx, task)
    write = lambda path, text: journal.write(ctx, task, path, text, whole=not path.startswith("wiki/"))
    git = ctx.worktree("notes") if safefs.exists(ctx.notes_path, ".git") else None
    written = notice_migration.refresh(ctx.notes_path, git=git, write=write)
    return written + notices.refresh(ctx.notes_path, pages, write=write)
