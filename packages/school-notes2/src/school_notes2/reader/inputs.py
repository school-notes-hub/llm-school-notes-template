"""Allow-listed reader inputs: no sources, evidence, rules or writer decisions."""

import difflib
import re
import subprocess
from pathlib import Path

from ..figures import commissions, context
from ..review import relations
from ..state import safefs
from ..wiki import banners, frontmatter
from ..wiki.pages import wiki_pages
from ..wiki.pages import relative


def preview(repo: Path, destination: Path, briefs: list[dict], render=None) -> None:
    """A wiki-only snapshot with candidate links in place; never a writer-writable mount."""
    destination.mkdir(parents=True, exist_ok=True)
    for rel in safefs.walk_files(repo, "wiki"):
        safefs.write_bytes(destination, rel, safefs.read_bytes(repo, rel))
    for brief in briefs:
        candidate = commissions.candidate(repo, brief)
        if candidate["state"] != "candidate":
            continue
        page = brief["page"]
        text = context.without_replaced(safefs.read_text(destination, page), page, brief.get("replaces"))
        asset = candidate.get("asset", "")
        if render and ("mermaid" in candidate or asset.endswith(".svg")):
            kind = "mermaid" if "mermaid" in candidate else "svg"
            data = context.mermaid_source(repo, brief, candidate).encode() if kind == "mermaid" else safefs.read_bytes(repo, asset)
            try:
                rendered = render(kind, data, brief["id"])
            except (ValueError, OSError, subprocess.TimeoutExpired):
                continue  # The independent figure call records pending; never self-insert.
            asset = f"wiki/assets/reader-preview/{brief['id']}.png"
            safefs.write_bytes(destination, asset, rendered)
        if not asset:
            continue
        link = f"![{candidate['alt']}](<{relative(page, asset)}>)\n\n{candidate['caption']}"
        if "mermaid" in candidate:
            body, _ = context.section(text, brief["anchor"])
            graph = next(m for m in commissions.MERMAID.finditer(body) if m[1] == data.decode())
            offset = text.index(body)
            text = text[:offset + graph.start()] + link + text[offset + graph.end():]
            link = ""
        text = commissions.MARKER.sub(lambda m: link if m[1] == brief["id"] else m[0], text)
        safefs.write_text(destination, page, text)

    for page in sorted(wiki_pages(destination)):
        text = safefs.read_text(destination, page)
        safefs.write_text(destination, page, banners.update(destination, page, text))


def prepare(repo: Path, view: Path, unit: dict, folder: Path, old_text) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    assigned = {"pages": [{"file": p, "key": unit["keys"][p]} for p in unit["pages"]]}
    inventory = relations.reviewer_inventory(repo)["pages"]
    pages = []
    for page in unit["pages"] + unit.get("context", []):
        text = safefs.read_text(view, page)
        ids = inventory.get(page, {})
        questions = []
        for qid in ids.get("questions", []):
            match = re.search(r"<!-- q: " + re.escape(qid) + r" -->\s*([^\n]+)", text)
            questions.append({"id": qid, "text": match[1] if match else ""})
        pages.append({"file": page, "role": "assigned" if page in unit["pages"] else "context",
                      "text": text, "questions": questions,
                      "decisions": frontmatter.split(text).meta.get("decisions", []),
                      "items": ids.get("items", {}),
                      "diff": "".join(difflib.unified_diff(old_text(page).splitlines(True),
                                                        text.splitlines(True), fromfile=page, tofile=page))})
    safefs.write_json(folder, "assigned.json", assigned)
    safefs.write_json(folder, "pages.json", pages)
    return assigned


def hits(repo: Path, items: list[dict]) -> list[dict]:
    out = []
    for item in sorted(items, key=lambda i: (i["file"], i.get("line") or 0, i["id"])):
        text = safefs.read_text(repo, item["file"])
        lines = text.splitlines()
        n = max(0, min(len(lines) - 1, (item.get("line") or 1) - 1))
        start, end = n, n + 1
        for _ in range(2):
            while start > 0 and lines[start - 1].strip():
                start -= 1
            start = max(0, start - 1)
            while end < len(lines) and lines[end].strip():
                end += 1
            end = min(len(lines), end + 1)
        out.append({k: item[k] for k in ("id", "file", "line", "message") if k in item} |
                   {"context": "\n".join(lines[start:end])})
    return out
