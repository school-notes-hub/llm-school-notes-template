"""Neutral catch-up navigation, derived from lesson frontmatter (plan 7.13)."""

import re

from . import markers

NAME = "catch-up"
LEGACY = re.compile(r"^# (?:🤒|📝) (?:Pótolandó|To catch up)\s*$", re.M)
BOUNDARY = re.compile(r"^(?:# |<!-- school-notes:generated |<br\s*/?>)", re.M)
BACK_LINK = re.compile(r"^\[.*\]\(\.\./index\.md\)\s*$", re.M)


# Neutral by rule (plan 7.13, learner AGENTS.md): no illness icon, no absence statement.
MARKS = {"open": "📝 ", "done": "✅ "}
# Hungarian renderer wording, like generate.TABLE_HEAD and the PROFILE catch-up notice.
INTRO = "Ezeknek az óráknak az anyagát pótolnod kell: írd be a füzetedbe (vagy tanuld meg), és szólj, ha megvan."
LEGEND = {"open": "A 📝 jel pótolandó órát mutat: az anyagát írd be a füzetedbe (vagy tanuld meg), és szólj, ha megvan.",
          "done": "A ✅ jel a már pótolt órát mutatja."}


def mark(meta: dict) -> str:
    return MARKS.get(meta.get("catch_up"), "")


def legend(states: set) -> str:
    """The lessons table's one-line key for the marks it shows, in a fixed order."""
    return " ".join(LEGEND[s] for s in ("open", "done") if s in states)


def update(text: str, pages: list, describe=lambda page: "") -> str:
    """Pages arrive in the index's date/file order; legacy handwritten lists are replaced.

    A line is the page link and `describe(page)`, built from the page's own lesson fields.
    No prose is inferred from notebook origin, and no transient status enters a banner.
    """
    lines = [" - ".join(filter(None, [f"* [{p.meta.get('title', p.file)}]({p.file})", describe(p)]))
             for p in pages if p.meta.get("catch_up") == "open"]
    body = f"# 📝 Pótolandó\n\n{INTRO}\n\n" + "\n".join(lines) + "\n" if lines else ""
    if NAME in markers.names(text):
        return markers.replace(text, NAME, body)
    old = LEGACY.search(text)
    if old:
        end = BOUNDARY.search(text, old.end())
        stop = end.start() if end else len(text)
        return text[:old.start()] + markers.wrap(NAME, body) + "\n" + text[stop:]
    if not lines:
        return text
    back = BACK_LINK.search(text)
    if back:
        pos = back.end()
    else:
        block = markers.BLOCK.search(text)
        pos = block.start() if block else len(text)
    return text[:pos] + "\n\n" + markers.wrap(NAME, body) + "\n" + text[pos:]
