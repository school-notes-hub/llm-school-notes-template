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

from ..schemas import validate
from ..state import safefs

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
