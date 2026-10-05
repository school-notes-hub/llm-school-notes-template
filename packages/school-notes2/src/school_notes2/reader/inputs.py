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


def prepare(repo: Path, view: Path, unit: dict, folder: Path, old_text, *, targeted=False) -> dict:
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
                      "text": "" if targeted else text,
                      "changed_lines": excerpts(old_text(page), safefs.read_text(repo, page)) if targeted else [],
                      "questions": [] if targeted else questions,
                      "decisions": frontmatter.split(text).meta.get("decisions", []),
                      "items": {} if targeted else ids.get("items", {}),
                      "diff": "".join(difflib.unified_diff(old_text(page).splitlines(True),
                                                        text.splitlines(True), fromfile=page, tofile=page))})
    safefs.write_json(folder, "assigned.json", assigned)
    safefs.write_json(folder, "pages.json", pages)
    return assigned


def changed(old, new):
    """New-side line numbers that differ from the old text (a plain line diff)."""
    a, b = old.splitlines(), new.splitlines()
    return {n + 1 for tag, _, _, start, end in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if tag != "equal" for n in range(start, end)}


def excerpts(old, new):
    numbers = changed(old, new)
    return [{"line": n, "text": line} for n, line in enumerate(new.splitlines(), 1) if n in numbers]
