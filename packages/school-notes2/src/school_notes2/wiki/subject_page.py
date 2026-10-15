"""Subject-page teaching-order lists, progress and public lesson-link targets."""

import html
import re
from dataclasses import dataclass

from . import hu_dates, teaching_order
from .pages import read_text
from .subject import Subject, SubjectPage, chapter_pages, covering_lessons


def anchor_id(text: str) -> str:
    """A jump-target id the renderer keeps as written (study-site `isJumpTarget`): lower-case
    letters, digits and hyphens; anything else becomes a hyphen."""
    return "".join(ch if ch.isdigit() or (ch.isalpha() and ch.islower()) or ch == "-" else "-"
                   for ch in text.lower())


def chapter_anchor(chapter_id: str) -> str:
    """The jump target in front of a chapter heading (the 🧭 box and the page breadcrumbs)."""
    return anchor_id(f"fejezet-{chapter_id}")


SUMMARY_NOTE = "A fejezet röviden, ismétléshez és dolgozat előtt."
HERE = "◀ itt tartunk"


def desc(text: str) -> str:
    """A list line's description: smaller and grey under the title (the stylesheet)."""
    return f' <span class="study-desc">{text}</span>' if text else ""


def list_line(page: SubjectPage) -> str:
    return f"* [{page.meta.get('title', page.file)}]({page.file}){desc(page.meta.get('description', ''))}"


def topic_line(number: int, page: SubjectPage, here: bool) -> str:
    """A worked lesson (topic page) in its chapter: 📄, its number in the teaching order, its
    title and description; `◀ itt tartunk` when the latest lesson covered it."""
    mark = f" {HERE}" if here else ""
    return (f"* 📄 {number}. [{page.meta.get('title', page.file)}]({page.file}){mark}"
            f"{desc(page.meta.get('description', ''))}")


def summary_line(page: SubjectPage) -> str:
    """The chapter summary, last in its chapter, with the fixed note of what it is for."""
    return f"* ⚡ [{page.meta.get('title', page.file)}]({page.file}){desc(SUMMARY_NOTE)}"


@dataclass
class Progress:
    """Where the class is (`teaching_order`): the chapter started last (`now`), the chapters
    started before it (`done`), and the pages the latest lesson covered (`latest`)."""
    now: str | None
    done: set[str]
    latest: list[str]
    spans: dict[str, str]


def progress(subject: Subject, found: list[teaching_order.Lesson] | None = None) -> Progress:
    found = ordered_lessons(subject) if found is None else found
    chapters_ = subject_chapters(subject, found)
    started = teaching_order.by_start(chapters_)
    latest = [str(t) for t in (found[-1].data.get("topics") or [])] if found else []
    return Progress(started[-1].id if started else None, {c.id for c in started[:-1]}, latest,
                    teaching_order.spans(chapters_, teaching_order.year_of(found)))


def listed_chapters(subject: Subject) -> list[dict]:
    listed = subject.index_meta.get("chapters")
    return [c for c in listed if isinstance(c, dict) and "id" in c] if isinstance(listed, list) else []


def chapter_mark(state: Progress, chapter_id: str) -> str:
    return " ✓" if chapter_id in state.done else " ◉ most" if chapter_id == state.now else ""


def chapters_block(subject: Subject) -> str:
    """The chapters in the `chapters` list order (the writer keeps it in the order the class
    started them; `sn check` warns otherwise), numbered, each with a jump target, its ✓ (started
    before the current one) or ◉ (the current one) mark and when it was taught (🗓️); inside, the
    worked lessons numbered in teaching order (`order`), the summary last."""
    state = progress(subject)
    latest = {t.split("#", 1)[0] for t in state.latest}
    sections = []
    for number, chapter in enumerate(listed_chapters(subject), 1):
        cid = str(chapter["id"])
        pages = [p for p in chapter_pages(subject, cid) if p.meta.get("type") != "lesson-notes"]
        topics = [p for p in pages if p.meta.get("type") != "chapter-summary"]
        lines = [topic_line(n, p, p.file in latest) for n, p in enumerate(topics, 1)]
        lines += [summary_line(p) for p in pages if p.meta.get("type") == "chapter-summary"]
        head = (f'# <a id="{chapter_anchor(cid)}"></a>📘 {number}. fejezet: '
                f"{teaching_order.plain_title(str(chapter['title']))}{chapter_mark(state, cid)}\n")
        when = f"\n{state.spans[cid]}\n" if cid in state.spans else ""
        sections.append(head + when + ("\n" + "\n".join(lines) + "\n" if lines else ""))
    return "\n<br />\n\n".join(sections)


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


