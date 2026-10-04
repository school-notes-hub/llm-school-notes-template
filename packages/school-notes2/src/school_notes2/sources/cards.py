"""Subject cards have one canonical home: tools/subjects.json (plan 4.3).

A missing card stays absent; the tool never invents a role or taught conventions.
Preparation snapshots a validated card in each package for stable resume inputs.
"""

import json
from pathlib import Path

from ..schemas import validate
from ..state import safefs


def load(repo: Path, subject: str) -> dict | None:
    try:
        data = json.loads(safefs.read_text(repo, "tools/subjects.json"))
    except FileNotFoundError:
        return None
    entry = data.get("subjects", {}).get(subject, {})
    if "card" not in entry:
        return None
    card = entry["card"]
    validate("subject-card", card)
    # Convention order is authored content, never alphabetical order.
    return {key: card[key] for key in ("role", "conventions", "style")}


def only_cards_changed(before: bytes, after: bytes) -> bool:
    """An owner's session may edit valid cards of existing subjects, no other metadata."""
    try:
        old, new = json.loads(before), json.loads(after)
        for data in (old, new):
            for entry in data.get("subjects", {}).values():
                if "card" in entry:
                    if data is new:
                        validate("subject-card", entry["card"])
                    del entry["card"]
        return old == new
    except (ValueError, TypeError, AttributeError):
        return False
