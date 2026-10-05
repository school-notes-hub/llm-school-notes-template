"""P5: only fixed/disputed items, new warning hits and changed figures."""

from pathlib import Path

from ..figures import inputs as figure_inputs
from ..reader import calls, inputs, report, units, verdicts
from ..review import relations, scope
from ..review.topic_result import apply_item
from ..state import safefs
from ..wiki import author, frontmatter, source_refs
from . import correction_figures, inspection_runtime as inspection, steps


def run(ctx, task):
    root, repo = inspection.folder(task), ctx.notes_path
    saved = safefs.read_json(root, "p5.json")
    if saved is None:
        changed = correction_figures.changed_figures(ctx, task)
        view = root / "recheck-view"
        inputs.preview(repo, view, [s["brief"] for s in task.get("inspection_figures", [])], inspection.render(ctx, task))
        closures = [c for c in task.get("correction_result", {}).get("review_closure", [])
                    if c["status"] in ("fixed", "disagree")]
        grouped = units.collect(repo, [], closures, changed)
        checked = [check_unit(ctx, task, view, u, closures) for u in grouped]
        receipts = dict(task.get("inspection_receipts", {}))
        for name, batch in figure_inputs.batches(repo, changed):
            receipt = inspection.figures(ctx, task, batch, "recheck-" + name)
            for brief in batch:
                receipts[brief["id"]] = inspection.figure_review.for_figure(receipt, brief["id"])
        saved = {"units": checked, "receipts": receipts}
        safefs.write_json(root, "p5.json", saved)
    apply(ctx, task, saved)


def check_unit(ctx, task, view, unit, closures):
    root = inspection.folder(task) / "reader" / units.slug(unit["topic"]) / "recheck"
    before = inspection.folder(task) / "correction"
    if task.get("mode") == "fix":
        before = task.dir / "fix-before"
    def old(page):
        return safefs.read_text(before, "before/" + page) if safefs.is_file(before, "before/" + page) else ""
    items, reports = [], {}
    for c in closures:
        if c["file"] not in reports:
            reports[c["file"]] = frontmatter.split(safefs.read_text(ctx.notes_path, c["file"]))
        detail = relations.details(reports[c["file"]], c["item_id"])
        if detail.get("file") in unit["pages"]:
            items.append({**detail, **c, "key": c["file"] + "#" + c["item_id"]})
    hits = []
    for page in unit["pages"]:
        hits += source_refs.scan(page, safefs.read_text(ctx.notes_path, page), old(page))
    previous_ids = {h["id"] for h in task.get("check_warnings", [])}
    by_id = {h["id"]: h for h in hits}
    for hit in task.get("correction_warnings", []):
        if hit["file"] in unit["pages"] and hit["id"] not in previous_ids:
            by_id.setdefault(hit["id"], hit)
    hits = sorted(by_id.values(), key=lambda h: (h["file"], h.get("line") or 0, h["id"]))
    changed_lines = any(author.part(old(p)) != author.part(safefs.read_text(ctx.notes_path, p))
                        for p in unit["pages"])
    if not items and not hits and not changed_lines:
        return {"unit": unit, "status": "not_checked"}
    inputs.prepare(ctx.notes_path, view, unit, root / "in", old, targeted=True)
    assigned = {"items": [{"key": i["key"], "status": i["status"]} for i in items],
                "hits": [h["id"] for h in hits]}
    safefs.write_json(root, "in/assigned.json", assigned)
    safefs.write_json(root, "in/items.json", items)
    safefs.write_json(root, "in/hits.json", inputs.hits(ctx.notes_path, hits))
    receipt = calls.run(ctx.notes_path, view, root, "recheck", assigned, inspection.role(ctx, task), log=ctx.log,
                        allowed_paths=set(unit["pages"]))
    if receipt["status"] == "reviewed":
        safefs.write_json(ctx.notes_path, f".school-notes/reader/{root.parent.name}/recheck.json", receipt["review"])
    prior = [v for p in unit["pages"] if (v := verdicts.valid(before / "before", p)) is not None]
    return {"unit": unit, "hits": hits, "items": items, "prior_pages": prior,
            "before": str(before / "before"), **receipt}


def apply(ctx, task, saved):
    written, findings, notes = [], [], []
    for entry in saved["units"]:
        if entry["status"] != "reviewed":
            continue
        review = entry["review"]
        written += _items(ctx.notes_path, review["items"])
        new = report.list_findings(ctx.notes_path, entry["hits"], review["hits"])
        before = Path(entry.get("before", str(inspection.folder(task) / "correction/before")))
        def old(page):
            return safefs.read_text(before, page) if safefs.is_file(before, page) else ""
        new += review.get("findings", [])
        new = [report.figure_quote(ctx.notes_path, f) for f in new]
        new, outside = scope.partition(new, old, lambda p: safefs.read_text(ctx.notes_path, p), entry.get("unit", {}).get("pages", [f["file"] for f in new]))
        new, feedback, _ = report.prepare(ctx.notes_path, new, outside)
        findings += [{**f, "origin": "recheck"} for f in new]
        notes += review["owner_notes"] + feedback
        _carry_verdicts(ctx, task, entry, new)
    if findings or notes:
        path = task.get("inspection_report")
        written.append(report.append(ctx.notes_path, path, findings, notes, f"recheck-{task.get('attempt', 1)}"))
    task.update(inspection_receipts=saved["receipts"], recheck_owner_notes=notes)
    steps.record_tool_files(task, ctx.notes_path, written + [verdicts.PATH, "docs/review/warning-verdicts.json"])


def _items(repo, items):
    written = []
    for item in items:
        if item["verdict"] in ("accept", "keep"):
            written.append(relations.reply(repo, item["key"], item["verdict"], item["answer"]))
        elif item["verdict"] == "not-ok":
            written.append(report.reopen(repo, item["key"], item["answer"]))
        else:
            path, _ = apply_item(repo, {"status": "fixed"}, item)
            if path:
                written.append(path)
    return written


def _carry_verdicts(ctx, task, entry, new):
    review = entry["review"]
    # A targeted result only carries forward an existing full reader verdict.
    originals = {p["file"]: p for p in task.get("reader_pages", []) + entry.get("prior_pages", [])}
    for page in sorted(originals.keys() & set(entry.get("unit", {}).get("pages", originals))):
        own = {i["key"] for i in entry["items"] if i.get("file") == page or
               relations.details(safefs.read_text(ctx.notes_path, i["file"]), i["item_id"]).get("file") == page}
        judged = [i for i in review["items"] if i["key"] in own]
        new_on_page = any(page in (f["file"], f.get("reported_file")) for f in new)
        if all(i["verdict"] in ("ok", "accept") for i in judged) and not new_on_page:
            open_items = any(i.get("file") == page and i["status"] in ("open", "owner")
                             for i in relations.inventory(ctx.notes_path)["items"].values())
            verdicts.record(ctx.notes_path, [{"file": page, "verdict": "changes" if open_items else "ok"}],
                            {page: units.page_key(ctx.notes_path, page)}, entry["model"], task.data["created"])
