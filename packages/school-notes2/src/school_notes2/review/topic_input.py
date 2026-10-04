"""One topic's complete, ordered source context and still-open assignments."""

from pathlib import PurePosixPath

from ..figures import commissions
from ..reader import inputs
from ..repair import queue
from ..state import safefs
from ..wiki import footnotes, markers, pages, source_refs
from . import relations, topics, warnings


def sources(work, topic):
    book = queue.inventory(work)
    if topic not in book:
        return []
    related = queue.related(topic, book)
    logs = [p for p in [topic, *related] if p in book and book[p].meta.get("type") == "lesson-notes"]
    index = str(PurePosixPath(topic).parent / "index.md")
    body = markers.read(safefs.read_text(work, index), "lessons") if safefs.is_file(work, index) else ""
    ordered = [pages.resolve(index, link.target) for link in pages.links(body or "")]
    logs.sort(key=lambda p: (ordered.index(p) if p in ordered else len(ordered), p))
    result = []
    for page in list(dict.fromkeys(logs + [topic])):
        # A one-page book makes queue.sources preserve this log's own source order.
        result += queue.sources(work, page, {page: book[page]})
    return list(dict.fromkeys(result))


def prepare(repo, work, task, unit, folder):
    folder.mkdir(parents=True, exist_ok=True)
    known = relations.inventory(work)
    closed = topics.closure_changes(repo, unit["base"], task.get("H"))
    members = set(unit["pages"])
    embedded = relations.related_pages(work)
    items = []
    for key, item in known["items"].items():
        path = item.get("file", "")
        uses = embedded.get(path, [])
        primary = min(uses, key=lambda p: (commissions.topic(work, p), p)) if uses else path
        if primary not in members:
            continue
        if item["status"] not in ("open", "owner") and key not in closed:
            continue
        item = {**item, "key": key}
        if key in closed:
            item["fix_commit"] = _closure_is_fix(repo, unit, key)
        items.append(item)
    hits = []
    for path in unit["pages"]:
        if path.endswith((".md", ".svg")):
            current, previous = safefs.read_text(work, path), topics.text(repo, unit["base"], path)
            hits += source_refs.scan(path, current, previous)
            hits += footnotes.scan(path, current, previous)
    ids = {i.get("hit_id") for i in known["items"].values()}
    hits = warnings.pending(work, hits, ids)
    assigned = {"pages": unit["assigned_pages"], "items": [{"key": i["key"], "status": i["status"]} for i in items],
                "hits": [h["id"] for h in hits]}
    safefs.write_json(folder, "assigned.json", assigned)
    safefs.write_text(folder, "diff.patch", topics.patch(repo, unit, task.get("H")))
    safefs.write_json(folder, "input.json", {
        "mode": unit["mode"], "topic": unit["topic"], "base": unit["base"], "H": task.get("H"),
        "pages": unit["pages"], "context": unit["context"], "sources": sources(work, unit["topic"]),
        "textbooks": [{"file": p, "lines": [line for line in safefs.read_text(work, p).splitlines() if "🔖" in line]}
                      for p in unit["pages"] if p.endswith(".md")],
        "relations": {p: data for p, data in relations.reviewer_inventory(work)["pages"].items()
                      if p in members or p in unit["context"]}, "items": items,
        "hits": inputs.hits(work, hits)})
    return {"assigned": assigned, "items": items, "hits": hits}


def _closure_is_fix(repo, unit, key):
    for commit in reversed(unit["commits"]):
        parent = repo.out("rev-parse", f"{commit}^").strip()
        if key in topics.closure_changes(repo, parent, commit):
            return topics.is_fix(repo, commit)
    return False
