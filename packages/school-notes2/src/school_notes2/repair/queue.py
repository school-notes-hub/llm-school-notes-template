"""Repair inventory and ordering. Only --queue builds/reorders; runs change statuses."""

from datetime import date
from pathlib import PurePosixPath

from ..schemas import validate, SchemaError
from ..state import safefs
from ..state.errors import NeedsOwner
from ..wiki import pages

PATH = "docs/repair-queue.json"
DEPENDENT = ("lesson-notes", "chapter-summary", "review")


def inventory(repo) -> dict:
    book = {}
    for rel in sorted(pages.wiki_pages(repo)):
        if PurePosixPath(rel).name in pages.RESERVED:
            continue
        page = pages.read_page(repo, rel)
        if page.meta.get("type"):
            book[rel] = page
    return book


def topic_links(rel, page) -> list[str]:
    return list(dict.fromkeys(target for lesson in page.meta.get("lessons", [])
                             for link in lesson.get("topics", [])
                             if (target := pages.resolve(rel, link.split("#", 1)[0]))))


def dependencies(rel, book) -> list[str]:
    page = book[rel]
    kind = page.meta.get("type")
    topics = {p for p, value in book.items() if value.meta.get("type") not in DEPENDENT}
    if kind == "lesson-notes":
        return topic_links(rel, page)  # Missing topics stay blocking, never silently omitted.
    if kind == "chapter-summary":
        return sorted(p for p in topics if PurePosixPath(p).parent == PurePosixPath(rel).parent
                      and page.meta.get("chapter") is not None
                      and book[p].meta.get("chapter") == page.meta["chapter"])
    if kind == "review":
        return sorted({target for link in pages.links(page.body) if not link.image
                       and (target := pages.resolve(rel, link.target)) in topics})
    return []


def related(rel, book) -> list[str]:
    if book[rel].meta.get("type") in DEPENDENT:
        return dependencies(rel, book)
    return [p for p in book if rel in dependencies(p, book)]


def _date(page) -> str:
    dates = []
    for lesson in page.meta.get("lessons", []):
        try:
            dates.append(date.fromisoformat(str(lesson.get("date", ""))).isoformat())
        except ValueError:
            pass  # Never derive a lesson date from the file name or date_note.
    return max(dates, default="")


def build(repo, previous=None) -> dict:
    book = inventory(repo)
    previous = previous if previous is not None else load(repo)
    old = {i["page"]: i for i in previous.get("items", [])}
    from ..figures import requests
    approved = {r["page"] for r in requests.approved(repo)}
    items = []
    for rel, page in book.items():
        before = old.get(rel, {})
        priority = before.get("priority")
        if priority is not None and (type(priority) is not int or priority < 0):
            raise NeedsOwner(f"{rel}: priority must be a nonnegative integer or null",
                             todo="edit docs/repair-queue.json, then run repair --queue")
        links = related(rel, book)
        matches = 0  # No text heuristic orders the queue; the owner's priority does.
        items.append({"page": rel, "kind": page.meta.get("type", "concept"),
                      "status": "pending" if rel in approved and before.get("status") == "done" else before.get("status", "pending"),
                      "priority": priority,
                      "matches": matches, "urgent": before.get("urgent", False),
                      "last_lesson": max([_date(page)] + [_date(book[p]) for p in links if p in book]),
                      "depends_on": dependencies(rel, book)})
    items.sort(key=sort_key)
    figures = _figures(repo, book, previous.get("figures", []))
    data = {"schema": 1, "items": items, "figures": figures}
    validate("repair-queue", data)
    return data


def sort_key(item) -> tuple:
    stamp = date.fromisoformat(item["last_lesson"]).toordinal() if item["last_lesson"] else 0
    return (not (item["urgent"] or item["matches"] > 0),
            item["priority"] if item["priority"] is not None else float("inf"),
            -item["matches"], -stamp, item["page"])


def _figures(repo, book, previous) -> list[dict]:
    old = {i["file"]: i for i in previous}
    embeds = {}
    for rel, page in book.items():
        for link in pages.links(page.body):
            target = pages.resolve(rel, link.target)
            if link.image and target:
                embeds.setdefault(target, set()).add(rel)
    out = []
    for rel in safefs.glob(repo, "wiki/assets", "wiki/assets/**/*.svg"):
        digest = pages.sha256(repo, rel)
        before = old.get(rel, {})
        out.append({"file": rel, "sha256": digest, "pages": sorted(embeds.get(rel, [])),
                    "matches": 0,
                    "status": before.get("status", "pending") if before.get("sha256") == digest else "pending"})
    return out


def load(repo) -> dict:
    return validated(safefs.read_json(repo, PATH))


def validated(data) -> dict:
    if data is None:
        return {"schema": 1, "items": [], "figures": []}
    try:
        validate("repair-queue", data)
        for key, identity in (("items", "page"), ("figures", "file")):
            ids = [i[identity] for i in data[key]]
            if len(ids) != len(set(ids)):
                raise SchemaError(f"duplicate {identity} in {key}")
    except SchemaError as exc:
        raise NeedsOwner(f"invalid repair queue: {exc}",
                         todo="correct docs/repair-queue.json, then run repair --queue") from exc
    return data


def next_item(data) -> dict | None:
    states = {i["page"]: i["status"] for i in data["items"]}
    return next((i for i in data["items"] if i["status"] == "pending"
                 and all(states.get(p) == "done" for p in i["depends_on"])), None)


def require_ready(rel, data, book) -> None:
    if rel not in book:
        raise NeedsOwner("repair target must be an existing content page",
                         todo="use a wiki/<subject>/<page>.md path")
    states = {i["page"]: i["status"] for i in data["items"]}
    waiting = [p for p in dependencies(rel, book) if states.get(p) != "done"]
    if waiting:
        raise NeedsOwner("repair dependencies are not done: " + ", ".join(waiting),
                         todo="repair the topic pages first")


def sources(repo, rel, book) -> list[str]:
    """Complete source folders, in lesson/source order, then path; no source cropping."""
    linked = related(rel, book)
    logs = [p for p in [rel, *linked] if p in book and book[p].meta.get("type") == "lesson-notes"]
    out = []
    for page_rel in list(dict.fromkeys(logs + [rel])):
        meta = book[page_rel].meta
        roots = [pages.resolve(page_rel, s["resource"]) for s in meta.get("sources", [])
                 if isinstance(s, dict) and s.get("resource")]
        folders = meta.get("source_file", [])
        if isinstance(folders, str):
            folders = [folders]
        roots += ["sources/" + f.removeprefix("sources/") for f in folders]
        for root in roots:
            if not root or not root.startswith("sources/"):
                continue
            if safefs.is_file(repo, root):
                out.append(root)
                # Extracted documents may refer to images next to the Markdown.
                if root.endswith("document.md"):
                    out += safefs.glob(repo, str(PurePosixPath(root).parent), "sources/**/*")
            elif safefs.is_dir(repo, root.rstrip("/")):
                out += safefs.glob(repo, root.rstrip("/"), "sources/**/*")
    return list(dict.fromkeys(out))
