"""Names on disk: ASCII folder slugs and the Drive subject → wiki subject mapping (plan 4.2)."""

import json
import re
import unicodedata
from pathlib import Path

from ..state import safefs

SUBJECTS = "tools/subjects.json"


def slug(text: str) -> str:
    """Accents removed, lowercase, every other run of characters becomes one dash."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "csomag"


def unique_dir(parent: Path, name: str, repo: Path | None = None) -> Path:
    """`parent/name`, or `name-2`, `name-3` … when that folder already exists.
    With `repo`, the test never follows a symlink inside it (7.6)."""
    candidate, n = parent / name, 1
    while (safefs.exists(repo, safefs.rel_of(repo, candidate)) if repo else candidate.exists()):
        n += 1
        candidate = parent / f"{name}-{n}"
    return candidate


def unique_name(taken: set[str], name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{stem}-{n}{dot}{ext}" if dot else f"{name}-{n}"
    taken.add(candidate)
    return candidate


def subject_key(drive_name: str, repo: Path) -> tuple[str, bool]:
    """(wiki subject folder, is_new). Known subjects match tools/subjects.json `name`."""
    subjects = {}
    if safefs.is_file(repo, SUBJECTS):
        subjects = json.loads(safefs.read_text(repo, SUBJECTS)).get("subjects", {})
    wanted = _norm(drive_name)
    for key, entry in sorted(subjects.items()):
        if _norm(entry.get("name", "")) == wanted:
            return key, not safefs.is_file(repo, f"wiki/{key}/index.md")
    key = slug(drive_name)
    return key, not safefs.is_file(repo, f"wiki/{key}/index.md")


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())
