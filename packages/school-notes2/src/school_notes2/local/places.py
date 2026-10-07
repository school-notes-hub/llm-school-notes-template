"""Read-only content facts `sn done` counts (moved from the VM flows; only the scans, without
the fix-run items). Every list is in content order (page, line, id)."""

from pathlib import Path

from ..figures import commissions, context, pending
from ..state import safefs
from ..wiki.check import textbook_lines as page_textbook_lines
from ..wiki.pages import links, resolve, wiki_pages

REQUEST = "<!-- figure-request: "


def missing_parts(repo: Path) -> tuple[set[str], set[str]]:
    """(figure places without an accepted figure, image links to a missing file)."""
    missing = set(commissions.markers(repo))
    for fid in sorted(missing):
        try:
            evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
            brief = safefs.read_json(repo, f".school-notes/figures/{fid}.json", evidence.get("commission"))
            candidate = safefs.read_json(repo, f".school-notes/figures/{fid}/figure.json", evidence.get("candidate"))
            if candidate and candidate.get("state") == "no-figure":
                missing.remove(fid)
            elif brief and candidate and evidence.get("verdict", {}).get("verdict") == "accept" and (
                    evidence["verdict"]["key"] == context.verdict_key(repo, brief, candidate)):
                missing.remove(fid)
        except (ValueError, OSError, KeyError):
            pass
    broken = set()
    for page in sorted(wiki_pages(repo)):
        for link in links(safefs.read_text(repo, page)):
            if link.image and (target := resolve(page, link.target)) and not safefs.is_file(repo, target):
                broken.add(target)
    return missing, broken


def orphan_places(repo: Path) -> list[dict]:
    """An orphan figure place – a figure or image marker with no pending figure and no accepted
    figure behind it – keeps a picture from the learner: {id, page, line, quote}. A
    `figure-request` marker is never one (it waits for a licence through
    docs/figure-requests.json). A marker id repeated on one page is one place (its first line)."""
    missing, _ = missing_parts(repo)
    queued = {e["commission"]["id"] for e in pending.load(repo)}
    found = commissions.markers(repo)
    out = {}
    for fid in sorted(missing - queued):
        for page, position in sorted(found.get(fid, [])):
            text = safefs.read_text(repo, page)
            if text.startswith(REQUEST, position):
                continue
            line = text.count("\n", 0, position) + 1
            out.setdefault((page, fid), {"id": fid, "page": page, "line": line,
                                         "quote": text.split("\n")[line - 1].strip()})
    return sorted(out.values(), key=lambda p: (p["page"], p["line"], p["id"]))


def textbook_lines(repo: Path) -> list[dict]:
    """A 🔖 textbook line without any lesson or page number tells the learner nothing: every
    page with such a line, its first one: {page, line, quote}, in page order."""
    out = []
    for page in sorted(wiki_pages(repo)):
        text = safefs.read_text(repo, page)
        lines = page_textbook_lines(page, text)
        if lines:
            out.append({"page": page, "line": lines[0], "quote": text.split("\n")[lines[0] - 1].strip()})
    return out