def when_label(span: str) -> str:
    """The visible date text shared by lesson-link keys and the date sweep."""
    return html.unescape(re.sub(r"<[^>]*>", "", span))


LESSONS_HEAD = "# 🗓️ Órák – melyik órán mit vettünk"
LESSONS_LEGEND = ("A legújabb óra van legfelül. A `~` bizonytalan dátumot jelöl; az időszakot az "
                  "egér rávitelekor vagy koppintásra látod.")
LEADING_MARK = re.compile(r"^(\d+)([.)])|^([#>+*-])")


def plain_line(text: str) -> str:
    """A lesson title as plain text at the start of a list line: a leading `1.`, `#`, `>`, `+`,
    `*` or `-` would start Markdown structure, so it is escaped."""
    return LEADING_MARK.sub(lambda m: f"{m[1]}\\{m[2]}" if m[1] else f"\\{m[3]}", text.strip())


def lesson_anchor(item: teaching_order.Lesson) -> str:
    """One target per entry, using its one-based position in the source `lessons` list."""
    return anchor_id(f"ora-{item.file.removesuffix('.md')}-{item.index + 1}")


def lesson_rows(subject: Subject, found: list[teaching_order.Lesson] | None = None) -> list[tuple[teaching_order.Lesson, list[str]]]:
    """Every lesson, newest first, with its numbered row target, plus `ora-<lesson log>` on the
    newest row of each lesson log, `ora-<lesson log>-<anchor>` on a row whose lesson names an
    `anchor` (the first such row when two name the same)."""
    found = ordered_lessons(subject) if found is None else found
    rows, seen = [], set()
    row_ids = {lesson_anchor(item) for item in found}
    for item in reversed(found):
        stem = item.file[:-3] if item.file.endswith(".md") else item.file
        ids = [anchor_id(f"ora-{stem}")]
        if item.data.get("anchor"):
            ids.append(anchor_id(f"ora-{stem}-{item.data['anchor']}"))
        ids = [lesson_anchor(item)] + [i for i in ids if i not in seen and i not in row_ids]
        seen.update(ids)
        rows.append((item, ids))
    return rows


