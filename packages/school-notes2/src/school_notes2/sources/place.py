"""Put one downloaded package into `sources/<subject>/<folder>/` and describe it for fetch.json
(plan 4.2, 4.4). Hashing, naming, copying and duplicate detection are the tool's work (3.5)."""

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..state import safefs
from . import cards
from .duplicates import Known, original_key
from .naming import slug, unique_dir, unique_name
from .order import ordered
from .prepare import pdf_pages, prepare_image

ORIGINALS = (".pptx", ".ppt", ".docx", ".doc", ".pdf")


@dataclass(frozen=True)
class Settings:
    max_side_px: int = 2000
    jpeg_quality: int = 85
    pdf_dpi: int = 200
    tools_dir: Path | None = None


@dataclass(frozen=True)
class Downloaded:
    """A package after download: its Drive data and the local files (records of download)."""

    drive_folder: str
    subject: str            # wiki subject folder
    role: str               # fuzet | tanari
    description: str
    new_subject: bool
    preconverted: bool
    files: list[dict]       # {"rel", "path", "sha256"}


@dataclass
class Placed:
    package: dict                                       # fetch.json `packages[]` entry
    pages: list[dict] = field(default_factory=list)     # fetch.json `pages[]` entries
    written: list[str] = field(default_factory=list)    # repo-relative paths the tool wrote


def place_package(repo: Path, pkg: Downloaded, start_seq: int, known: Known,
                  settings: Settings = Settings(), folder: Path | None = None) -> Placed:
    """Store the package; `known` is updated so later packages of the run see its pages.

    The target folder must not exist yet (a repeated preparation starts from a clean worktree),
    or be given as `folder` (empty; the caller reserved it).
    """
    folder = folder or unique_dir(repo / "sources" / pkg.subject, slug(pkg.drive_folder), repo)
    entry = {"drive_folder": pkg.drive_folder, "subject": pkg.subject, "role": pkg.role,
             "new_subject": pkg.new_subject, "preconverted": pkg.preconverted, "files": []}
    card = cards.load(repo, pkg.subject)
    if card is not None:
        entry["card"] = card
    if pkg.description:
        entry["drive_description"] = pkg.description
    placed = Placed(entry)
    files = {f["rel"]: f for f in pkg.files}
    if pkg.preconverted:
        _place_document(repo, folder, pkg, files, start_seq, known, placed)
    else:
        _place_pages(repo, folder, pkg, files, start_seq, known, settings, placed)
    rel = safefs.rel_of(repo, folder)
    if safefs.is_dir(repo, rel) and not safefs.listdir(repo, rel):
        safefs.rmtree(repo, rel)      # every page was a duplicate
    return placed


def _place_pages(repo, folder, pkg, files, seq, known, settings, placed) -> None:
    taken: set[str] = set()
    number = 0              # the package-global page number (p0001.jpg)
    for rel in ordered(files):
        record = files[rel]
        if rel.lower().endswith(".pdf"):
            with tempfile.TemporaryDirectory() as tmp:
                pngs = pdf_pages(Path(record["path"]), Path(tmp), settings.pdf_dpi)
                for page_no, png in enumerate(pngs, start=1):
                    number += 1
                    name = unique_name(taken, f"p{number:04d}.jpg")
                    _one_page(repo, folder, pkg, record, page_no, png, name, seq, known, settings, placed)
                    seq += 1
            placed.package["files"].append(_file_entry(rel, record["sha256"], len(pngs)))
        else:
            number += 1
            name = unique_name(taken, _photo_name(rel))
            _one_page(repo, folder, pkg, record, None, Path(record["path"]), name, seq, known,
                      settings, placed)
            seq += 1
            placed.package["files"].append(_file_entry(rel, record["sha256"], 1))


def _one_page(repo, folder, pkg, record, page_no, image, name, seq, known, settings, placed):
    path = safefs.rel_of(repo, folder / name)
    with tempfile.TemporaryDirectory() as tmp:
        # Prepared on the host, then placed without following any link in the tree (7.6).
        prepared = Path(tmp) / name
        content = prepare_image(image, prepared, settings.max_side_px, settings.jpeg_quality,
                                settings.tools_dir)
        original = original_key(record["sha256"], page_no)
        earlier = known.match(original, content)
        if not earlier:             # duplicates are not stored again (4.2)
            safefs.copy_in(prepared, repo, path)
            known.add(original, content, path)
            placed.written.append(path)
    placed.pages.append({"seq": seq, "package": pkg.drive_folder, "file": record["rel"],
                         "page": page_no, "path": path, "sha256": content,
                         "original_sha256": record["sha256"], "duplicate_of": earlier})


def _place_document(repo, folder, pkg, files, seq, known, placed) -> None:
    """A doc-extract package is one list item (4.2): its extracted files are copied; the
    original pptx/docx/pdf is only hashed (original_sha256) and stays on Drive."""
    for rel in ordered(files):
        if rel.lower().endswith(ORIGINALS):
            continue        # the original pptx/docx/pdf stays on Drive
        target = safefs.rel_of(repo, folder / rel)
        safefs.copy_in(Path(files[rel]["path"]), repo, target)
        placed.written.append(target)
    doc = folder / "document.md"
    content = hashlib.sha256(safefs.read_bytes(repo, safefs.rel_of(repo, doc))).hexdigest()
    originals = [r for r in ordered(files) if r.lower().endswith(ORIGINALS)]
    source_rel = originals[0] if originals else "document.md"
    original = files[source_rel]["sha256"]
    earlier = known.match(original, content)
    if earlier:
        safefs.rmtree(repo, safefs.rel_of(repo, folder))   # the same document was taken (4.2)
        placed.written.clear()
    else:
        known.add(original, content, doc.relative_to(repo).as_posix())
    placed.pages.append({"seq": seq, "package": pkg.drive_folder, "file": "document.md",
                         "page": None, "path": doc.relative_to(repo).as_posix(), "sha256": content,
                         "original_sha256": original, "duplicate_of": earlier})
    placed.package["files"].append(_file_entry(source_rel, original, 1))


def _photo_name(rel: str) -> str:
    """`Nap 1/IMG 2.HEIC` → `nap-1-img-2.jpg`: one flat, ASCII, JPEG name per photo."""
    stem = rel.rsplit(".", 1)[0] if "." in rel.rsplit("/", 1)[-1] else rel
    return slug(stem.replace("/", "-")) + ".jpg"


def _file_entry(rel: str, sha: str, pages: int) -> dict:
    return {"file": rel, "original_sha256": sha, "pages": pages}
