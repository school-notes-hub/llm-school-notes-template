"""Fixed, generated pending notices; no model participates in export."""

import re

from ..figures import commissions, pending, requests
from ..state import safefs
from ..wiki import drafts, frontmatter, markers
from . import verdicts, new_pages

PAGE = "⏳ Ezt az oldalt még ellenőrizzük.\n"
SECTION = "⏳ Ezt a részt még ellenőrizzük.\n"
FIGURE = "⏳ Ehhez a részhez ábra készül.\n"


def refresh(repo, pages, *, write=None, remove_only=False):
    write = write or (lambda path, text: safefs.write_text(repo, path, text))
    waiting = pending.load(repo)
    waiting += [{"commission": r} for r in requests.active(repo)]
    waiting = sorted({e["commission"]["id"]: e for e in waiting}.values(),
                     key=lambda e: (e["commission"]["page"], e["commission"]["id"]))
    written = []
    for page in sorted(set(pages)):
        if not safefs.is_file(repo, page) or not page.endswith(".md"):
            continue
        original = safefs.read_text(repo, page)
        text = markers.clean_nested_notices(original)
        names = {name for _, _, name in markers.spans(text)
                 if markers.is_notice(name)}
        existing = {markers.read(text, name) for name in names}
        page_notice = new_pages.eligible(repo, page) and not verdicts.ever_reviewed(repo, page)
        wanted = PAGE if page_notice else drafts.NOTICE if frontmatter.split(text).meta.get("status") == "draft" else None
        # An unchanged page notice stays where it is (also a 2.5.1 placement): no needless edit.
        kept = {"pending"} if wanted is not None and markers.names(text).count("pending") == 1 \
            and markers.read(text, "pending") == wanted else set()
        text = markers.remove(text, names - kept)
        placements = _placements(text, waiting, page, page_notice and not kept, not kept)
        for cut, (_, name, body) in sorted(placements.items(), reverse=True):
            # The one-time refresh only takes notices away, except a continuing topic's own
            # notice: the owner's "real gap" rule always shows it (a draft may have carried
            # the old page notice instead).
            if remove_only and body not in existing and body != drafts.NOTICE:
                continue
            text = text[:cut] + "\n" + markers.wrap(name, body) + "\n" + text[cut:]
        if text != original:
            write(page, text)
            written.append(page)
    return written


def _placements(text, waiting, page, page_notice, draft_notice=True):
    placements = {}
    def add(cut, priority, name, body):
        cut = markers.outside(text, cut)
        candidate = (priority, name, body)
        placements[cut] = min(placements.get(cut, candidate), candidate)
    if page_notice:
        add(markers.fixed_place(text, "pending"), 1, "pending", PAGE)
    elif draft_notice and frontmatter.split(text).meta.get("status") == "draft":
        add(markers.fixed_place(text, "pending"), 4, "pending", drafts.NOTICE)
    _figure_placements(text, waiting, page, add)
    return placements


def _figure_placements(text, waiting, page, add):
    for entry in waiting:
        brief = entry["commission"]
        if brief["page"] == page:
            for match in re.finditer(commissions.MARKER.pattern + r"(?:\n|$)", text):
                if match[1] == brief["id"]:
                    add(match.end(), 0, "pending-figure-" + brief["id"], FIGURE)
