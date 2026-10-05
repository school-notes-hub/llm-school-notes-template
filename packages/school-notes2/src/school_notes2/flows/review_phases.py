"""P2–P6 with up to three correction rounds; no model call after finalization."""

from ..log import duration
from ..figures import insert, pending, migration_gate
from ..reader import notice_migration, notices, report, verdicts
from ..review import relations
from ..state import safefs
from ..state.errors import WaitingQuota
from . import correction, correction_figures, correction_round, inspection, recheck, steps

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
        initial = task.get("mode") == "fix"
        record_figures(ctx, task, correction_round.identity(task, 1) if initial else task.run_id)
        more = correction.all_items(ctx, task) or correction_figures.waiting(ctx, task)
        task.set_phase("correcting" if more else "review_ready",
                       correction_round=2 if initial and not task.get("fix_scope_rolled_back") else 1)
    while task.phase in ("correcting", "rechecking"):
        if task.phase == "correcting":
            handoff = correction.run(ctx, task, edits)
            if handoff is not None:
                return handoff
            # Two complete rollbacks already retried inside correction.run; no attempt counted.
            task.set_phase("review_ready" if task.get("correction_rolled_back") else "rechecking")
            if task.phase == "review_ready":
                break
        recheck.run(ctx, task)
        record_figures(ctx, task, correction_round.identity(task))
        more = correction.all_items(ctx, task) or correction_figures.waiting(ctx, task)
        n = correction_round.number(task)
        task.set_phase("correcting" if more and n < 3 and task.mode != "interactive" else "review_ready",
                       correction_round=n + 1 if more and n < 3 and task.mode != "interactive" else n)
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
    identity = task.run_id if task.get("correction_round") is None else correction_round.identity(task)
    written += record_figures(ctx, task, identity, final=True)
    written += refresh_notices(ctx, task, _notice_pages(ctx, task))
    steps.record_tool_files(task, repo, written)
    steps.generate_all(ctx, task)
    from . import fix_progress
    fix_progress.record(ctx, task)


def record_figures(ctx, task, run_id, *, final=False):
    written, owners = [], []
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
        entry = pending.record(ctx.notes_path, brief, run_id,
            correction_figures.defects(state, receipt, previous.get("defects", [])),
            owner_required=exhausted, review_pending=correction_figures.awaiting(ctx, brief),
            attempted=((state["attempted"] if "attempted" in state else correction_figures.attempted(ctx, task, brief))
                       if not final or task.get("correction_round") is None else False), log=getattr(ctx, "log", None))
        written += [pending.PATH, migration_gate.MARK]
        if final and entry["owner_required"] and entry["runs"] >= 3 and not exhausted:
            owners.append({"file": brief["page"], "quote": f"<!-- figure: {brief['id']} -->",
                "owner_status": "owner", "figure_id": brief["id"], "category": "kép–szöveg", "origin": "figure",
                "chain": 1, "relates_to": None, "problem": "Az ábramegbízás három próba után is függőben van.", "suggestion": ""})
    if owners:
        path = recheck.report_path(ctx, task)
        written.append(report.append(ctx.notes_path, path, owners, [], "figures"))
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
