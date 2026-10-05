"""Generated index blocks (plan 4.10): subject indexes and the root index.

Single source of truth: the pages' frontmatter (`chapters` in the subject index,
`chapter`/`order` on pages, `lessons` on lesson-notes pages) and tools/subjects.json.
Output is a pure function of those inputs, so generation is idempotent and byte-stable.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..state import safefs
from . import catch_up, markers
from ..sources.order import natural_key
from .pages import md_files, read_page, read_text
from .pages import subjects as subject_slugs

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
TABLE_HEAD = "| Dátum | Óra | Jegyzet | Témakörök |\n|---|---|---|---|\n"
SUBJECT_BLOCKS = ("catch-up", "chapters", "lessons", "review", "notes")


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

    def by_type(self, kind: str) -> list[SubjectPage]:
        return [p for p in self.pages if p.meta.get("type") == kind]

    def page(self, file: str) -> SubjectPage | None:
        return next((p for p in self.pages if p.file == file), None)


def load_subject(repo: Path, slug: str) -> Subject:
    index = read_page(repo, f"wiki/{slug}/index.md")
    heading = next((ln[2:].strip() for ln in index.body.splitlines() if ln.startswith("# ")), slug)
    subject = Subject(slug, index.meta, heading)
    for rel in md_files(repo, f"wiki/{slug}/*.md"):
        name = rel.rsplit("/", 1)[1]
        if name != "index.md":
            subject.pages.append(SubjectPage(name, read_page(repo, rel).meta))
    return subject


def chapter_pages(subject: Subject, chapter_id: str) -> list[SubjectPage]:
    inside = [p for p in subject.pages if p.meta.get("chapter") == chapter_id]
    return sorted(inside, key=lambda p: (_order(p.meta), p.file))


def _order(meta: dict) -> int:
    """A missing or non-integer `order` sorts last; the check reports it on topic pages."""
    order = meta.get("order", 0)
    return order if isinstance(order, int) and not isinstance(order, bool) else 10**9


def list_line(page: SubjectPage) -> str:
    bolt = "⚡ " if page.meta.get("type") == "chapter-summary" else ""
    return f"* {bolt}[{page.meta.get('title', page.file)}]({page.file}) - {page.meta.get('description', '')}"


def chapters_block(subject: Subject) -> str:
    sections = []
    for chapter in subject.index_meta.get("chapters") or []:
        lines = "\n".join(list_line(p) for p in chapter_pages(subject, chapter["id"]))
        sections.append(f"# 📘 {chapter['title']}\n\n{lines}\n" if lines else f"# 📘 {chapter['title']}\n")
    return "\n<br />\n\n".join(sections)


PARTIAL_DATE = re.compile(r"^\d{4}-\d{2}-(?:\d\?|\?\d|\?\?)")


def lesson_date(lesson: dict) -> str:
    """The table's Dátum cell: the notebook date, or `?` with the range it must fall in."""
    date, note = lesson.get("date"), lesson.get("date_note")
    if date:
        return f"{date}; {note}" if note else str(date)
    if note and PARTIAL_DATE.match(note):
        return note          # a partly legible date ("2026-09-1? (levágva …)") stands as written
    return f"? ({note})" if note else "?"


def notebook_position(meta: dict) -> tuple:
    """Where a lesson page's material starts in the notebook: its first source page, in the
    fixed page order (4.3). Pages of one notebook thus keep the notebook's order."""
    first = ""
    source_file = meta.get("source_file")
    if isinstance(source_file, list):
        source_file = source_file[0] if source_file else ""
    hashes = meta.get("content_sha256")
    if isinstance(source_file, str) and source_file:
        first = source_file
        if source_file.endswith("/") and isinstance(hashes, dict) and hashes:
            first += sorted(hashes, key=natural_key)[0]
    if not first:
        for key in ("sources", "source_files"):
            for item in meta.get(key) or []:
                if isinstance(item, dict) and "sources/" in str(item.get("resource", "")):
                    first = str(item["resource"]).split("sources/", 1)[1]
                    break
            if first:
                break
    return natural_key(first.removeprefix("sources/"))


def lesson_sort_key(page: SubjectPage, index: int, lesson: dict) -> tuple:
    # Undated lessons sort by the latest date their range allows (the wiki's own rule); a tie
    # is settled by where the page's material starts in the notebook, then by the file name –
    # always the same order, taken from the content.
    dates = ISO.findall(str(lesson.get("date") or "")) or ISO.findall(lesson.get("date_note") or "")
    return (max(dates) if dates else "", page.file[:10], notebook_position(page.meta),
            page.file, index)


def lessons(subject: Subject) -> list[tuple[SubjectPage, dict]]:
    """Every lesson of the subject, newest first."""
    rows = []
    for page in subject.by_type("lesson-notes"):
        for i, lesson in enumerate(page.meta.get("lessons") or []):
            rows.append((lesson_sort_key(page, i, lesson), page, lesson))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [(page, lesson) for _, page, lesson in rows]


def topic_link(subject: Subject, topic: str) -> str:
    """`[title](file.md#anchor)`; the title always comes from the page itself."""
    target = subject.page(topic.split("#", 1)[0])
    title = target.meta.get("title", topic) if target else topic
    return f"[{title}]({topic})"


