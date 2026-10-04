"""P2/P3: final candidate state, independent reader and figure checks, one report."""

import subprocess

from ..figures import commissions, context, inputs as figure_inputs, review as figure_review
from ..figures.render import Renderer
from ..llm import launch
from ..reader import calls, inputs, report, units, verdicts
from ..state import safefs
from . import steps


def folder(task):
    path = task.dir / f"attempt-{task.get('attempt', 1)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def role(ctx, task):
    configured, harness = ctx.cfg.role("reviewer")
    return launch.RoleRun(ctx.name, task.run_id, "reader-1", configured, harness,
                          ctx.image_tag(), launch.Mounts(), task.dir / "unused.json",
                          "reader-1", folder(task), allowed_domains=ctx.cfg.provider_domains,
                          max_agents=task.get("max_agents", ctx.cfg.limits.max_agents),
                          lease_dir=ctx.cfg.state_dir / "agent-leases", attempt=task.get("attempt", 1))


def prepare(ctx, task):
    result = task.get("inspection_result")
    assigned = {a["id"]: a for a in result.get("figures", [])}
    for entry in task.get("pending_figures", []):
        brief = entry["commission"]
        assigned.setdefault(brief["id"], {k: brief[k] for k in ("id", "page", "kind")})
    briefs = commissions.validate_assignments(ctx.notes_path, list(assigned.values()))
    states = [{"brief": brief, "candidate": candidate_state(ctx, task, brief)} for brief in briefs]
    changed = sorted(steps.llm_snapshot(ctx, task))
    grouped = units.collect(ctx.notes_path, changed, result.get("review_closure", []), briefs)
    # Retry only changed keys. A unit containing an invalid page is read as a whole.
    grouped = [u for u in grouped if any(verdicts.valid(ctx.notes_path, p) is None for p in u["pages"])
               or any(b["page"] in u["pages"] for b in briefs)]
    task.update(inspection_figures=states, inspection_units=grouped)



def candidate_state(ctx, task, brief):
    try:
        candidate = commissions.candidate(ctx.notes_path, brief)
        if candidate["state"] == "candidate":
            from ..figures import machine
            errors = machine.report(ctx.notes_path, brief, candidate)["errors"]
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
        briefs = [s["brief"] for s in task.get("inspection_figures", [])]
        view = root / "reader-view"
        inputs.preview(repo, view, briefs, render(ctx, task))
        findings, notes, pages, receipts, coverage = [], [], [], {}, []
        for unit in task.get("inspection_units", []):
            if task.get("mode") != "fix":
                result = _reader(ctx, task, view, unit)
                findings += result["findings"]
                notes += result["notes"]
                pages += result["pages"]
                coverage.append({"topic": unit["topic"], **result["coverage"]})
        candidates = [s["brief"] for s in task.get("inspection_figures", [])
                      if s["candidate"]["state"] == "candidate"]
        fresh = []
        for brief in candidates:
            previous = task.get("inspection_receipts", {}).get(brief["id"], {})
            key = context.verdict_key(repo, brief, commissions.candidate(repo, brief))
            if any(v["id"] == brief["id"] and v["key"] == key
                   for v in previous.get("review", {}).get("figures", [])):
                receipts[brief["id"]] = previous
            else:
                fresh.append(brief)
        for name, batch in figure_inputs.batches(repo, fresh):
            receipt = figures(ctx, task, batch, name)
            for brief in batch:
                receipts[brief["id"]] = receipt
            findings += figure_findings(batch, receipt)
            notes += receipt.get("review", {}).get("owner_notes", [])
        saved = {"findings": findings, "notes": notes, "pages": pages, "receipts": receipts, "coverage": coverage}
        safefs.write_json(root, "p3.json", saved)
    _apply(ctx, task, saved)


def _reader(ctx, task, view, unit):
    repo, root = ctx.notes_path, folder(task) / "reader" / units.slug(unit["topic"])
    assigned = inputs.prepare(repo, view, unit, root / "pass1/in", lambda p: old_text(ctx, task, p))
    first = calls.run(repo, view, root / "pass1", "reader-1", assigned, role(ctx, task), log=ctx.log)
    findings, notes, pages, coverage = [], [], [], {"errors": 0, "covered": 0}
    if first["status"] == "reviewed":
        review = first["review"]
        safefs.write_json(repo, f".school-notes/reader/{root.name}/pass1.json", review)
        findings = [{**f, "origin": "reader"} for f in review["findings"]]
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
            findings += report.list_findings(repo, hits, review["hits"])
            notes += review["owner_notes"]
            errors = [h for h in review["hits"] if h["verdict"] == "hiba"]
            coverage = {"errors": len(errors), "covered": sum(h["covered_by"] is not None for h in errors)}
            ctx.log.event("reader.coverage", topic=unit["topic"], **coverage)
    return {"findings": findings, "notes": notes, "pages": pages, "coverage": coverage}


def figures(ctx, task, batch, name):
    renderer = render(ctx, task)
    try:
        return figure_review.run_batch(ctx.notes_path, batch, name, role(ctx, task),
                                       render=renderer, log=ctx.log)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "pending", "reason": str(exc)}


def render(ctx, task):
    return Renderer(ctx.release() / "packages/study-site", ctx.cfg.browser,
                        folder(task) / "render", timeout_s=ctx.cfg.timeouts.rasterize_s)


def figure_findings(batch, receipt):
    result = []
    by_id = {b["id"]: b for b in batch}
    for verdict in receipt.get("review", {}).get("figures", []):
        if verdict["verdict"] == "accept":
            continue
        brief = by_id[verdict["id"]]
        defects = verdict["defects"] + verdict["text_mismatch"]
        result.append({"file": brief["page"], "quote": f"<!-- figure: {brief['id']} -->",
                       "origin": "figure", "figure_id": brief["id"], "category": "kép–szöveg",
                       "problem": str(defects) if defects else verdict["observed"], "suggestion": "",
                       "relates_to": verdict["relates_to"], "new_evidence": verdict.get("new_evidence", "")})
    return result


def _apply(ctx, task, saved):
    path = f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    if not task.get("inspection_figures") and not any(saved[k] for k in ("findings", "notes", "pages", "receipts")):
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
