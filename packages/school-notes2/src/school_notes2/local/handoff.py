"""The hand-over folders `.school-notes/out/<subject>/` that `sn close` reads (role texts
`jegyzetiro.md`, `lektor.md`; rules: `instructions/helyi-menet.md`).

The writer's `figures.json` [{id, page, route, replaces}], `ujranezes.json` [{id, page, anchor,
asset}] and `adatok.json` (schema `handoff-data`: `writer`, the lesson pages' source pages
`notes`, the image checks `checks`, the teacher-image `requests`); the reviewer's
`verdicts.json` and `recheck.json` keyed by figure id; the controller's `keys.json`
(`sn close --snapshot`)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from .common import Refused

OUT = ".school-notes/out"
DONE = ".school-notes/done"           # hand-overs `sn close` has finished (`close.retire`)


@dataclass
class Handoff:
    subject: str
    figures: list[dict]
    verdicts: dict
    rechecks: list[dict]
    recheck_verdicts: dict
    keys: dict
    data: dict = field(default_factory=dict)       # adatok.json ({} when there is none)


def _json(repo: Path, rel: str, default):
    return safefs.read_json(repo, rel, default) if safefs.is_file(repo, rel) else default


def retired(repo: Path, subject: str) -> list[str]:
    """The finished hand-overs of a subject under `DONE` (`helyi-<digest>-<subject>[-n]`), by name."""
    if not safefs.is_dir(repo, DONE):
        return []
    name = re.compile(rf"helyi-[0-9a-f]{{12}}-{re.escape(subject)}(?:-\d+)?")
    return [f"{DONE}/{d}" for d in safefs.listdir(repo, DONE) if name.fullmatch(d)]


def retired_notes(repo: Path) -> set[str]:
    """Every lesson log a finished hand-over's `adatok.json` names: written by that close, so a
    re-run before the commit does not miss its hand-over."""
    out = set()
    for d in safefs.listdir(repo, DONE) if safefs.is_dir(repo, DONE) else []:
        rel = f"{DONE}/{d}/adatok.json"
        try:
            data = _json(repo, rel, {}) if safefs.is_dir(repo, f"{DONE}/{d}") else {}
            out |= {n["file"] for n in data.get("notes", []) if isinstance(n, dict) and isinstance(n.get("file"), str)}
        except (ValueError, OSError, AttributeError):
            continue
    return out


def handoffs(repo: Path, subjects: list[str] | None, *, allow_retired: bool = False) -> list[Handoff]:
    """The hand-overs in `OUT`, by subject; a named subject without one is refused – with
    `allow_retired` not when it has a finished hand-over (`sn close` re-run after a move)."""
    found = sorted(safefs.listdir(repo, OUT)) if safefs.is_dir(repo, OUT) else []
    if subjects:
        missing = sorted(s for s in set(subjects) - set(found) if not (allow_retired and retired(repo, s)))
        if missing:
            raise Refused(f"nincs átadás ezekhez: {', '.join(missing)} ({OUT}/<tantárgy>/)")
        found = [s for s in found if s in subjects]
    out = []
    for subject in found:
        base = f"{OUT}/{subject}"
        if not safefs.is_dir(repo, base):
            continue
        data = _json(repo, f"{base}/adatok.json", {})
        if data:
            try:
                validate("handoff-data", data)
            except ValueError as exc:
                raise Refused(f"{base}/adatok.json: {exc}") from None
        out.append(Handoff(subject, _json(repo, f"{base}/figures.json", []), _json(repo, f"{base}/verdicts.json", {}),
                           _json(repo, f"{base}/ujranezes.json", []), _json(repo, f"{base}/recheck.json", {}),
                           _json(repo, f"{base}/keys.json", {}), data))
    return out


def in_scope(page: str, subjects: list[str] | None) -> bool:
    parts = page.split("/")
    return not subjects or (len(parts) > 2 and parts[0] == "wiki" and parts[1] in subjects)

def accepted(verdicts: dict, fid: str) -> dict | None:
    value = verdicts.get(fid)
    return value if isinstance(value, dict) and value.get("verdict") == "accept" else None
