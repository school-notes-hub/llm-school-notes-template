"""P2/P3: final candidate state, independent reader and figure checks, one report."""

import subprocess

from ..figures import pending, commissions, context, inputs as figure_inputs, review as figure_review, migration_gate
from ..reader import calls, inputs, report, units, verdicts
from ..state import safefs
from ..wiki import banners, frontmatter
from . import correction_figures, generation_receipts, steps
from .inspection_runtime import folder, role, render, figures


def prepare(ctx, task):
    result = task.get("inspection_result")
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
                raise steps.CheckFailed(commissions.check(ctx.notes_path, [assignment])) from exc
            brief = waiting[assignment["id"]]
            candidate = {"state": "failed", "reason": str(exc)}
            safefs.write_json(ctx.notes_path, f".school-notes/figures/{brief['id']}/figure.json", candidate)
        else:
            candidate = candidate_state(ctx, task, brief)
        states.append({"brief": brief, "candidate": candidate, "attempted": attempted})
    briefs = [s["brief"] for s in states]
    changed = sorted(steps.llm_snapshot(ctx, task))
    grouped = units.collect(ctx.notes_path, changed, result.get("review_closure", []), briefs)
    task.update(inspection_changed=task.get("inspection_changed", changed), inspection_all_units=grouped)
    # Retry only changed keys. A unit containing an invalid page is read as a whole.
    grouped = [u for u in grouped if task.get("mode") == "fix" or any(verdicts.valid(ctx.notes_path, p) is None for p in u["pages"])
               or any(s["brief"]["page"] in u["pages"] and figure_changed(ctx, task, s) for s in states)]
    task.update(inspection_figures=states, inspection_units=grouped)


def figure_changed(ctx, task, state):
    if state["candidate"]["state"] != "candidate":
        return False
    brief = state["brief"]
    key = context.verdict_key(ctx.notes_path, brief, state["candidate"])
    previous = task.get("inspection_receipts", {}).get(brief["id"], {})
    return figure_review.verdict_for(previous, brief["id"]).get("key") != key


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


def old_text(ctx, task, page):
    old = ctx.worktree("notes").run("show", f"{steps.base_of(task)}:{page}", check=False)
    return old.stdout.decode("utf-8", "replace") if old.returncode == 0 else ""


def inspect(ctx, task):
    root, repo = folder(task), ctx.notes_path
    saved = safefs.read_json(root, "p3.json")
    if saved is None:
        view = prepare_view(ctx, task, root)
        findings, notes, pages, coverage, fixes = inspect_readers(ctx, task, view)
        receipts, figure_notes = inspect_figures(ctx, task)
        notes += figure_notes
        saved = {"findings": findings, "notes": notes, "pages": pages, "receipts": receipts, "coverage": coverage, "fixes": fixes}
        safefs.write_json(root, "p3.json", saved)
    _apply(ctx, task, saved)
    if saved.get("fixes"):
        from . import recheck
        recheck.apply(ctx, task, {"units": saved["fixes"], "receipts": saved["receipts"]})


def prepare_view(ctx, task, root):
    repo = ctx.notes_path
    briefs = [s["brief"] for s in task.get("inspection_figures", [])]
    view = root / "reader-view"
    inputs.preview(repo, view, briefs, render(ctx, task))
    for unit in task.get("inspection_units", []):
        for page in unit["pages"]:
            if frontmatter.split(safefs.read_text(repo, page)).meta.get("banner_from"):
                unit["keys"][page] = units.page_key(repo, page, banner_image=banners.candidate_image(repo, page, briefs))
    return view


def inspect_readers(ctx, task, view):
    findings, notes, pages, coverage, fixes = [], [], [], [], []
    for unit in task.get("inspection_units", []):
        if task.get("mode") == "fix":
            from . import recheck
            closures = [c for c in task.get("inspection_result", {}).get("review_closure", [])
                        if c["status"] in ("fixed", "disagree")]
            fixes.append(recheck.check_unit(ctx, task, view, unit, closures))
        else:
            result = _reader(ctx, task, view, unit)
            findings += result["findings"]
            notes += result["notes"]
            pages += result["pages"]
            coverage.append({"topic": unit["topic"], **result["coverage"]})
    return findings, notes, pages, coverage, fixes


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
    first = calls.run(repo, view, root / "pass1", "reader-1", assigned, role(ctx, task), log=ctx.log,
                      allowed_paths=set(unit["pages"]) | set(unit.get("context", [])))
    findings, notes, pages, coverage = [], [], [], {"errors": 0, "covered": 0}
    if first["status"] == "reviewed":
        review = first["review"]
        safefs.write_json(repo, f".school-notes/reader/{root.name}/pass1.json", review)
        findings = [{**f, "origin": "reader", "outside_assignment": f["file"] not in unit["pages"]}
                    for f in review["findings"]]
        notes += review["owner_notes"]
        pages = [{**p, "key": unit["keys"][p["file"]], "model": first["model"]} for p in review["pages"]]
    hits = [h for h in task.get("check_warnings", []) if h["file"] in unit["pages"]]
    if hits:
        second_in = root / "pass2/in"
        second_in.mkdir(parents=True, exist_ok=True)
        ids = [f["id"] for f in findings]
        assigned = {"hits": [h["id"] for h in hits], "findings": ids}
        safefs.write_json(second_in, "assigned.json", assigned)
        safefs.write_json(second_in, "hits.json", inputs.hits(repo, hits))
        safefs.write_json(second_in, "findings.json", findings)
        second = calls.run(repo, view, root / "pass2", "reader-2", assigned, role(ctx, task), log=ctx.log)
        if second["status"] == "reviewed":
            review = second["review"]
            safefs.write_json(repo, f".school-notes/reader/{root.name}/pass2.json", review)
            findings += report.list_findings(repo, hits, review["hits"], findings)
            notes += review["owner_notes"]
            errors = [h for h in review["hits"] if h["verdict"] == "hiba"]
            coverage = {"errors": len(errors), "covered": sum(h["covered_by"] is not None for h in errors)}
            ctx.log.event("reader.coverage", topic=unit["topic"], **coverage)
    return {"findings": findings, "notes": notes, "pages": pages, "coverage": coverage}


def _apply(ctx, task, saved):
    findings, notes, pages = report.prepare(ctx.notes_path, saved["findings"], saved["notes"], saved["pages"])
    saved = {**saved, "findings": findings, "notes": notes, "pages": pages}
    path = f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    if not task.get("inspection_figures") and not any(saved.get(k) for k in ("findings", "notes", "pages", "receipts", "fixes")):
        task.update(inspection_report=None, inspection_receipts={}, reader_pages=[])
        return
    model = role(ctx, task).role
    if task.get("attempt", 1) > 1 and safefs.is_file(ctx.notes_path, path):
        report.append(ctx.notes_path, path, saved["findings"], saved["notes"], f"attempt-{task.get('attempt')}")
    else:
        report.write(ctx.notes_path, path, saved["findings"], saved["notes"],
                     f"{model.model}/{model.effort}", task.get("base"), task.data["created"])
    for page in saved["pages"]:
        verdicts.record(ctx.notes_path, [page], {page["file"]: page["key"]}, page["model"], task.data["created"])
    task.update(inspection_report=path, inspection_receipts=saved["receipts"], reader_pages=saved["pages"],
                reader_owner_notes=saved["notes"], reader_coverage=saved.get("coverage", []))
    steps.record_tool_files(task, ctx.notes_path, [path, verdicts.PATH, "docs/review/warning-verdicts.json"])
