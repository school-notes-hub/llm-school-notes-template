"""P2–P6, one forward-only pass per attempt; no model call after finalization."""

from ..figures import insert, pending, migration_gate
from ..reader import notices, report, verdicts
from ..review import relations
from ..state import safefs
from ..state.errors import WaitingQuota
from . import correction, correction_figures, inspection, recheck, steps

PHASES = ("figures", "inspecting", "correcting", "rechecking", "review_ready")


def advance(ctx, task, notify, edits=None):
    if task.phase == "waiting_quota":
        task.set_phase(task.get("quota_phase"))
    try:
        return _advance(ctx, task, notify, edits)
    except WaitingQuota:
        task.set_phase("waiting_quota", quota_phase=task.phase)
        raise


def _advance(ctx, task, notify, edits):
    if task.phase == "figures":
        inspection.prepare(ctx, task)
        task.set_phase("inspecting")
    if task.phase == "inspecting":
        inspection.inspect(ctx, task)
        task.set_phase("correcting" if task.get("mode") != "fix" and (correction.all_items(ctx, task) or correction_figures.waiting(ctx, task))
                       else "review_ready")
    if task.phase == "correcting":
        handoff = correction.run(ctx, task, edits)
        if handoff is not None:
            return handoff
        task.set_phase("rechecking" if correction.needs_recheck(ctx, task) and not task.get("correction_rolled_back")
                       else "review_ready")
    if task.phase == "rechecking":
        recheck.run(ctx, task)
        task.set_phase("review_ready")
    if task.phase == "review_ready":
        finalize(ctx, task, edits)
        items = relations.inventory(ctx.notes_path)["items"]
        notify([{"file": k.rsplit("#", 1)[0], "item_id": k.rsplit("#", 1)[1]}
                for k, i in items.items() if i["status"] == "owner"])
        task.set_phase("finishing", review_complete=True)


def finalize(ctx, task, edits=None):
    repo, written, owners = ctx.notes_path, [], []
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
        previous = next((e for e in pending.load(repo) if e["commission"]["id"] == brief["id"]), {})
        defects = correction_figures.defects(state, receipt, previous.get("defects", []))
        exhausted = correction_figures.mark_exhausted(ctx, {"commission": brief})
        entry = pending.record(repo, brief, task.run_id, defects,
                               owner_required=exhausted, review_pending=correction_figures.awaiting(ctx, brief),
                               attempted=state["attempted"] if "attempted" in state else correction_figures.attempted(ctx, task, brief))
        written += [pending.PATH, migration_gate.MARK]
        if entry["owner_required"] and entry["runs"] >= 3 and not exhausted:
            owners.append({"file": brief["page"], "quote": f"<!-- figure: {brief['id']} -->",
                           "figure_id": brief["id"], "category": "kép–szöveg", "origin": "figure", "chain": 1, "relates_to": None,
                           "problem": "Az ábramegbízás három futás után is függőben van.", "suggestion": ""})
    if owners:
        path = task.get("inspection_report")
        written.append(report.append(repo, path, owners, [], "figures"))
    written += notices.refresh(repo, _notice_pages(ctx, task))
    steps.record_tool_files(task, repo, written)
    steps.generate_all(ctx, task)


def _notice_pages(ctx, task):
    pages = {p for u in task.get("inspection_units", []) for p in u["pages"]}
    path = task.get("inspection_report")
    if path:
        pages.update(i["file"] for key, i in relations.inventory(ctx.notes_path)["items"].items()
                     if key.startswith(path + "#") and i["status"] in ("open", "owner") and i.get("file"))
    return sorted(pages)


def final_keys(ctx, task):
    """G4 regeneration and final G5 check: invalidate only, never call a reviewer."""
    from . import learning
    learning.migrate(ctx, task)
    stale = verdicts.invalidate(ctx.notes_path)
    pages = {r["file"] for r in stale}
    pages.update(_notice_pages(ctx, task))
    written = notices.refresh(ctx.notes_path, sorted(pages)) if task.get("review_complete") else []
    # Notices may change pages after step 6 (also in an earlier, interrupted call):
    # public.json must describe the pages as they are. Idempotent: no write without a change.
    steps.write_public(ctx, task)
    written = written + ["publication/public.json"]
    steps.record_tool_files(task, ctx.notes_path, written +
                           ([verdicts.PATH] if safefs.is_file(ctx.notes_path, verdicts.PATH) else []))
    ctx.log.event("review.final_keys", invalidated=len(stale))
    return stale
