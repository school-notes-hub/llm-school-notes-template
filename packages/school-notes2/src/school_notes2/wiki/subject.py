"""Subject metadata, page loading, notebook evidence and chapter membership."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..state import safefs
from . import teaching_order
from .pages import md_files, read_page, read_text


@dataclass
class SubjectPage:
    file: str            # file name inside the subject folder
    meta: dict


@dataclass
class Subject:
    slug: str
    index_meta: dict
    index_title: str     # the index's first `# ` heading
    pages: list[SubjectPage] = field(default_factory=list)
    notebooks: set[str] = field(default_factory=set)   # source folders that hold one notebook
    repo: Path | None = None

    def by_type(self, kind: str) -> list[SubjectPage]:
        return [p for p in self.pages if p.meta.get("type") == kind]

    def page(self, file: str) -> SubjectPage | None:
        return next((p for p in self.pages if p.file == file), None)


def load_subject(repo: Path, slug: str) -> Subject:
    index = read_page(repo, f"wiki/{slug}/index.md")
    heading = next((ln[2:].strip() for ln in index.body.splitlines() if ln.startswith("# ")), slug)
    subject = Subject(slug, index.meta, heading, repo=repo)
    for rel in md_files(repo, f"wiki/{slug}/*.md"):
        name = rel.rsplit("/", 1)[1]
        if name != "index.md":
            subject.pages.append(SubjectPage(name, read_page(repo, rel).meta))
    subject.notebooks = notebook_folders(repo, {teaching_order.first_folder(p.meta)
                                                for p in subject.by_type("lesson-notes")} - {""})
    return subject


NOTEBOOK_PAGE = re.compile(r"^(?:p\d{4}|page-\d+)\.(?:jpe?g|png|webp)$", re.I)


def notebook_folders(repo: Path, folders: set[str]) -> set[str]:
    """The source folders whose page order is the order of one notebook (teaching-order
    evidence): every stored page split from one PDF (its manifest), or, for a folder without a
    manifest, exactly one PDF with or without its page images, or only PDF-page images
    (`p0001.jpg`, `page-07.jpeg`). Two PDFs, or a catch-up folder of separate photos, may mix
    notebooks: their order is no evidence. The same folder gets the same answer with or without
    a manifest (older learner folders have none)."""
    out = set()
    for folder in sorted(folders):
        base = f"sources/{folder}"
        if safefs.is_file(repo, f"{base}/sn-fetch.json"):
            try:
                pages = [p for p in json.loads(read_text(repo, f"{base}/sn-fetch.json")).get("pages", [])
                         if not p.get("duplicate_of")]
            except ValueError:
                continue
            if pages and all(p.get("page") for p in pages) and len({p.get("file") for p in pages}) == 1:
                out.add(folder)
        elif safefs.is_dir(repo, base):
            files = [n for n in safefs.listdir(repo, base) if not n.startswith(".")]
            pdfs = [n for n in files if n.lower().endswith(".pdf")]
            pages = [n for n in files if NOTEBOOK_PAGE.match(n)]
            # one PDF (with or without its page images), or only PDF-page images; two PDFs may
            # be two notebooks, so their order is no evidence
            if len(pdfs) <= 1 and (pdfs or pages) and len(pdfs) + len(pages) == len(files):
                out.add(folder)
    return out


def chapter_pages(subject: Subject, chapter_id: str) -> list[SubjectPage]:
    inside = [p for p in subject.pages if p.meta.get("chapter") == chapter_id]
    return sorted(inside, key=lambda p: (_order(p.meta), p.file))


def chapter_sections(subject: Subject) -> list[tuple[dict, list[SubjectPage]]]:
    """The teaching order of a subject's pages: the index's `chapters` list (the order the class
    started them) with each chapter's pages (`chapter_pages`); a malformed entry is left out, a
    page stands only under the first chapter that has it. The Podcast page, the media order
    numbers and the video order all walk this."""
    listed = subject.index_meta.get("chapters")
    out, seen = [], set()
    for chapter in listed if isinstance(listed, list) else []:
        if not isinstance(chapter, dict) or "id" not in chapter:
            continue
        pages = [p for p in chapter_pages(subject, chapter["id"]) if p.file not in seen]
        seen |= {p.file for p in pages}
        out.append((chapter, pages))
    return out


def _order(meta: dict) -> int:
    """A missing or non-integer `order` sorts last; the check reports it on topic pages."""
    order = meta.get("order", 0)
    return order if isinstance(order, int) and not isinstance(order, bool) else 10**9


PARTIAL_DATE = re.compile(r"^\d{4}-\d{2}-(?:\d\?|\?\d|\?\?)")


def lesson_date(lesson: dict) -> str:
    """The table's Dátum cell: the notebook date, or `?` with the range it must fall in."""
    date, note = lesson.get("date"), lesson.get("date_note")
    if date:
        return f"{date}; {note}" if note else str(date)
    if note and PARTIAL_DATE.match(note):
        return note          # a partly legible date ("2026-09-1? (levágva …)") stands as written
    return f"? ({note})" if note else "?"


def covering_lessons(lessons: list[teaching_order.Lesson], page: str) -> list[teaching_order.Lesson]:
    """Lessons of one log covering this page, in its source `lessons` list order."""
    return sorted((item for item in lessons if page in item.topics), key=lambda item: item.index)
