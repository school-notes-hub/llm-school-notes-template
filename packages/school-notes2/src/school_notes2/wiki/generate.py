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
from . import catch_up, hu_dates, markers, teaching_order
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
    notebooks: set[str] = field(default_factory=set)   # source folders that hold one notebook

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
    found = ordered_lessons(subject)
    spans = teaching_order.spans(subject_chapters(subject, found), teaching_order.year_of(found))
    sections = []
    listed = subject.index_meta.get("chapters") if isinstance(subject.index_meta.get("chapters"), list) else []
    for chapter in listed:
        lines = "\n".join(list_line(p) for p in chapter_pages(subject, chapter["id"]))
        when = f"{spans[str(chapter['id'])]}\n\n" if str(chapter["id"]) in spans else ""
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
    return teaching_order.ordered([(p.file, p.meta) for p in subject.by_type("lesson-notes")], subject.notebooks)


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


def lesson_link(page: SubjectPage, lesson: dict) -> str:
    """The lesson log of a lesson, at its section when it names an `anchor`."""
    return f"{page.file}#{lesson['anchor']}" if lesson.get("anchor") else page.file


PARTLY = re.compile(r"\d{4}-\d{2}-(?:\d\?|\?\d|\?\?)|\bvagy\b|részben olvasható")


def when(lesson: teaching_order.Lesson, year: int) -> str:
    """The lesson's day as a quiet date item (`hu_dates.meta`): `okt. 6.` (a note on a dated
    lesson as its tooltip); an undated lesson `~` + its approximate day (`hu_dates.approximate`),
    the range only in the tooltip – `Bizonytalan dátum: …` for a partly legible date or two
    possible days, `Dátum nélküli óra: …` otherwise."""
    note = str(lesson.data.get("date_note") or "")
    if lesson.dated:
        return hu_dates.meta(hu_dates.short(lesson.lo, year), hu_dates.in_text(note, year))
    what = "Bizonytalan dátum" if PARTLY.search(note) else "Dátum nélküli óra"
    title = f"{what}: {hu_dates.range_text(lesson.lo, lesson.hi, year)}" + (
        "; a helye a sorban nem biztos" if lesson.uncertain else "")
    return hu_dates.meta(hu_dates.approximate(lesson.lo, lesson.hi, year), title, unsure=True)


def after(text: str, lesson: teaching_order.Lesson, year: int) -> str:
    """The important information first, then the quiet date item."""
    return f"{text} {when(lesson, year)}"


def lessons_block(subject: Subject) -> str:
    found = ordered_lessons(subject)
    year = teaching_order.year_of(found)
    rows, states = [], set()
    for item in reversed(found):
        page, lesson = subject.page(item.file), item.data
        topics = ", ".join(topic_link(subject, t) for t in lesson.get("topics") or [])
        states.add(page.meta.get("catch_up"))
        rows.append(f"| {catch_up.mark(page.meta)}{when(item, year)} | "
                    f"{lesson.get('title', '')} | [jegyzet]({lesson_link(page, lesson)}) | {topics} |")
    key = catch_up.legend(states)
    return (f"{key}\n\n" if key else "") + TABLE_HEAD + "".join(r + "\n" for r in rows)


NOW_HEADING = "# 📍 Itt tartunk"
RECENT = 5          # lessons listed before the latest one


def now_block(subject: Subject) -> str:
    """📍 Itt tartunk: the chapter the class started last, the latest lesson with its topics, the
    chapters before, and the lessons before it, newest first (rules 1.22.6: the important
    information first, then the quiet date item)."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    year = teaching_order.year_of(found)
    chapters_ = subject_chapters(subject, found)
    started, spans = teaching_order.by_start(chapters_), teaching_order.spans(chapters_, year)
    latest = found[-1]
    topics = ", ".join(topic_link(subject, t) for t in latest.data.get("topics") or [])
    lines = [NOW_HEADING, ""]
    if started:
        now = started[-1]
        lines.append(f"* **Most:** {teaching_order.plain_title(now.title)} {spans[now.id]}")
    link = f"[{latest.data.get('title', '')}]({lesson_link(subject.page(latest.file), latest.data)})"
    lines.append(f"* **Legutóbb:** {after(link, latest, year)}" + (f" · {topics}" if topics else ""))
    if len(started) > 1:
        lines.append("* **Előtte:** " + " → ".join(
            f"{teaching_order.plain_title(c.title)} {spans[c.id]}" for c in started[:-1]))
    before = list(reversed(found[:-1]))[:RECENT]
    if before:
        lines += ["", "Eddig ebben a sorrendben vettük, a legújabb elöl:", ""]
        lines += ["* " + after(f"[{item.data.get('title', '')}]({lesson_link(subject.page(item.file), item.data)})",
                               item, year) for item in before]
    return "\n".join(lines) + "\n"


def catch_up_description(subject: Subject, page: SubjectPage) -> str:
    """`Dátum: …. Témakörök: ….` from the page's `lessons`, as in the lessons table."""
    lessons_ = [lesson for lesson in page.meta.get("lessons") or [] if isinstance(lesson, dict)]
    found = ordered_lessons(subject)
    year = teaching_order.year_of(found)
    dates = [when(item, year) for item in sorted((x for x in found if x.file == page.file), key=lambda x: x.index)]
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


def place_now(text: str, body: str) -> str:
    """The 📍 block's one fixed place on every subject index: right after the back link to the
    home page, before the catch-up list (else right before the first generated block, else at
    the end). A block standing elsewhere moves there, so existing pages converge."""
    text = markers.remove(text, {"now"})
    back = catch_up.BACK_LINK.search(text)
    block = markers.BLOCK.search(text)
    pos = back.end() if back else (block.start() if block else len(text))
    head, tail = text[:pos].rstrip("\n"), text[pos:].lstrip("\n")
    return head + "\n\n" + markers.wrap("now", body) + "\n" + tail


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
    text = catch_up.update(text, by_date_desc(subject.by_type("lesson-notes")),
                           lambda page: catch_up_description(subject, page))
    return place_now(text, now_block(subject))


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
    """Refresh every index and the Podcast page (while there is an episode: its list shows the
    topic pages' current titles); returns the repo-relative paths that changed."""
    from . import podcast
    changed = []
    targets = [(f"wiki/{s}/index.md", lambda s=s: subject_index(repo, s)) for s in subject_order(repo)]
    targets.append(("wiki/index.md", lambda: root_index(repo)))
    if podcast.records(repo):
        targets.append((podcast.PAGE, lambda: podcast.podcast_page(repo)))
    for rel, build in targets:
        old = read_text(repo, rel) if safefs.is_file(repo, rel) else None
        new = build()
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return changed