def lessons_block(subject: Subject) -> str:
    """🗓️ Órák: one line per lesson, newest first – the lesson's title, its quiet date, then
    `→` its worked lessons (topic pages); never a link to the lesson log itself."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    year = teaching_order.year_of(found)
    lines = [LESSONS_HEAD, "", LESSONS_LEGEND, ""]
    for item, ids in lesson_rows(subject, found):
        targets = "".join(f'<a id="{i}"></a>' for i in ids)
        topics = " · ".join(topic_link(subject, t) for t in item.data.get("topics") or [])
        lines.append(f"* {targets}{plain_line(str(item.data.get('title', '')))} {when(item, year)}"
                     + (f"<br />→ {topics}" if topics else ""))
    return "\n".join(lines) + "\n"


JUMP_ID = re.compile(r'<a id="([^"]+)"></a>')


def topic_lesson_links(lessons, labels: dict[tuple[str, int], str]) -> dict[str, str]:
    """Topic keys for one log, choosing the first covering lesson in source order."""
    links: dict[str, str] = {}
    for topic in sorted({t for item in lessons for t in item.topics}):
        for item in covering_lessons(lessons, topic):
            links.setdefault("|" + topic, lesson_anchor(item))
            links.setdefault(labels[item.file, item.index] + "|" + topic, lesson_anchor(item))
    return links


def lesson_links(subject: Subject) -> dict[str, dict[str, str]]:
    """Where a link to a lesson log goes on the public site (it is not published there): for each
    lesson log of the subject, fragment → the jump target of its row in the 🗓️ Órák list. `""`
    is the newest-row fallback; `@<when text>` identifies a unique date on that log. `|topic`
    and `@<when text>|topic` select the first covering lesson in the source list (with that
    date for the latter). A lesson's `anchor` selects its own row; every
    other jump target written on the same line as a lesson's anchor in the log that lesson's row."""
    rows: dict[str, dict[str, str]] = {}
    dates: dict[tuple[str, str], list[str]] = {}
    labels: dict[tuple[str, int], str] = {}
    found = ordered_lessons(subject)
    year = teaching_order.year_of(found)
    for item, ids in reversed(lesson_rows(subject, found)):
        stem = item.file[:-3]
        page = rows.setdefault(item.file, {})
        label = when_label(when(item, year))
        labels[item.file, item.index] = "@" + label
        dates.setdefault((item.file, "@" + label), []).append(lesson_anchor(item))
        base = anchor_id(f"ora-{stem}")
        page[""] = base if base in ids else lesson_anchor(item)
        anchor = item.data.get("anchor")
        own = anchor_id(f"ora-{stem}-{anchor}") if anchor else ""
        if anchor:
            page[str(anchor)] = own if own in ids else lesson_anchor(item)
    for (file, label), targets in dates.items():
        if len(targets) == 1:
            rows[file][label] = targets[0]
    for file, page in rows.items():
        own_lessons = [item for item in found if item.file == file]
        for key, target in topic_lesson_links(own_lessons, labels).items():
            page.setdefault(key, target)
        try:
            text = read_text(subject.repo, f"wiki/{subject.slug}/{file}") if subject.repo else ""
        except OSError:
            text = ""
        for line in text.splitlines():
            found_ids = JUMP_ID.findall(line)
            owner = next((page[i] for i in found_ids if i in page and i), None)
            for i in found_ids:
                if owner and i not in page:
                    page[i] = owner
    return {file: dict(sorted(page.items())) for file, page in sorted(rows.items())}


def now_block(subject: Subject) -> str:
    """🧭 Hol tartunk, a box without a heading: the chapters in the `chapters` list order on one
    line (✓ started before the current one, ◉ the current one, with when it was taught), the
    worked lessons of the latest lesson, and the current chapter's summary for revision. Only
    topic pages and summaries are linked, never a lesson log."""
    found = ordered_lessons(subject)
    if not found:
        return ""
    state = progress(subject, found)
    steps = []
    for chapter in listed_chapters(subject):
        cid = str(chapter["id"])
        kind = " class=\"study-path-done\"" if cid in state.done else \
            " class=\"study-path-now\"" if cid == state.now else ""
        mark = " ✓" if cid in state.done else " ◉" if cid == state.now else ""
        when_ = f" {state.spans[cid]}" if cid in state.spans and kind else ""
        steps.append(f'<li{kind}><a href="#{chapter_anchor(cid)}">'
                     f"{teaching_order.plain_title(str(chapter['title']))}</a>{mark}{when_}</li>")
    lines = ["> [!PROGRESS]", "> 🧭 **Hol tartunk**", ">", '> <ol class="study-path">' + "".join(steps) + "</ol>"]
    pages = []
    for topic in state.latest:
        page = subject.page(topic.split("#", 1)[0])
        if page and page.meta.get("type") in ("topic", "chapter-summary"):
            icon = "⚡" if page.meta["type"] == "chapter-summary" else "📄"
            pages.append(f"{icon} [{page.meta.get('title', topic)}]({topic})")
    if pages:
        lines += [">", "> **Most:** " + " · ".join(pages)]
    summary = next((p for p in chapter_pages(subject, state.now)
                    if p.meta.get("type") == "chapter-summary"), None) if state.now else None
    if summary:
        lines += [">", f"> **Ismétléshez:** ⚡ [{summary.meta.get('title', summary.file)}]({summary.file})"]
    return "\n".join(lines) + "\n"


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
    """Empty: the lesson logs are the writer's tool and not on the public site; the 🗓️ Órák list
    says which lesson covered what. The block stays, so its name keeps its place."""
    return ""
