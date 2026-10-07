"""Per-page evidence records (plan 4.8): append-only, at a place computed from the page.

`wiki/<subject>/<page>.md` → `docs/evidence/pages/<subject>/<page>.md`. Each entry is the
writer's description (the hand-over's `adatok.json` `checks`) plus what `sn close` computes:
image path, SHA-256, source page (from the source manifest), time, checker, run.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..state import safefs

PAGES_DIR = PurePosixPath("docs/evidence/pages")
IMAGE_ROOTS = ("sources/", "wiki/assets/")      # only committed images are evidence (4.8)


class RecordError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    """One check of the writer (`adatok.json` `checks`)."""

    page: str
    image: str
    locator: str
    observed: str
    decision: str
    note: str = ""


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


def _resolve(repo: Path, image: str, pages: dict[str, dict]) -> tuple[str, str, str]:
    """(repo path, sha256, source note) of a check's image (a repo path); the source note comes
    from the source manifest when the image is a stored source page."""
    rel, source = str(image), ""
    if rel in pages:
        page = pages[rel]
        source = f"{page['package']} / " + page["file"] + (f", {page['page']}. oldal" if page.get("page") else "")
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


def _section(repo: Path, entries: list[Entry], heading: str, pages: dict[str, dict]) -> str:
    lines = [heading, ""]
    for e in entries:
        rel, digest, source = _resolve(repo, e.image, pages)
        lines.append(f"* Kép: `{rel}` (sha256 `{digest}`)")
        if source:
            lines.append(f"  * Forrás: {_one_line(source)}")
        lines += [f"  * Hely: {_one_line(e.locator)}", f"  * Döntés: {e.decision}",
                  f"  * Megfigyelés: {_one_line(e.observed)}"]
        if e.note:
            lines.append(f"  * Megjegyzés: {_one_line(e.note)}")
    return "\n".join(lines) + "\n"


def check_entries(repo: Path, entries: list[Entry], pages: dict[str, dict]) -> list[str]:
    """Problems that would stop `append` (no write)."""
    out = []
    for e in entries:
        try:
            record_path(e.page)
            _resolve(repo, e.image, pages)
        except RecordError as exc:
            out.append(str(exc))
    return out


def append(repo: Path, entries: list[Entry], *, run_id: str, checker: str, at: str,
           pages: dict[str, dict] | None = None, kind: str = "checks") -> list[str]:
    """Write this pass's section per page; returns the written repo paths (changed or not).

    A section is keyed by run, checker and `kind`. A repeated call for the same key REPLACES
    that section (a repeated `sn close` of the same pass); sections of other passes are never
    touched."""
    pages = pages or {}
    by_page: dict[str, list[Entry]] = {}
    for e in entries:
        by_page.setdefault(e.page, []).append(e)
    written = []
    marker = f"– {run_id} – {checker} – {kind}"
    for page, group in sorted(by_page.items()):
        rel = record_path(page)
        old = safefs.read_text(repo, rel) if safefs.exists(repo, rel) \
            else f"# Bizonyítékrekord: {page}\n"
        section = _section(repo, group, f"## {at} {marker}", pages)
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
    if "\n".join(lines[start + 1:end]).strip("\n") == section.split("\n", 1)[1].strip("\n"):
        return text                 # the same checks again: the section keeps its first time
    head = "\n".join(lines[:start]).rstrip("\n")
    tail = "\n".join(lines[end:])
    return head + "\n\n" + section + ("\n" + tail + "\n" if tail else "")
