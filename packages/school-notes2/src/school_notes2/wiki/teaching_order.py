"""When the class taught what (shared rules 1.22.4: *Lesson-notes pages*, *Subject index*,
*Stable order*), computed from the lesson logs' `lessons` only.

A lesson is placed by its notebook `date`; an undated one by the LOWER bound of its `date_note`
range (`<X> után, legkésőbb <Y>`, `<X>-től`, `<X> és <Y> között`, `<X> vagy <Y>`), then by the
upper bound, then by where its page starts in the notebook, the file name and its place in the
page. Inside one lesson log the lessons stand in notebook order, so a later lesson's lower bound
is never earlier than the one before it, and an earlier lesson's upper bound never later than
the one after it. A lesson with no lower bound sorts first (oldest): its place is unknown.

Two lessons are in a *known* order when their ranges do not overlap, when they stand in one
lesson log, or when they have the same range and come from the same source folder (the pages
of one folder keep the notebook's order). An undated lesson that is in no known order with some
other lesson is *uncertain*: the index marks it, so the learner does not read a false order (a
lesson with no lower bound is uncertain itself but does not make the others uncertain).

A chapter starts with the first lesson whose `topics` names one of its pages; chapters are
ordered by that start, then by the average day of their lessons, then by the `chapters` list.
Later lessons (a revisit) never move a chapter."""

import posixpath
import re
from dataclasses import dataclass, field
from datetime import date

from ..sources.order import natural_key

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
LATEST = re.compile(r"legkésőbb\s+(\d{4}-\d{2}-\d{2})")
GRADE = re.compile(r"^\d{1,2}\. évfolyam: ")
NEVER = "9999-12-31"
MONTHS = ("január", "február", "március", "április", "május", "június", "július", "augusztus",
          "szeptember", "október", "november", "december")


@dataclass
class Lesson:
    file: str               # the lesson log's file name in the subject folder
    index: int              # its place in the page's `lessons`
    data: dict              # the `lessons` entry
    lo: str                 # earliest possible day ("" unknown)
    lo_open: bool           # strictly after `lo` (`<X> után`)
    hi: str                 # latest possible day (NEVER unknown)
    dated: bool
    folder: str             # the page's first source folder
    position: tuple         # where the page starts in the notebook
    uncertain: bool = False
    topics: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.lo, 0 if self.dated else 1, self.hi, self.position, self.file, self.index)

    @property
    def day(self) -> str:
        """The day that stands for the lesson: its date, else its lower (else upper) bound."""
        return self.lo or (self.hi if self.hi != NEVER else "")


def bounds(lesson: dict) -> tuple[str, bool, str, bool]:
    """(lo, lo_open, hi, dated) of one `lessons` entry."""
    day = str(lesson.get("date") or "")
    if ISO.fullmatch(day):
        return day, False, day, True
    note = str(lesson.get("date_note") or "")
    found = ISO.findall(note)
    latest = LATEST.search(note)
    if latest:
        hi, rest = latest[1], list(found)
        rest.remove(latest[1])
        lo = min(rest) if rest else ""
    else:
        lo = min(found) if found else ""
        hi = max(found) if len(found) > 1 else NEVER
    return lo, bool(lo and re.search(re.escape(lo) + r"\s+után", note)), hi, False


def first_folder(meta: dict) -> str:
    source = meta.get("source_file")
    if isinstance(source, list):
        source = source[0] if source else ""
    source = str(source or "").removeprefix("sources/")
    return source.rstrip("/") if source.endswith("/") else posixpath.dirname(source)


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


def page_lessons(file: str, meta: dict) -> list[Lesson]:
    entries = [e for e in meta.get("lessons") or [] if isinstance(e, dict)]
    raw = [list(bounds(e)) for e in entries]
    floor = ""
    for row in raw:                       # notebook order: never earlier than the one before
        if not row[3] and floor > row[0]:
            row[0], row[1] = floor, False
        floor = max(floor, row[0])
    ceiling = NEVER
    for row in reversed(raw):             # … and never later than the one after
        if not row[3] and ceiling < row[2]:
            row[2] = ceiling
        ceiling = min(ceiling, row[2])
    folder, position = first_folder(meta), notebook_position(meta)
    return [Lesson(file, i, e, lo, op, hi, dated, folder, position,
                   topics=[str(t).split("#", 1)[0] for t in e.get("topics") or []])
            for i, (e, (lo, op, hi, dated)) in enumerate(zip(entries, raw))]


