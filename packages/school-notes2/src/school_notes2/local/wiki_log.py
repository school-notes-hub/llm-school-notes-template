"""The `wiki/log.md` entries of a pass (rules 1.22.5, helyi-menet *Hand-over*): the writer hands
them over in `adatok.json` `log` ([{kind: Creation | Update, text}], Hungarian, links relative to
`wiki/`). `sn close` writes them only for a hand-over it actually retires: the folder carries
`closed.json` ({sn, pass, subject, logged}) into its move to `.school-notes/done/<pass>/`; then
the entries go under the day's `## YYYY-MM-DD` heading, newest pass first, behind the pass's
marker `<!-- pass: <pass> -->`, and `logged` becomes true. A pass is written once, whatever its
wording and however often a close runs; a retired pass whose entries an interrupted close did
not write is repaired by the next close.

`sn done` reports a retired pass (one with `closed.json`) whose entries are not in the log,
under its subject, unless the controller wrote them by hand and noted `log_by_hand` there."""

import re
from pathlib import Path

from ..state import safefs
from ..wiki.pages import find_links, resolve
from .handoff import DONE, Handoff

LOG = "wiki/log.md"
CLOSED = "closed.json"
HEAD = "# Wiki Update Log\n"


def entry_lines(data: dict) -> list[str]:
    return list(dict.fromkeys(f"* **{entry['kind']}**: {entry['text'].strip()}" for entry in data.get("log", [])))


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


def mark_closed(repo: Path, base: str, name: str, subject: str, version: str) -> None:
    safefs.write_json(repo, f"{base}/{CLOSED}", {"sn": version, "pass": name, "subject": subject, "logged": False})


def marker(name: str) -> str:
    return f"<!-- pass: {name} -->"


def _insert(text: str, day: str, block: str) -> str:
    heading = re.search(rf"^## {re.escape(day)}[ \t]*$", text, re.M)
    if heading:
        return text[:heading.end()] + "\n\n" + block + text[heading.end():].lstrip("\n")
    first = re.search(r"^## ", text, re.M)
    block = f"## {day}\n\n" + block
    return (text[:first.start()] + block + text[first.start():]) if first else \
        text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"


def write_pass(repo: Path, dest: str, day: str) -> bool:
    """Write the entries of the retired pass in `dest` (once); True when the log changed."""
    closed = safefs.read_json(repo, f"{dest}/{CLOSED}", {})
    data = safefs.read_json(repo, f"{dest}/adatok.json", {}) if safefs.is_file(repo, f"{dest}/adatok.json") else {}
    lines = entry_lines(data)
    if not lines or closed.get("logged"):
        return False
    name = str(closed.get("pass") or dest.rsplit("/", 1)[1])
    text = safefs.read_text(repo, LOG) if safefs.is_file(repo, LOG) else HEAD
    changed = marker(name) not in text
    if changed:
        safefs.write_text(repo, LOG, _insert(text, day, marker(name) + "\n" + "".join(line + "\n\n" for line in lines)))
    safefs.write_json(repo, f"{dest}/{CLOSED}", {**closed, "logged": True})
    return changed


def _retired(repo: Path) -> list[tuple[str, dict]]:
    if not safefs.is_dir(repo, DONE):
        return []
    out = []
    for name in sorted(safefs.listdir(repo, DONE)):
        base = f"{DONE}/{name}"
        if safefs.is_file(repo, f"{base}/{CLOSED}"):
            closed = safefs.read_json(repo, f"{base}/{CLOSED}", {})
            out.append((base, closed if isinstance(closed, dict) else {}))
    return out


def repair(repo: Path, day: str) -> list[str]:
    """The retired passes whose entries a close did not write (an interruption): written now."""
    return [base for base, closed in _retired(repo) if not closed.get("logged") and write_pass(repo, base, day)]


def missing(repo: Path) -> list[str]:
    """Retired passes (closed by sn 0.3.6 or later) whose entries are not in the log, each named
    with its subject's folder so the subject's own retirement is held, never another's."""
    out = []
    for base, closed in _retired(repo):
        if closed.get("logged") or closed.get("log_by_hand"):
            continue
        subject = closed.get("subject") or base.rsplit("-", 1)[-1]
        out.append(f"wiki/{subject}/: {base} (az adatok.json-ban nem volt `log`, vagy még nincs beírva)")
    return out
