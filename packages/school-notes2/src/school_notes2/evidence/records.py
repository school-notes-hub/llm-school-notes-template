"""Per-page evidence records (plan 4.8): append-only, at a place computed from the page.

`wiki/<subject>/<page>.md` → `docs/evidence/pages/<subject>/<page>.md`. Each entry is the LLM's
description plus what the tool computes: image path, SHA-256, source page, time, checker, run.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..state import safefs

PAGES_DIR = PurePosixPath("docs/evidence/pages")
IMAGE_ROOTS = ("sources/", "wiki/assets/")      # only committed images are evidence (4.8)


class RecordError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    """One check, normalised from a writer `checks` item or a reviewer `figures` item."""

    page: str
    image: str | int
    locator: str
    observed: str
    decision: str
    note: str = ""
    checks: dict | None = None


def record_path(page: str) -> PurePosixPath:
    rel = PurePosixPath(page)
    if rel.parts[:1] != ("wiki",) or rel.suffix != ".md" or ".." in rel.parts:
        raise RecordError(f"{page}: not a wiki page")
    return PAGES_DIR.joinpath(*rel.parts[1:])


def from_writer(checks: list[dict]) -> list[Entry]:
    return [Entry(c["page"], c["image"], c["locator"], c["observed"], c["decision"],
                  c.get("note", "")) for c in checks]


def _sha256(repo: Path, rel: str) -> str:
    return hashlib.sha256(safefs.read_bytes(repo, rel)).hexdigest()


def _resolve(repo: Path, image, pages_by_seq: dict[int, dict]) -> tuple[str, str, str]:
    """(repo path, sha256, source note) of a check's image: a seq or a repo-internal path."""
    if isinstance(image, int) or (isinstance(image, str) and image.isdigit()):
        page = pages_by_seq.get(int(image))
        if page is None:
            raise RecordError(f"image {image}: no such page in fetch.json")
        where = page["file"] + (f", {page['page']}. oldal" if page.get("page") else "")
        rel = page["path"]
        source = f"{page['package']} / {where}"
    else:
        rel, source = str(image), ""
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts:
        raise RecordError(f"{rel}: image outside the repository")
    if not rel.startswith(IMAGE_ROOTS):
        raise RecordError(f"{rel}: evidence images must be under {' or '.join(IMAGE_ROOTS)}")
    if not safefs.is_file(repo, rel):
        raise RecordError(f"{rel}: image does not exist")
    return rel, _sha256(repo, rel), source


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _section(repo: Path, entries: list[Entry], heading: str,
             pages_by_seq: dict[int, dict]) -> str:
    lines = [heading, ""]
    for e in entries:
        rel, digest, source = _resolve(repo, e.image, pages_by_seq)
        lines.append(f"* Kép: `{rel}` (sha256 `{digest}`)")
        if source:
            lines.append(f"  * Forrás: {_one_line(source)}")
        lines += [f"  * Hely: {_one_line(e.locator)}", f"  * Döntés: {e.decision}",
                  f"  * Megfigyelés: {_one_line(e.observed)}"]
        if e.note:
            lines.append(f"  * Megjegyzés: {_one_line(e.note)}")
        if e.checks:
            lines.append(f"  * Ellenőrzések: `{json.dumps(e.checks, ensure_ascii=False)}`")
    return "\n".join(lines) + "\n"


def append(repo: Path, entries: list[Entry], *, run_id: str, checker: str, at: str,
           fetch_pages: list[dict] | None = None, kind: str = "checks") -> list[str]:
    """Write this run's section per page; returns the written repo paths.

    A section is keyed by run, checker and `kind` (`checks`, `review`, or `image:<id>` for
    one accepted image). A repeated call for the same key REPLACES that section: until the
    run is committed its section is the tool's own draft, and a corrected result must win
    (finish reruns after a failed check). Sections of other runs are never touched."""
    pages_by_seq = {p["seq"]: p for p in fetch_pages or []}
    by_page: dict[str, list[Entry]] = {}
    for e in entries:
        by_page.setdefault(e.page, []).append(e)
    written = []
    marker = f"– {run_id} – {checker} – {kind}"
    for page, group in sorted(by_page.items()):
        rel = record_path(page)
        old = safefs.read_text(repo, rel) if safefs.exists(repo, rel) \
            else f"# Bizonyítékrekord: {page}\n"
        section = _section(repo, group, f"## {at} {marker}", pages_by_seq)
        new = _put_section(old, marker, section)
        if new != old:
            safefs.write_text(repo, rel, new)
        written.append(rel.as_posix())
    return written


def _put_section(text: str, marker: str, section: str) -> str:
    """Replace the section whose heading ends with `marker`, or append it."""
    lines = text.rstrip("\n").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ") and ln.endswith(marker)),
                 None)
    if start is None:
        return "\n".join(lines) + "\n\n" + section
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    head = "\n".join(lines[:start]).rstrip("\n")
    tail = "\n".join(lines[end:])
    return head + "\n\n" + section + ("\n" + tail + "\n" if tail else "")