def known_before(a: Lesson, b: Lesson) -> bool:
    if a.file == b.file:
        return a.index < b.index
    if a.hi < b.lo or (a.hi == b.lo and b.lo_open):
        return True
    return (a.folder == b.folder and a.folder != "" and (a.lo, a.dated, a.hi) == (b.lo, b.dated, b.hi)
            and (a.position, a.file) < (b.position, b.file))


def ordered(pages: list[tuple[str, dict]]) -> list[Lesson]:
    """Every lesson of a subject, oldest first, with its `uncertain` mark."""
    found = sorted((lesson for file, meta in pages for lesson in page_lessons(file, meta)),
                   key=lambda lesson: lesson.key)
    for lesson in found:
        # A lesson with no lower bound is itself uncertain; it does not make the others so.
        lesson.uncertain = not lesson.dated and any(
            other is not lesson and (other.lo or not lesson.lo)
            and not known_before(other, lesson) and not known_before(lesson, other)
            for other in found)
    return found


@dataclass
class Chapter:
    id: str
    title: str
    place: int                       # in the `chapters` list
    lessons: list[Lesson]            # the lessons whose `topics` name one of its pages, oldest first

    @property
    def start(self) -> Lesson | None:
        """The first lesson with a known lower bound (one without could be any time)."""
        known = [lesson for lesson in self.lessons if lesson.lo]
        return (known or self.lessons or [None])[0]

    @property
    def average(self) -> float:
        # lessons with a known lower bound only (one without could be any time)
        days = [date.fromisoformat(lesson.lo).toordinal() for lesson in self.lessons if lesson.lo]
        return sum(days) / len(days) if days else 0.0

    @property
    def key(self) -> tuple:
        return (self.start.key if self.start else ("",), self.average, self.place)


def chapters(index_meta: dict, page_chapter: dict[str, str], lessons: list[Lesson]) -> list[Chapter]:
    """The `chapters` list with each chapter's lessons (`page_chapter`: topic file → chapter id)."""
    out = []
    for place, entry in enumerate(index_meta.get("chapters") or []):
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        mine = [lesson for lesson in lessons if any(page_chapter.get(t) == cid for t in lesson.topics)]
        out.append(Chapter(str(cid), str(entry.get("title", cid)), place, mine))
    return out


def by_start(found: list[Chapter]) -> list[Chapter]:
    """The chapters that have lessons, in the order the class started them."""
    return sorted((c for c in found if c.lessons), key=lambda c: c.key)


def order_problems(found: list[Chapter]) -> list[tuple[str, str]]:
    """(later, earlier): a chapter listed after another although the class started it first –
    only when the two starts are in a known order."""
    listed = [c for c in found if c.lessons]
    return [(b.id, a.id) for a, b in zip(listed, listed[1:]) if known_before(b.start, a.start)]


def plain_title(title: str) -> str:
    return GRADE.sub("", title)


def _part(day: str) -> str:
    d = int(day[8:10])
    return "eleje" if d <= 10 else "közepe" if d <= 20 else "vége"


def month_part(day: str) -> str:
    return f"{MONTHS[int(day[5:7]) - 1]} {_part(day)}"


def exact(day: str) -> str:
    return f"{MONTHS[int(day[5:7]) - 1]} {int(day[8:10])}."


def span(chapter: Chapter, until: Lesson | None = None) -> str:
    """When the chapter was taught, in learner words: from its start to its last lesson before
    the current chapter started (`until`; a revisit after that does not stretch it); exact days for one
    or two dated lessons, else parts of months. The current chapter (no `until`): `… óta, még tart`."""
    first = chapter.start
    taught = [lesson for lesson in chapter.lessons
              if lesson.key >= first.key and (until is None or lesson.key < until.key)] or [first]
    last = taught[-1]
    if all(lesson.dated for lesson in taught) and len({lesson.lo for lesson in taught}) <= 2:
        start, end = exact(first.lo), exact(last.lo)
    else:
        start = month_part(first.day) if first.day else "?"
        end_day = last.lo if last.dated else (last.hi if last.hi != NEVER else last.lo)
        if until is not None and until.hi != NEVER and end_day > until.hi:
            end_day = until.hi       # it is placed before the current chapter's start
        end = month_part(end_day) if end_day else "?"
    if until is None:
        return f"{start} óta, még tart"
    return start if start == end else f"{start} – {end}"


def spans(found: list[Chapter]) -> dict[str, str]:
    """chapter id → its span; the chapter started last is the current one."""
    started = by_start(found)
    if not started:
        return {}
    current = started[-1]
    return {c.id: span(c, None if c is current else current.start) for c in started}
