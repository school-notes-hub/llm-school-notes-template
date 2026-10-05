"""P2 and one independent check per run: the reader (new material, P3) or the recheck of
every changed author line (fix runs, P5). Findings become items for the next run."""

import subprocess

from ..figures import commissions, context, inputs as figure_inputs, review as figure_review, migration_gate
from ..reader import calls, inputs, report, units, verdicts
from ..state import safefs
from . import correction_figures, generation_receipts, steps
from .inspection_runtime import folder, role, render, figures

RECEIPT = "inspection.json"


def rechecking(task):
    """Fix runs and resumed 2.5.x correction rounds recheck lines; new material is read."""
    return task.get("mode") == "fix" or bool(task.get("recheck_all"))


def prepare(ctx, task):
    result = task.get("inspection_result") or {}
    waiting = {e["commission"]["id"]: e["commission"] for e in task.get("pending_figures", [])}
    assignments = [a for a in commissions.assignments(result, task.get("pending_figures", []))
                   if not migration_gate.concerns(ctx.notes_path, a)]
    attempts = task.get("figure_attempts", {})
    attempt = str(task.get("attempt", 1))
    if attempt not in attempts:
        attempts = {**attempts, attempt: {a["id"]: correction_figures.attempted(ctx, task, a) for a in assignments}}
        task.update(figure_attempts=attempts)
    states = []
    for assignment in assignments:
        attempted = attempts[attempt].get(assignment["id"], False)
        try:
            brief = commissions.validate_assignments(ctx.notes_path, [assignment])[0]
        except (ValueError, OSError) as exc:
            if assignment["id"] not in waiting:
                # A new commission the writer left invalid gives no figure; the text stays (#7).
                ctx.log.event("figure.invalid_commission", "warning", target=assignment["id"], message=str(exc)[:200])
                continue
            brief = waiting[assignment["id"]]
            candidate = {"state": "failed", "reason": str(exc)}
            safefs.write_json(ctx.notes_path, f".school-notes/figures/{brief['id']}/figure.json", candidate)
        else:
            candidate = candidate_state(ctx, task, brief)
        states.append({"brief": brief, "candidate": candidate, "attempted": attempted})
    changed = sorted(steps.llm_snapshot(ctx, task))
    grouped = [] if rechecking(task) else units.collect(ctx.notes_path, changed, (), [s["brief"] for s in states])
    task.update(inspection_figures=states, inspection_units=grouped, inspection_changed=changed)


def candidate_state(ctx, task, brief):
    try:
        candidate = commissions.candidate(ctx.notes_path, brief)
        if candidate["state"] == "candidate":
            errors = commissions.preflight(ctx.notes_path, brief,
                                            generated=lambda rel: generation_receipts.rights(ctx)(rel))
            if errors:
                raise ValueError("; ".join(errors))
            if "mermaid" in candidate or candidate.get("asset", "").endswith(".svg"):
                kind = "mermaid" if "mermaid" in candidate else "svg"
                data = context.mermaid_source(ctx.notes_path, brief, candidate).encode() if kind == "mermaid" else safefs.read_bytes(ctx.notes_path, candidate["asset"])
                render(ctx, task)(kind, data, brief["id"])
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        candidate = {"state": "failed", "reason": str(exc)}
        safefs.write_json(ctx.notes_path, f".school-notes/figures/{brief['id']}/figure.json", candidate)
    return candidate


def figure_changed(ctx, task, state):
    if state["candidate"]["state"] != "candidate":
        return False
    brief = state["brief"]
    key = context.verdict_key(ctx.notes_path, brief, state["candidate"])
    previous = task.get("inspection_receipts", {}).get(brief["id"], {})
    return figure_review.verdict_for(previous, brief["id"]).get("key") != key


def old_text(ctx, task, page):
    old = steps.base_reader(ctx, task)(page)
    return old.decode("utf-8", "replace") if old is not None else ""


def inspect(ctx, task):
    from . import recheck
    root = folder(task)
    saved = safefs.read_json(root, RECEIPT)
    if saved is None:
        view = root / "reader-view"
        inputs.preview(ctx.notes_path, view, [s["brief"] for s in task.get("inspection_figures", [])], render(ctx, task))
        receipts, figure_notes = inspect_figures(ctx, task)
        if rechecking(task):
            saved = {"recheck": recheck.run(ctx, task, view), "receipts": receipts, "notes": figure_notes}
        else:
            findings, notes, pages = inspect_readers(ctx, task, view)
            saved = {"findings": findings, "notes": notes + figure_notes, "pages": pages, "receipts": receipts}
        safefs.write_json(root, RECEIPT, saved)
    if "recheck" in saved:
        recheck.apply(ctx, task, saved)
    else:
        _apply(ctx, task, saved)


