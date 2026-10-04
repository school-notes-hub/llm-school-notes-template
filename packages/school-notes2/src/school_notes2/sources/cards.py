"""Subject cards have one canonical home: the template's shared `subject-cards.json` (plan 4.3).

One card per subject, the same for every learner: a shared file, byte-identical in each
learner repo, edited only in the template in an interactive session. A learner's
`tools/subjects.json` holds no card; a `card` key there has no effect. The subject's place
(school year, school type, training) comes from the learner's configuration and PROFILE.md.
A missing card stays absent: the run goes on without it and `status` lists the subject.
Preparation snapshots a validated card in each package for stable resume inputs.
"""

import json
from pathlib import Path

from ..schemas import SchemaError, validate
from ..state import safefs
from ..state.errors import Prerequisite

PATH = "subject-cards.json"


def _parse(content: bytes | str) -> dict:
    data = json.loads(content)
    validate("subject-cards", data)
    return data["cards"]


def _all(repo: Path) -> dict:
    try:
        return _parse(safefs.read_text(repo, PATH))
    except FileNotFoundError:
        return {}


def load(repo: Path, subject: str) -> dict | None:
    card = _all(repo).get(subject)
    if card is None:
        return None
    return {key: card[key] for key in ("role", "style")}


def missing(repo: Path, subjects) -> list[str]:
    """The learner's subjects without a shared card, in name order (for `status`)."""
    cards = _all(repo)
    return sorted(s for s in set(subjects) if s not in cards)


def preflight(content: bytes) -> None:
    """Validate the pinned shared card file before taking any package from Drive."""
    try:
        _parse(content)
    except (ValueError, TypeError, SchemaError) as exc:
        raise Prerequisite(f"invalid shared subject cards: {str(exc)[:200]}",
                           todo=f"javítsd a template {PATH} fájlját, majd szinkronizáld "
                                "a közös fájlokat a tanulói repóba") from exc
