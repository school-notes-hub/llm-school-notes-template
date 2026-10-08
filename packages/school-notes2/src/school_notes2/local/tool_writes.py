"""What the tool itself wrote into the working copy since the last commit:
`.school-notes/tool-writes.json` (ignored by git, never committed).

`parts`: for a wiki page whose machine frontmatter keys or generated blocks the tool wrote
(`sn close`, a new subject's index by `sn fetch`), the SHA-256 of those parts as written.
`files`: for a whole file the tool wrote outside `sources/` (a textbook by `sn book`, a podcast
MP3 or receipt by `sn podcast`), its SHA-256 – or null for a file the tool deleted (`sn podcast
--retire`). The writer guard accepts exactly these as the tool's own work; anything else in those
places is a hand edit."""

import hashlib
from pathlib import Path

from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.machine import machine_keys

PATH = ".school-notes/tool-writes.json"


def machine_parts(text: str) -> str:
    """The parts of a page only the tool writes: machine frontmatter keys and generated blocks."""
    try:
        meta = frontmatter.split(text).meta
    except Exception:            # noqa: BLE001 - unreadable frontmatter: compare the whole text
        return text
    values = "\n".join(f"{k}={meta.get(k)!r}" for k in machine_keys(meta) if k in meta)
    blocks = "\n".join(f"{n}:{markers.read(text, n)}" for n in markers.names(text))
    return values + "\n--\n" + blocks


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def load(repo: Path) -> dict:
    value = safefs.read_json(repo, PATH, {}) if safefs.is_file(repo, PATH) else {}
    return {"parts": dict(value.get("parts", {})), "files": dict(value.get("files", {}))}


def record(repo: Path, *, parts=(), files=()) -> None:
    value = load(repo)
    for rel in parts:
        if safefs.is_file(repo, rel):
            value["parts"][rel] = sha(machine_parts(safefs.read_text(repo, rel)))
    for rel in files:
        value["files"][rel] = sha(safefs.read_bytes(repo, rel)) if safefs.is_file(repo, rel) else None
    safefs.write_json(repo, PATH, {k: dict(sorted(v.items())) for k, v in value.items()})
