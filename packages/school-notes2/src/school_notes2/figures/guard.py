"""Writer-side prevention of bitmap self-insertion. A writer-drawn SVG or inline Mermaid
needs no commission (6b); a raster image keeps the rights gate (commission and review)."""

from ..state import safefs
from ..wiki.pages import links, resolve, wiki_pages


def check(g) -> list:
    from ..wiki.guard import Violation
    out = []
    changed = {c.path for c in g.changes if c.status != "deleted"}
    assets = {p for p in changed if p.startswith("wiki/")}
    pages = {p for p in changed if p.startswith("wiki/") and p.endswith(".md")}
    if assets:
        pages.update(p for p in wiki_pages(g.worktree) if any(
            link.image and resolve(p, link.target) in assets
            for link in links(safefs.read_text(g.worktree, p))))
    for page in sorted(pages):
        out += _images(g, page, safefs.read_text(g.worktree, page), Violation)
    return out


def _images(g, page, text, violation):
    from ..wiki import markers
    from ..wiki.guard import parts_hash
    out = []
    base = (g.base_content(page) or b"").decode("utf-8", "replace")
    previous = {resolve(page, link.target) for link in links(base) if link.image}
    tool_banner = g.tool_parts.get(page) == parts_hash(text)
    for link in links(text):
        asset = resolve(page, link.target)
        if not link.image or not asset or not asset.startswith("wiki/") or asset.endswith(".svg"):
            continue
        old = g.base_content(asset)
        if not safefs.is_file(g.worktree, asset):
            continue  # the link check reports missing assets
        current = safefs.read_bytes(g.worktree, asset)
        if asset in previous and old == current:
            continue
        # Tool-generated figure blocks are checked byte-for-byte by the existing guard.
        if any(text.count("\n", 0, start) + 1 < link.line < text.count("\n", 0, end) + 1
               and (name == "lesson-banner" and tool_banner or
                    name.startswith("figure-") and _accepted(g.worktree, page, name[7:]))
               for start, end, name in markers.spans(text)):
            continue
        out.append(violation(page, "new or changed image must remain a figure/image marker until independent acceptance", False))
    return out


def _accepted(repo, page, fid):
    from . import context
    record = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
    try:
        return (record["commission"]["page"] == page and record["verdict"]["verdict"] == "accept"
                and record["verdict"]["key"] == context.verdict_key(repo, record["commission"], record["candidate"]))
    except (KeyError, ValueError, OSError):
        return False
