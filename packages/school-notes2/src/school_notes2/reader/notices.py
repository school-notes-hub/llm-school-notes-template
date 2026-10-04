"""Fixed, generated pending notices; no model participates in export."""

import hashlib
import re

from ..figures import commissions, pending, requests
from ..review import figure_waiting, relations
from ..state import safefs
from ..wiki import drafts, frontmatter, lesson_log, markers
from . import verdicts

PAGE = "⏳ Ezt az oldalt még ellenőrizzük.\n"
SECTION = "⏳ Ezt a részt még ellenőrizzük.\n"
FIGURE = "⏳ Ehhez a részhez ábra készül.\n"


def refresh(repo, pages):
    known = relations.inventory(repo)["items"]
    waiting = pending.load(repo)
    waiting += [{"commission": r} for r in requests.active(repo)]
    waiting = list({e["commission"]["id"]: e for e in waiting}.values())
    nightly_waiting = figure_waiting.active(repo)
    written = []
    for page in sorted(set(pages)):
        if not safefs.is_file(repo, page) or not page.endswith(".md"):
            continue
        original = safefs.read_text(repo, page)
        text = original
        for name in markers.names(text):
            if name.startswith(("pending-section-", "pending-figure-")):
                text = markers.replace(text, name, "")
        items = [i for i in known.values() if i.get("file") == page and i["status"] in ("open", "owner")]
        page_notice = verdicts.valid(repo, page) is None or any(i.get("unlocated") for i in items)
        sections = set()
        for item in items:
            quote = item.get("quote", "")
            pattern = r"\s+".join(re.escape(w) for w in quote.split())
            found = re.search(pattern, text) if pattern else None
            headings = list(re.finditer(r"^#{1,6} .+$", text[:found.start()], re.M)) if found else []
            if headings:
                sections.add(headings[-1][0])
            else:
                page_notice = True
        for heading in sorted(sections):
            name = "pending-section-" + hashlib.sha256(heading.encode()).hexdigest()[:12]
            if name in markers.names(text):
                text = markers.replace(text, name, SECTION)
            else:
                text = text.replace(heading + "\n", heading + "\n\n" + markers.wrap(name, SECTION) + "\n", 1)
        notice = PAGE if page_notice else drafts.NOTICE if frontmatter.split(text).meta.get("status") == "draft" else ""
        text = lesson_log.after_header(text, "pending", notice)
        for entry in sorted(waiting, key=lambda e: (e["commission"]["page"], e["commission"]["id"])):
            brief = entry["commission"]
            if brief["page"] != page:
                continue
            name = "pending-figure-" + brief["id"]
            if name in markers.names(text):
                text = markers.replace(text, name, FIGURE)
            else:
                pattern = re.compile(commissions.MARKER.pattern + r"(?:\n|$)")
                text = pattern.sub(lambda m: m[0] + "\n" + markers.wrap(name, FIGURE) + "\n"
                                   if m[1] == brief["id"] else m[0], text)
        for entry in nightly_waiting:
            spec = entry["spec"]
            if spec["page"] == page:
                text = _night_figure(text, spec)
        if text != original:
            safefs.write_text(repo, page, text)
            written.append(page)
    return written


def _night_figure(text, spec):
    name = "pending-figure-" + spec["id"]
    if name in markers.names(text):
        return markers.replace(text, name, FIGURE)
    heading = next((h[0] for h in re.finditer(r"^#{1,6} (.+)$", text, re.M)
                    if h[1] == spec["anchor"]), None)
    if heading:
        return text.replace(heading + "\n", heading + "\n\n" + markers.wrap(name, FIGURE) + "\n", 1)
    return lesson_log.after_header(text, name, FIGURE)
