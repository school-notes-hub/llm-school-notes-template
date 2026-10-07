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
from . import catch_up, markers, teaching_order
from .pages import md_files, read_page, read_text
from .pages import subjects as subject_slugs

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
TABLE_HEAD = "| Dátum | Óra | Jegyzet | Témakörök |\n|---|---|---|---|\n"


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
    """The chapters in the `chapters` list order (the writer keeps it in the order the class
    started them; `sn check` warns otherwise), each with when it was taught (🗓️)."""
    spans = teaching_order.spans(subject_chapters(subject, ordered_lessons(subject)))
    sections = []
    for chapter in subject.index_meta.get("chapters") or []:
        lines = "\n".join(list_line(p) for p in chapter_pages(subject, chapter["id"]))
        when = f"🗓️ {spans[str(chapter['id'])]}\n\n" if str(chapter["id"]) in spans else ""
        sections.append(f"# 📘 {chapter['title']}\n\n{when}{lines}\n" if lines else f"# 📘 {chapter['title']}\n")
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


notebook_position = teaching_order.notebook_position


def ordered_lessons(subject: Subject) -> list[teaching_order.Lesson]:
    """Every lesson of the subject, oldest first (`teaching_order`: an undated lesson by the lower
    bound of its range), with its `uncertain` mark."""
    return teaching_order.ordered([(p.file, p.meta) for p in subject.by_type("lesson-notes")])


def lessons(subject: Subject) -> list[tuple[SubjectPage, dict]]:
    """Every lesson of the subject, newest first."""
    return [(subject.page(lesson.file), lesson.data) for lesson in reversed(ordered_lessons(subject))]


def subject_chapters(subject: Subject, found: list[teaching_order.Lesson]) -> list[teaching_order.Chapter]:
    pages = {p.file: str(p.meta.get("chapter")) for p in subject.pages if p.meta.get("chapter")}
    return teaching_order.chapters(subject.index_meta, pages, found)


def topic_link(subject: Subject, topic: str) -> str:
    """`[title](file.md#anchor)`; the title always comes from the page itself."""
    target = subject.page(topic.split("#", 1)[0])
    title = target.meta.get("title", topic) if target else topic
    return f"[{title}]({topic})"


UNCERTAIN = " ↕"
UNCERTAIN_LEGEND = ("A ↕ jel: ennek a dátum nélküli órának a helye a sorban nem biztos, mert az "
                    "időszaka átfed más órákéval.")


def lessons_block(subject: Subject) -> str:
    rows, states, marked = [], set(), False
    for item in reversed(ordered_lessons(subject)):
        page, lesson = subject.page(item.file), item.data
        topics = ", ".join(topic_link(subject, t) for t in lesson.get("topics") or [])
        anchor = f"#{lesson['anchor']}" if lesson.get("anchor") else ""
        states.add(page.meta.get("catch_up"))
        marked |= item.uncertain
        rows.append(f"| {catch_up.mark(page.meta)}{lesson_date(lesson)}{UNCERTAIN if item.uncertain else ''} | "
                    f"{lesson.get('title', '')} | [jegyzet]({page.file}{anchor}) | {topics} |")
    key = " ".join(filter(None, [catch_up.legend(states), UNCERTAIN_LEGEND if marked else ""]))
    return (f"{key}\n\n" if key else "") + TABLE_HEAD + "".join(r + "\n" for r in rows)


NOW_HEADING = "# 📍 Itt tartunk"
RECENT = 5          # lessons listed before the latest one


def _dated(lesson: dict) -> str:
    """`2026-10-06`, or `dátum nélkül, <range>` (a partly legible date as written)."""
    cell = lesson_date(lesson)
    return f"dátum nélkül, {lesson['date_note']}" if cell.startswith("?") and lesson.get("date_note") else (
        "dátum nélkül" if cell == "?" else cell)


def now_block(subject: Subject) -> str:
    """📍 Itt tartunk: the chapter the class started last, the latest lesson with its topics, the
    chapters before, and the lessons before it, newest first (rules 1.22.4)."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    chapters_ = subject_chapters(subject, found)
    started, spans = teaching_order.by_start(chapters_), teaching_order.spans(chapters_)
    latest = found[-1]
    page = subject.page(latest.file)
    anchor = f"#{latest.data['anchor']}" if latest.data.get("anchor") else ""
    topics = ", ".join(topic_link(subject, t) for t in latest.data.get("topics") or [])
    mark = UNCERTAIN if latest.uncertain else ""
    lines = [NOW_HEADING, ""]
    if started:
        now = started[-1]
        lines.append(f"* **Most:** {teaching_order.plain_title(now.title)} "
                     f"({spans[now.id]})")
    lines.append(f"* **Legutóbb:** [{latest.data.get('title', '')}]({page.file}{anchor}) – "
                 f"{_dated(latest.data)}{mark}" + (f" · {topics}" if topics else ""))
    if len(started) > 1:
        lines.append("* **Előtte:** " + " → ".join(
            f"{teaching_order.plain_title(c.title)} ({spans[c.id]})"
            for c in started[:-1]))
    before = list(reversed(found[:-1]))[:RECENT]
    if before:
        lines += ["", "Eddig ebben a sorrendben vettük, a legújabb elöl:", ""]
        for item in before:
            p = subject.page(item.file)
            a = f"#{item.data['anchor']}" if item.data.get("anchor") else ""
            lines.append(f"* {lesson_date(item.data)}{UNCERTAIN if item.uncertain else ''} – "
                         f"[{item.data.get('title', '')}]({p.file}{a})")
    if latest.uncertain or any(item.uncertain for item in before):
        lines += ["", UNCERTAIN_LEGEND]
    return "\n".join(lines) + "\n"


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


def with_now(text: str) -> str:
    """The 📍 block's fixed place: right after the back link to the home page (else right
    before the first generated block, else at the end), so it stands above the chapter lists."""
    if "now" in markers.names(text):
        return text
    back = catch_up.BACK_LINK.search(text)
    block = markers.BLOCK.search(text)
    pos = back.end() if back else (block.start() if block else len(text))
    head, tail = text[:pos].rstrip("\n"), text[pos:].lstrip("\n")
    return head + "\n\n" + markers.wrap("now", "") + "\n" + tail


def with_blocks(text: str, names: tuple[str, ...]) -> str:
    """A required index block the author removed comes back, empty, at the fixed place:
    the end of the page, in canonical order; the refresh then fills it."""
    missing = [n for n in names if n not in markers.names(text)]
    if not missing:
        return text
    return text.rstrip("\n") + "\n\n" + "".join(markers.wrap(n, "") for n in missing)


def subject_index(repo: Path, slug: str) -> str:
    """The subject index text with every generated block refreshed (and present)."""
    text = with_now(with_blocks(markers.clean_nested_notices(read_text(repo, f"wiki/{slug}/index.md")),
                                REQUIRED_SUBJECT_BLOCKS))
    subject = load_subject(repo, slug)
    bodies = {"now": now_block(subject), "chapters": chapters_block(subject), "lessons": lessons_block(subject),
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
