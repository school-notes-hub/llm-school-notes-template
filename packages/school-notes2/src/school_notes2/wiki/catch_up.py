"""Neutral catch-up navigation, derived from lesson frontmatter (plan 7.13)."""

import re

from . import markers

NAME = "catch-up"
LEGACY = re.compile(r"^# (?:🤒|📝) (?:Pótolandó|To catch up)\s*$", re.M)
BOUNDARY = re.compile(r"^(?:# |<!-- school-notes:generated |<br\s*/?>)", re.M)
BACK_LINK = re.compile(r"^\[.*\]\(\.\./index\.md\)\s*$", re.M)


def mark(meta: dict) -> str:
    return {"open": "📝 ", "done": "✅ "}.get(meta.get("catch_up"), "")


def update(text: str, pages: list) -> str:
    """Pages arrive in the index's date/file order; legacy handwritten lists are replaced.

    No prose is inferred from notebook origin, and no transient status enters a banner.
    """
    lines = [f"* [{p.meta.get('title', p.file)}]({p.file})" for p in pages
             if p.meta.get("catch_up") == "open"]
    # Hungarian renderer wording, like generate.TABLE_HEAD; see README localization note.
    body = "# 📝 Pótolandó\n\n" + "\n".join(lines) + "\n" if lines else ""
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
