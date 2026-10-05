"""P5: one independent recheck of every author-changed page of the run, against the base.

The reviewer judges the run's closures (fixed: ok/not-ok, disagree: accept/keep) and names
the file and line of each new finding. A learning-blocking finding on a changed line is an
item for the next run (chain +1, deeper than three goes to the owner); everything else is an
owner note. No page is skipped: the comparison is always the run's base, never a round."""

from ..review.severity import is_error
from ..reader import calls, inputs, report, units
from ..review import relations
from ..review.relations import apply_item
from ..state import safefs
from ..wiki import author, frontmatter
from ..wiki.pages import wiki_pages
from . import inspection_runtime as runtime, steps


def closures(task):
    return [c for c in (task.get("inspection_result") or {}).get("review_closure", [])
            if c["status"] in ("fixed", "disagree")]


def pages(ctx, task, closed):
    known = relations.inventory(ctx.notes_path)["items"]
    published = set(wiki_pages(ctx.notes_path))
    found = {p for p in steps.llm_snapshot(ctx, task) if p in published}
    found.update(known.get(c["file"] + "#" + c["item_id"], {}).get("file", "") for c in closed)
    found.update(s["brief"]["page"] for s in task.get("inspection_figures", []))
    return sorted(found & published)


def run(ctx, task, view):
    closed = closures(task)
    return [check_page(ctx, task, view, page, closed) for page in pages(ctx, task, closed)]


def check_page(ctx, task, view, page, closed):
    from .inspection import old_text
    repo = ctx.notes_path
    root = runtime.folder(task) / "recheck" / units.slug(page)
    old = old_text(ctx, task, page)
    reports, items = {}, []
    for c in closed:
        if c["file"] not in reports:
            reports[c["file"]] = frontmatter.split(safefs.read_text(repo, c["file"]))
        detail = relations.details(reports[c["file"]], c["item_id"])
        if detail.get("file") == page:
            items.append({**detail, **c, "key": c["file"] + "#" + c["item_id"]})
    figures = [s for s in task.get("inspection_figures", []) if s["brief"]["page"] == page]
    if not items and not figures and author.part(old) == author.part(safefs.read_text(repo, page)):
        return {"page": page, "status": "not_checked"}
    unit = {"topic": page, "pages": [page], "context": [], "keys": {page: units.page_key(repo, page)}}
    inputs.prepare(repo, view, unit, root / "in", lambda _: old, targeted=True)
    assigned = {"pages": [{"file": page}], "items": [{"key": i["key"], "status": i["status"]} for i in items]}
    safefs.write_json(root, "in/assigned.json", assigned)
    safefs.write_json(root, "in/items.json", items)
    receipt = calls.run(repo, view, root, "recheck", assigned, runtime.role(ctx, task), log=ctx.log,
                        allowed_paths={page})
    return {"page": page, "items": items, "old": old, **receipt}


def apply(ctx, task, saved):
    repo, written, findings, notes = ctx.notes_path, [], [], list(saved.get("notes", []))
    known = relations.inventory(repo)["items"]
    for entry in saved["recheck"]:
        if entry["status"] != "reviewed":
            if entry["status"] != "not_checked":
                notes.append(f"A visszaellenőrzés nem futott le ({entry['page']}): {entry.get('reason', '')}")
            continue
        review = entry["review"]
        written += _items(repo, review["items"])
        new = [report.figure_quote(repo, f) for f in review.get("findings", [])]
        advice = [f for f in new if not is_error(f)]
        changed = inputs.changed(entry.get("old", ""), safefs.read_text(repo, entry["page"]))
        corrected = {i["key"] for i in entry.get("items", [])}
        for finding in (report.locate(repo, f) for f in new if is_error(f)):
            key = finding.get("item_key")
            if key in corrected:
                written.append(report.reopen(repo, key, f"{finding['file']}: {finding['quote']} — {finding['problem']}"))
            elif finding["line"] in changed:
                depth = 1 + max((known.get(i["key"], {}).get("chain", 0) for i in entry.get("items", [])), default=0)
                findings.append({**finding, "origin": "recheck", "relates_to": finding.get("relates_to"), "chain": depth,
                                 **({"owner_status": "owner"} if depth > 3 else {})})
            else:
                notes.append(f"Nem változott sor ({finding['file']}:{finding['line'] or '?'}): {finding['problem']}")
        _, notes = report.advice_notes(advice, notes + review["owner_notes"])
    notes = sorted(set(notes))
    if findings or notes:
        from . import journal
        journal.settle(ctx, task)
        write = lambda repo_, rel, text: journal.write(ctx, task, rel, text, whole=True)
        path = report_path(ctx, task, write)
        written.append(report.append(repo, path, findings, notes, f"recheck-{task.get('attempt', 1)}", write=write))
    task.update(inspection_receipts=saved["receipts"], recheck_owner_notes=notes)
    steps.record_tool_files(task, repo, written)


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


def report_path(ctx, task, write=None):
    path = task.get("inspection_report")
    if path is None:
        path = f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
        report.write(ctx.notes_path, path, [], [], "recheck", task.get("base"), task.data["created"], write=write)
        task.update(inspection_report=path)
    return path
