"""Subject cards have one canonical home: tools/subjects.json (plan 4.3).

A missing card stays absent; the tool never invents a role or taught conventions.
Preparation snapshots a validated card in each package for stable resume inputs.
"""

import json
import re
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from ..state.errors import Prerequisite


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
    """Edit existing cards, or preload a new subject with only its name and card."""
    try:
        old, new = json.loads(before), json.loads(after)
        old_subjects, new_subjects = old.get("subjects", {}), new.get("subjects", {})
        for subject in sorted(new_subjects.keys() - old_subjects.keys()):
            entry = new_subjects[subject]
            if (not re.fullmatch(r"[a-z0-9-]+", subject) or set(entry) != {"name", "card"}
                    or not isinstance(entry["name"], str) or not entry["name"].strip()):
                return False
            validate("subject-card", entry["card"])
            del new_subjects[subject]
        for data in (old, new):
            for entry in data.get("subjects", {}).values():
                if "card" in entry:
                    if data is new:
                        validate("subject-card", entry["card"])
                    del entry["card"]
        return old == new
    except (ValueError, TypeError, AttributeError):
        return False


def preflight(content: bytes) -> None:
    """Validate the pinned preparation config before taking any package from Drive."""
    subject = ""
    try:
        data = json.loads(content)
        for subject, entry in sorted(data.get("subjects", {}).items()):
            if "card" in entry:
                validate("subject-card", entry["card"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise Prerequisite(f"invalid subject card configuration: {subject or 'subjects'}",
                           todo=f"javítsd a tools/subjects.json {subject} kártyáját".strip()) from exc
