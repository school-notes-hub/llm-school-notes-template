"""The hand-over folders `.school-notes/out/<subject>/` that `sn close` reads (role texts
`jegyzetiro.md`, `lektor.md`; rules: `instructions/helyi-menet.md`).

The writer's `figures.json` [{id, page, route, replaces}], `ujranezes.json` [{id, page, anchor,
asset}] and `adatok.json` (schema `handoff-data`: `writer`, the lesson pages' source pages
`notes`, the image checks `checks`, the teacher-image `requests`); the reviewer's
`verdicts.json` and `recheck.json` keyed by figure id; the controller's `keys.json`
(`sn close --snapshot`)."""

from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from .common import Refused

OUT = ".school-notes/out"


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


def handoffs(repo: Path, subjects: list[str] | None) -> list[Handoff]:
    found = sorted(safefs.listdir(repo, OUT)) if safefs.is_dir(repo, OUT) else []
    if subjects:
        missing = sorted(set(subjects) - set(found))
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