def lessons_block(subject: Subject) -> str:
    rows, states = [], set()
    for page, lesson in lessons(subject):
        topics = ", ".join(topic_link(subject, t) for t in lesson.get("topics") or [])
        anchor = f"#{lesson['anchor']}" if lesson.get("anchor") else ""
        states.add(page.meta.get("catch_up"))
        rows.append(f"| {catch_up.mark(page.meta)}{lesson_date(lesson)} | {lesson.get('title', '')} | "
                    f"[jegyzet]({page.file}{anchor}) | {topics} |")
    key = catch_up.legend(states)
    return (f"{key}\n\n" if key else "") + TABLE_HEAD + "".join(r + "\n" for r in rows)


def catch_up_description(subject: Subject, page: SubjectPage) -> str:
    """`Dátum: …. Témakörök: ….` from the page's `lessons`, as in the lessons table."""
    lessons_ = [lesson for lesson in page.meta.get("lessons") or [] if isinstance(lesson, dict)]
    dates = [lesson_date(lesson) for lesson in lessons_]
    topics = list(dict.fromkeys(t for lesson in lessons_ for t in lesson.get("topics") or []))
    parts = ([f"Dátum: {', '.join(dates)}."] if dates else []) + \
        ([f"Témakörök: {', '.join(topic_link(subject, t) for t in topics)}."] if topics else [])
    return " ".join(parts)


def by_date_desc(pages: list[SubjectPage]) -> list[SubjectPage]:
    ordered = sorted(pages, key=lambda p: p.file)
    return sorted(ordered, key=lambda p: p.file[:10], reverse=True)


def review_block(subject: Subject) -> str:
    pages = by_date_desc(subject.by_type("review"))
    if not pages:
        return ""
    lines = "\n".join(list_line(p) for p in pages)
    return f"# 🔁 Ismétlés\n\n{lines}\n\n<br />\n\n"


def notes_block(subject: Subject) -> str:
    pages = by_date_desc(subject.by_type("lesson-notes"))
    if not pages:
        return ""
    return "# 📝 Jegyzetek\n\n" + "\n".join(list_line(p) for p in pages) + "\n"


REQUIRED_SUBJECT_BLOCKS = ("chapters", "lessons", "review", "notes")


def with_blocks(text: str, names: tuple[str, ...]) -> str:
    """A required index block the author removed comes back, empty, at the fixed place:
    the end of the page, in canonical order; the refresh then fills it."""
    missing = [n for n in names if n not in markers.names(text)]
    if not missing:
        return text
    return text.rstrip("\n") + "\n\n" + "".join(markers.wrap(n, "") for n in missing)


def subject_index(repo: Path, slug: str) -> str:
    """The subject index text with every generated block refreshed (and present)."""
    text = with_blocks(markers.clean_nested_notices(read_text(repo, f"wiki/{slug}/index.md")),
                       REQUIRED_SUBJECT_BLOCKS)
    subject = load_subject(repo, slug)
    bodies = {"chapters": chapters_block(subject), "lessons": lessons_block(subject),
              "review": review_block(subject), "notes": notes_block(subject)}
    for name in markers.names(text):
        if name in bodies:
            text = markers.replace(text, name, bodies[name])
    return catch_up.update(text, by_date_desc(subject.by_type("lesson-notes")),
                           lambda page: catch_up_description(subject, page))


def subject_order(repo: Path) -> list[str]:
    """subjects.json order (new subjects are appended), then any other subject folder."""
    known = list(load_subjects_json(repo).get("subjects", {}))
    folders = set(subject_slugs(repo))
    return [s for s in known if s in folders] + sorted(folders - set(known))


def load_subjects_json(repo: Path) -> dict:
    try:
        return json.loads(read_text(repo, "tools/subjects.json"))
    except FileNotFoundError:
        return {"subjects": {}}


def subject_sentence(name: str) -> str:
    article = "Az" if name[:1].lower() in "aáeéiíoóöőuúüű" else "A"
    return f"{article} {name.lower()} tantárgy témakörei és jegyzetei."


def subject_label(repo: Path, slug: str) -> str:
    entry = load_subjects_json(repo).get("subjects", {}).get(slug, {})
    name = entry.get("name", slug)
    return f"{entry['emoji']} {name}" if entry.get("emoji") else name


def root_block(repo: Path) -> str:
    lines = []
    subjects = load_subjects_json(repo).get("subjects", {})
    for slug in subject_order(repo):
        entry = subjects.get(slug, {})
        name = entry.get("name", slug)
        emoji = f"{entry['emoji']} " if entry.get("emoji") else ""
        meta = read_page(repo, f"wiki/{slug}/index.md").meta
        lines.append(f"* {emoji}[{name}]({slug}/index.md) - "
                     f"{meta.get('description') or subject_sentence(name)}")
    return "".join(ln + "\n" for ln in lines)


def root_index(repo: Path) -> str:
    text = markers.clean_nested_notices(read_text(repo, "wiki/index.md"))
    if subject_order(repo):  # An uninitialized wiki has no subjects and no block yet.
        text = with_blocks(text, ("subjects",))
    if "subjects" in markers.names(text):
        text = markers.replace(text, "subjects", root_block(repo))
    return text


def write_indexes(repo: Path) -> list[str]:
    """Refresh every index; returns the repo-relative paths that changed."""
    changed = []
    targets = [(f"wiki/{s}/index.md", lambda s=s: subject_index(repo, s)) for s in subject_order(repo)]
    targets.append(("wiki/index.md", lambda: root_index(repo)))
    for rel, build in targets:
        old = read_text(repo, rel)
        new = build()
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return changed
