"""Fixed, generated pending notices; no model participates in export."""

import hashlib
import re

from ..figures import commissions, pending
from ..review import generated, relations
from ..state import safefs
from ..wiki import drafts, frontmatter, lesson_log, markers
from . import verdicts

PAGE = "⏳ Ezt az oldalt még ellenőrizzük.\n"
SECTION = "⏳ Ezt a részt még ellenőrizzük.\n"
FIGURE = "⏳ Ehhez a részhez ábra készül.\n"


def refresh(repo, pages):
    known = relations.inventory(repo)["items"]
    waiting = pending.load(repo)
    written = []
    for page in sorted(set(pages)):
        if not safefs.is_file(repo, page) or not page.endswith(".md"):
            continue
        original = safefs.read_text(repo, page)
        text = markers.clean_nested_notices(original)
        names = {name for _, _, name in markers.spans(text)
                 if markers.is_notice(name)}
        text = markers.remove(text, names)
        items = [i for i in known.values() if i.get("file") == page and i["status"] in ("open", "owner")
                 and not generated.only_literals(original, i.get("quote", ""))]
        placements = _placements(text, items, waiting, page, verdicts.valid(repo, page) is None)
        for cut, (_, name, body) in sorted(placements.items(), reverse=True):
            text = text[:cut] + "\n" + markers.wrap(name, body) + "\n" + text[cut:]
        if text != original:
            safefs.write_text(repo, page, text)
            written.append(page)
    return written


def _placements(text, items, waiting, page, page_notice):
    placements = {}
    def add(cut, priority, name, body):
        cut = markers.outside(text, cut)
        candidate = (priority, name, body)
        placements[cut] = min(placements.get(cut, candidate), candidate)
    headings = list(re.finditer(r"^#{1,6} .+$", text, re.M))
    blocks = markers.spans(text)
    for item in items:
        found = generated.matches(text, item.get("quote", ""))
        # Prefer an authored occurrence when the same words also occur in tool text.
        found = [m for m in found if not any(a <= m.start() and m.end() <= b for a, b, _ in blocks)]
        preceding = [h for h in headings if found and h.start() <= found[0].start()]
        if item.get("unlocated") or not preceding:
            page_notice = True
            continue
        heading = preceding[-1]
        occurrence = sum(h[0] == heading[0] for h in preceding)
        identity = heading[0] + (f"\n{occurrence}" if occurrence > 1 else "")
        name = "pending-section-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        add(heading.end() + int(text[heading.end():heading.end() + 1] == "\n"), 2, name, SECTION)
    if page_notice:
        add(lesson_log.header_end(text), 1, "pending", PAGE)
    elif frontmatter.split(text).meta.get("status") == "draft":
        add(lesson_log.header_end(text), 4, "pending", drafts.NOTICE)
    for entry in waiting:
        brief = entry["commission"]
        if brief["page"] == page:
            for match in re.finditer(commissions.MARKER.pattern + r"(?:\n|$)", text):
                if match[1] == brief["id"]:
                    add(match.end(), 0, "pending-figure-" + brief["id"], FIGURE)
    return placements