def inspect_readers(ctx, task, view):
    findings, notes, pages = [], [], []
    changed = set(task.get("inspection_changed", []))
    figured = {s["brief"]["page"] for s in task.get("inspection_figures", []) if figure_changed(ctx, task, s)}
    for unit in task.get("inspection_units", []):
        # Only changed pages without a current verdict (or with a changed figure) are
        # assigned; the rest of the topic is context (Fable 6). Nothing is read twice.
        assigned = [p for p in unit["pages"] if p in figured or
                    (p in changed and verdicts.valid(ctx.notes_path, p) is None)]
        if not assigned:
            continue
        unit = {**unit, "pages": assigned, "context": sorted(set(unit["pages"]) - set(assigned) | set(unit["context"])),
                "keys": {p: units.page_key(ctx.notes_path, p) for p in assigned}}
        result = _reader(ctx, task, view, unit)
        findings += result["findings"]
        notes += result["notes"]
        pages += result["pages"]
    return findings, notes, pages


def inspect_figures(ctx, task):
    repo, receipts, notes = ctx.notes_path, {}, []
    candidates = [s["brief"] for s in task.get("inspection_figures", [])
                  if s["candidate"]["state"] == "candidate"]
    fresh = []
    for brief in candidates:
        previous = task.get("inspection_receipts", {}).get(brief["id"], {})
        key = context.verdict_key(repo, brief, commissions.candidate(repo, brief))
        if figure_review.verdict_for(previous, brief["id"]).get("key") == key:
            receipts[brief["id"]] = previous
        else:
            fresh.append(brief)
    for name, batch in figure_inputs.batches(repo, fresh):
        receipt = figures(ctx, task, batch, name)
        for brief in batch:
            receipts[brief["id"]] = figure_review.for_figure(receipt, brief["id"])
        notes += receipt.get("review", {}).get("owner_notes", [])
    return receipts, notes


def _reader(ctx, task, view, unit):
    repo, root = ctx.notes_path, folder(task) / "reader" / units.slug(unit["topic"])
    assigned = inputs.prepare(repo, view, unit, root / "pass1/in", lambda p: old_text(ctx, task, p))
    first = calls.run(repo, view, root / "pass1", "reader-1", assigned, role(ctx, task), log=ctx.log)
    if first["status"] != "reviewed":
        return {"findings": [], "notes": [], "pages": []}
    review = first["review"]
    safefs.write_json(repo, f".school-notes/reader/{root.name}/pass1.json", review)
    return {"findings": [{**f, "origin": "reader"} for f in review["findings"]], "notes": review["owner_notes"],
            "pages": [{**p, "key": unit["keys"][p["file"]], "model": first["model"]} for p in review["pages"]]}


def _apply(ctx, task, saved):
    findings, notes, pages = report.prepare(ctx.notes_path, saved["findings"], saved["notes"], saved["pages"])
    path = f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    if not task.get("inspection_figures") and not any(saved.get(k) for k in ("findings", "notes", "pages", "receipts")):
        task.update(inspection_receipts={}, reader_pages=[])
        return
    model = role(ctx, task).role
    from . import journal
    journal.settle(ctx, task)
    write = lambda repo, rel, text: journal.write(ctx, task, rel, text, whole=True)
    if safefs.is_file(ctx.notes_path, path):
        report.append(ctx.notes_path, path, findings, notes, f"reader-{task.get('attempt', 1)}", write=write)
    else:
        report.write(ctx.notes_path, path, findings, notes, f"{model.model}/{model.effort}", task.get("base"),
                     task.data["created"], write=write)
    for page in pages:
        verdicts.record(ctx.notes_path, [page], {page["file"]: page["key"]}, page["model"], task.data["created"])
    task.update(inspection_report=path, inspection_receipts=saved["receipts"], reader_pages=pages,
                reader_owner_notes=notes)
    steps.record_tool_files(task, ctx.notes_path, [path, verdicts.PATH])
