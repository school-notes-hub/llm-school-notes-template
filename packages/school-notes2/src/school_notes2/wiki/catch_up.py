"""The retired catch-up list (plan 7.13; owner 2026-10-15, plan terv-oldalszerkezet T1): the
learner keeps track of what to catch up himself, so no subject page shows a 📝 Pótolandó list or
a 📝/✅ mark any more. The `catch_up: open/done` frontmatter key stays in the data; the tool
does not show it. An existing `catch-up` block is emptied (the block stays, so a later close
does not add it back); a hand-written list from before the block is replaced by the empty block."""

import re

from . import markers

NAME = "catch-up"
LEGACY = re.compile(r"^# (?:🤒|📝) (?:Pótolandó|To catch up)\s*$", re.M)
BOUNDARY = re.compile(r"^(?:# |<!-- school-notes:generated |<br\s*/?>)", re.M)
BACK_LINK = re.compile(r"^\[.*\]\(\.\./index\.md\)\s*$", re.M)


def update(text: str) -> str:
    """The subject index with its catch-up block empty and a legacy hand-written list replaced
    by the empty block; a page with neither is unchanged."""
    if NAME in markers.names(text):
        return markers.replace(text, NAME, "")
    old = LEGACY.search(text)
    if old:
        end = BOUNDARY.search(text, old.end())
        stop = end.start() if end else len(text)
        return text[:old.start()] + markers.wrap(NAME, "") + "\n" + text[stop:]
    return text
