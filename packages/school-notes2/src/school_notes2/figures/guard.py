"""Writer-side prevention of SVG/bitmap self-insertion; Mermaid remains inline."""

import hashlib
from collections import Counter

from ..state import safefs
from ..wiki.pages import links, resolve, wiki_pages
from . import commissions


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
        text = safefs.read_text(g.worktree, page)
        old = (g.base_content(page) or b"").decode("utf-8", "replace")
        out += _images(g, page, text, Violation)
        previous = Counter(m[1] for m in commissions.MERMAID.finditer(old))
        for match in commissions.MERMAID.finditer(text):
            if previous[match[1]]:
                previous[match[1]] -= 1
                continue
            if not _assigned_mermaid(g.worktree, page, match[1]):
                out.append(Violation(page, "new or changed Mermaid needs a figure commission and rendered independent review", False))
    return out


def _images(g, page, text, violation):
    out = []
    for link in links(text):
        asset = resolve(page, link.target)
        if not link.image or not asset or not asset.startswith("wiki/"):
            continue
        old = g.base_content(asset)
        if not safefs.is_file(g.worktree, asset):
            continue  # the link check reports missing assets
        current = safefs.read_bytes(g.worktree, asset)
        if old == current or asset in g.tool_files:
            continue
        # Tool-generated figure blocks are checked byte-for-byte by the existing guard.
        from ..wiki import markers
        if any(_accepted(g.worktree, page, name[7:])
               and any(asset == resolve(page, child.target)
                       for child in links(markers.read(text, name) or "") if child.image)
               for name in markers.names(text) if name.startswith("figure-")):
            continue
        out.append(violation(page, "new or changed image must remain a figure/image marker until independent acceptance", False))
    return out


def _assigned_mermaid(repo, page, source):
    from . import context
    for fid, occurrences in commissions.markers(repo).items():
        if len(occurrences) != 1 or occurrences[0][0] != page:
            continue
        try:
            brief = commissions.read(repo, fid)
            candidate = commissions.candidate(repo, brief)
            if (brief["page"] == page and candidate.get("mermaid") == hashlib.sha256(source.encode()).hexdigest()
                    and context.mermaid_source(repo, brief, candidate) == source):
                return True
        except (OSError, ValueError):
            continue
    return False


def _accepted(repo, page, fid):
    from . import context
    record = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
    try:
        return (record["commission"]["page"] == page and record["verdict"]["verdict"] == "accept"
                and record["verdict"]["key"] == context.verdict_key(repo, record["commission"], record["candidate"]))
    except (KeyError, ValueError, OSError):
        return False
