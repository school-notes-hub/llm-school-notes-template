"""The `wiki/log.md` entries of a pass (rules 1.22.4, helyi-menet *Hand-over*): the writer hands
them over in `adatok.json` `log` ([{kind: Creation | Update, text}], Hungarian, links relative to
`wiki/`); `sn close` writes them under the day's `## YYYY-MM-DD` heading, newest first, the
subjects in name order and each hand-over's entries in its own order. A line already in that
day's section is not written again, so a replay changes nothing.

A finished hand-over gets `closed.json` in its `done/` folder; `sn done` reports one whose
`adatok.json` had no `log` (unless the controller wrote the entry by hand and noted it there as
`log_by_hand`)."""

import re
from pathlib import Path

from ..state import safefs
from ..wiki.pages import find_links, resolve
from .handoff import DONE, Handoff

LOG = "wiki/log.md"
CLOSED = "closed.json"
HEAD = "# Wiki Update Log\n"


def lines(found: list[Handoff]) -> list[str]:
    out = [f"* **{entry['kind']}**: {entry['text'].strip()}"
           for h in sorted(found, key=lambda h: h.subject) for entry in h.data.get("log", [])]
    return list(dict.fromkeys(out))


def problems(repo: Path, found: list[Handoff]) -> list[str]:
    """A log link must reach a page or image inside `wiki/` (relative to `wiki/`)."""
    out = []
    for h in found:
        for entry in h.data.get("log", []):
            for link in find_links(entry["text"]):
                target = link["target"].strip("<>").split("#", 1)[0]
                if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue
                rel = resolve(LOG, target)
                if not rel or not rel.startswith("wiki/") or not safefs.is_file(repo, rel):
                    out.append(f"{h.subject}: log: {target} is not a wiki page (links are relative to wiki/)")
    return out


def write(repo: Path, found: list[Handoff], day: str) -> bool:
    """Add the pass's entries under `## <day>` (the section made at the top when missing)."""
    new = lines(found)
    if not new:
        return False
    text = safefs.read_text(repo, LOG) if safefs.is_file(repo, LOG) else HEAD
    heading = re.search(rf"^## {re.escape(day)}[ \t]*$", text, re.M)
    if heading:
        nxt = re.search(r"^## ", text[heading.end():], re.M)
        section = text[heading.end():heading.end() + nxt.start() if nxt else len(text)]
        new = [line for line in new if line not in section.splitlines()]
        if not new:
            return False
        block = "".join(line + "\n\n" for line in new)
        text = text[:heading.end()] + "\n\n" + block + text[heading.end():].lstrip("\n")
    else:
        first = re.search(r"^## ", text, re.M)
        block = f"## {day}\n\n" + "".join(line + "\n\n" for line in new)
        text = (text[:first.start()] + block + text[first.start():]) if first else \
            text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"
    safefs.write_text(repo, LOG, text)
    return True


def mark_closed(repo: Path, dest: str, version: str) -> None:
    safefs.write_json(repo, f"{dest}/{CLOSED}", {"sn": version})


def missing(repo: Path) -> list[str]:
    """Finished hand-overs (closed by sn 0.3.6 or later) whose `adatok.json` had no `log`."""
    if not safefs.is_dir(repo, DONE):
        return []
    out = []
    for name in sorted(safefs.listdir(repo, DONE)):
        base = f"{DONE}/{name}"
        if not safefs.is_file(repo, f"{base}/{CLOSED}"):
            continue
        closed = safefs.read_json(repo, f"{base}/{CLOSED}", {})
        data = safefs.read_json(repo, f"{base}/adatok.json", {}) if safefs.is_file(repo, f"{base}/adatok.json") else {}
        if not data.get("log") and not (isinstance(closed, dict) and closed.get("log_by_hand")):
            out.append(base)
    return out
