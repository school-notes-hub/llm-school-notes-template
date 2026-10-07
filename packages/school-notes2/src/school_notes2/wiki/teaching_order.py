"""When the class taught what (shared rules 1.22.5: *Lesson-notes pages*, *Subject index*,
*Stable order*), computed from the lesson logs' `lessons` only.

**Bounds.** A lesson's range is its notebook `date`, or the range of its `date_note`
(`<X> után, legkésőbb <Y>` – strictly after X, so the earliest day is X+1 –, `<X>-től`,
`<X> és <Y> között`, `<X> vagy <Y>`); no lower bound is "", no upper bound NEVER.

**Evidence of order.** A lesson certainly comes before another when they stand in one lesson
log in that order (the notebook order), when their pages are successive pages of one source
folder (the page positions of one notebook), or when its range ends before the other's begins.
The ranges are narrowed along that evidence: an undated lesson is never earlier than a lesson
that certainly comes before it, nor later than one that certainly comes after it. A file name,
an alphabetical folder order or two pages at the same position are no evidence: they only keep
the output deterministic.

**Order.** Lessons sort by lower bound, upper bound, then the deterministic fallback (folder,
page position, file, index); inside one lesson log only the index decides. An undated lesson
that is in no certain order with some other lesson is *uncertain* (↕); a lesson with no lower
bound is uncertain itself but does not make the others so.

**Chapters.** A chapter starts with the first lesson whose `topics` names one of its pages: of
its lessons, one that no other of them certainly precedes, preferring one with a known lower
bound (a lesson with only an upper bound starts the chapter when the evidence puts it before the
others); a later lesson (a revisit) therefore never becomes the start while an earlier one is
evidenced. Chapters are ordered by their start lesson's chronology (its range; no file name);
two chapters started in the same lesson by the order of their first topic in that lesson's
`topics`, then by the `chapters` list. Nothing that comes later moves a chapter."""

import functools
import posixpath
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ..sources.order import natural_key

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
LATEST = re.compile(r"legkésőbb\s+(\d{4}-\d{2}-\d{2})")
GRADE = re.compile(r"^\d{1,2}\. évfolyam: ")
NEVER = "9999-12-31"
MONTHS = ("január", "február", "március", "április", "május", "június", "július", "augusztus",
          "szeptember", "október", "november", "december")
UNCERTAIN = " ↕"


@dataclass
class Lesson:
    file: str               # the lesson log's file name in the subject folder
    index: int              # its place in the page's `lessons`
    data: dict              # the `lessons` entry
    lo: str                 # earliest possible day, inclusive ("" unknown)
    hi: str                 # latest possible day, inclusive (NEVER unknown)
    dated: bool
    folder: str             # the page's first source folder
    position: tuple         # where the page starts in that folder
    uncertain: bool = False
    topics: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        """Presentation order: chronology, then a deterministic fallback (no evidence)."""
        return (self.lo, self.hi, self.folder, self.position, self.file, self.index)

    @property
    def day(self) -> str:
        """The day that stands for the lesson: its date, else its lower (else upper) bound."""
        return self.lo or (self.hi if self.hi != NEVER else "")


def _next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def bounds(lesson: dict) -> tuple[str, str, bool]:
    """(lo, hi, dated) of one `lessons` entry, both bounds inclusive."""
    day = str(lesson.get("date") or "")
    if ISO.fullmatch(day):
        return day, day, True
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
    if lo and re.search(re.escape(lo) + r"\s+után", note):
        lo = _next_day(lo)                       # strictly after X: X+1 at the earliest
    return lo, hi, False


def source_folders(meta: dict) -> list[str]:
    value = meta.get("source_file")
    values = value if isinstance(value, list) else [value] if value else []
    out = []
    for v in values:
        v = str(v).removeprefix("sources/")
        out.append(v.rstrip("/") if v.endswith("/") else posixpath.dirname(v))
    return out


def first_folder(meta: dict) -> str:
    return (source_folders(meta) or [""])[0]


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
    entries = [e for e in meta.get("lessons") or [] if isinstance(e, dict)] \
        if isinstance(meta.get("lessons"), list) else []
    folder, position = first_folder(meta), notebook_position(meta)
    out = []
    for i, entry in enumerate(entries):
        lo, hi, dated = bounds(entry)
        topics = entry.get("topics") if isinstance(entry.get("topics"), list) else []
        out.append(Lesson(file, i, entry, lo, hi, dated, folder, position,
                          topics=[str(t).split("#", 1)[0] for t in topics]))
    return out


def _sequences(found: list[Lesson]) -> list[list[list[list[Lesson]]]]:
    """The evidence chains: per source folder, its pages by position (pages at one position
    side by side), each page's lessons in notebook order; a page without a folder alone."""
    by_folder: dict[str, dict[tuple, dict[str, list[Lesson]]]] = {}
    for lesson in found:
        folder = lesson.folder or f"\0{lesson.file}"
        by_folder.setdefault(folder, {}).setdefault(lesson.position, {}).setdefault(lesson.file, []).append(lesson)
    return [[list(pages.values()) for _, pages in sorted(positions.items())]
            for _, positions in sorted(by_folder.items())]


def _narrow(found: list[Lesson]) -> None:
    for chain in _sequences(found):
        floor = ""
        for group in chain:                     # forward: never earlier than what came before
            reached = floor
            for page in group:
                running = floor
                for lesson in sorted(page, key=lambda item: item.index):
                    if not lesson.dated and running > lesson.lo:
                        lesson.lo = running
                    running = max(running, lesson.lo)
                reached = max(reached, running)
            floor = reached
        ceiling = NEVER
        for group in reversed(chain):           # backward: never later than what comes after
            reached = ceiling
            for page in group:
                running = ceiling
                for lesson in sorted(page, key=lambda item: -item.index):
                    if not lesson.dated and running < lesson.hi:
                        lesson.hi = running
                    running = min(running, lesson.hi)
                reached = min(reached, running)
            ceiling = reached


def known_before(a: Lesson, b: Lesson) -> bool:
    """Evidence only: the notebook order of one lesson log, successive pages of one source
    folder, or ranges that do not overlap."""
    if a.file == b.file:
        return a.index < b.index
    if a.folder and a.folder == b.folder and a.position != b.position:
        return a.position < b.position
    return a.hi < b.lo


def ordered(pages: list[tuple[str, dict]]) -> list[Lesson]:
    """Every lesson of a subject, oldest first, with its `uncertain` mark."""
    found = [lesson for file, meta in pages for lesson in page_lessons(file, meta)]
    _narrow(found)
    found.sort(key=lambda lesson: lesson.key)
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
    pages: set[str] = field(default_factory=set)

    @property
    def start(self) -> Lesson | None:
        if not self.lessons:
            return None
        first = [lesson for lesson in self.lessons
                 if not any(known_before(other, lesson) for other in self.lessons if other is not lesson)]
        known = [lesson for lesson in first if lesson.lo]
        return min(known or first or self.lessons, key=lambda lesson: lesson.key)

    def topic_place(self) -> int:
        """Where the chapter's first topic stands in its start lesson's `topics`."""
        return next((i for i, t in enumerate(self.start.topics) if t in self.pages), 10**6)


def chapters(index_meta: dict, page_chapter: dict[str, str], lessons: list[Lesson]) -> list[Chapter]:
    """The `chapters` list with each chapter's lessons (`page_chapter`: topic file → chapter id)."""
    out = []
    listed = index_meta.get("chapters") if isinstance(index_meta.get("chapters"), list) else []
    for place, entry in enumerate(listed):
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("id"))
        pages = {f for f, c in page_chapter.items() if c == cid}
        mine = [lesson for lesson in lessons if any(t in pages for t in lesson.topics)]
        out.append(Chapter(cid, str(entry.get("title", cid)), place, mine, pages))
    return out


def _compare(a: Chapter, b: Chapter) -> int:
    x, y = a.start, b.start
    if (x.lo, x.hi) != (y.lo, y.hi):
        return -1 if (x.lo, x.hi) < (y.lo, y.hi) else 1
    if x is y and a.topic_place() != b.topic_place():
        return -1 if a.topic_place() < b.topic_place() else 1
    if x is not y and known_before(x, y):
        return -1
    if x is not y and known_before(y, x):
        return 1
    return -1 if a.place < b.place else (1 if a.place > b.place else 0)


def by_start(found: list[Chapter]) -> list[Chapter]:
    """The chapters that have lessons, in the order the class started them."""
    return sorted((c for c in found if c.lessons), key=functools.cmp_to_key(_compare))


def order_problems(found: list[Chapter]) -> list[tuple[str, list[str], str | None]]:
    """(chapter, the chapters listed before it although it certainly started earlier, the
    chapter it belongs right after – None: first) for every provable inversion of the list."""
    listed = [c for c in found if c.lessons]
    out = []
    for j, chapter in enumerate(listed):
        later = [c.id for c in listed[:j] if known_before(chapter.start, c.start)]
        if not later:
            continue
        after = next((c.id for c in reversed(listed[:j]) if not known_before(chapter.start, c.start)), None)
        out.append((chapter.id, later, after))
    return out


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
    """When the chapter was taught, in learner words: from its start to the latest possible day
    of its lessons that do not certainly come after the current chapter's start (`until`); exact days for one or
    two dated lessons, else parts of months; the current chapter (no `until`) `… óta, még
    tart`. An undated start, or an undated last lesson of a finished chapter, makes the span
    uncertain (↕): its edge is a range, never cut as if certain."""
    first = chapter.start
    taught = [lesson for lesson in chapter.lessons
              if not known_before(lesson, first) and (until is None or not known_before(until, lesson))]
    taught = taught or [first]

    def latest(lesson: Lesson) -> str:
        return lesson.lo if lesson.dated else (lesson.hi if lesson.hi != NEVER else lesson.lo)

    last = max(taught, key=lambda lesson: (latest(lesson), lesson.dated))
    mark = "" if first.dated and (until is None or last.dated) else UNCERTAIN
    if all(lesson.dated for lesson in taught) and len({lesson.lo for lesson in taught}) <= 2:
        start, end = exact(first.lo), exact(last.lo)
    else:
        start = month_part(first.lo) if first.lo else (
            f"legkésőbb {month_part(first.hi)}" if first.hi != NEVER else "?")
        end = month_part(latest(last)) if latest(last) else "?"
    if until is None:
        return f"{start} óta, még tart{mark}"
    return (start if start == end else f"{start} – {end}") + mark


def spans(found: list[Chapter]) -> dict[str, str]:
    """chapter id → its span; the chapter started last is the current one."""
    started = by_start(found)
    if not started:
        return {}
    current = started[-1]
    return {c.id: span(c, None if c is current else current.start) for c in started}


def order_warnings(repo: Path, paths: list[str]) -> list[dict]:
    """Teaching-order warnings for the pages in `paths` (`sn check`, `sn done`): on the subject
    index every chapter the `chapters` list puts after one it certainly started before (with the
    place it belongs); on a topic page that no lesson's `topics` names; on a lesson log an
    undated lesson without a lower bound, or with a `legkésőbb` bound earlier than a dated lesson
    from the same source folder (a folder label is no upper bound)."""
    import yaml
    from . import generate
    from ..state import safefs
    out = []
    wanted = set(paths)
    for slug in sorted({p.split("/")[1] for p in paths if p.count("/") == 2 and p.startswith("wiki/")}):
        if slug == "assets" or not safefs.is_file(repo, f"wiki/{slug}/index.md"):
            continue
        try:
            subject = generate.load_subject(repo, slug)
        except (ValueError, yaml.YAMLError):
            continue                 # unreadable frontmatter: reported on its own
        found = generate.ordered_lessons(subject)
        listed = generate.subject_chapters(subject, found)
        titles = {c.id: c.title for c in listed}
        for cid, later, after in order_problems(listed):
            start = next(c.start for c in listed if c.id == cid)
            where = f"right after {after!r} ({titles[after]})" if after else "first in the list"
            out.append(_warn(f"wiki/{slug}/index.md", (
                f"`chapters`: {cid!r} ({titles[cid]}) is listed after "
                f"{', '.join(repr(c) for c in later)}, but the class started it first "
                f"({generate.lesson_date(start.data)}: {start.data.get('title', '')}); it belongs {where} "
                "(the chapters stand in the order the class started them)")))
        named = {t for lesson in found for t in lesson.topics}
        for page in subject.by_type("topic"):
            if page.file not in named:
                out.append(_warn(f"wiki/{slug}/{page.file}", (
                    "no lesson's `topics` names this topic page, so it has no place in the teaching "
                    "order: list it in `topics` of the lesson that taught it")))
        for lesson in found:
            if lesson.dated:
                continue
            rel, raw = f"wiki/{slug}/{lesson.file}", bounds(lesson.data)
            what = f"lessons[{lesson.index}] ({lesson.data.get('title', '')})"
            if not raw[0]:
                out.append(_warn(rel, f"{what}: `date_note` has no lower bound; write `<X> után, legkésőbb "
                                      "<Y>` with X the date of the last lesson before it"))
            if not LATEST.search(str(lesson.data.get("date_note") or "")) or not lesson.folder:
                continue             # no `legkésőbb` bound (e.g. a partly legible date)
            later = sorted(other.lo for other in found
                           if other.dated and other.folder == lesson.folder and other.lo > raw[1])
            if later:
                out.append(_warn(rel, (
                    f"{what}: the `date_note` upper bound {raw[1]} is earlier than the dated lesson of "
                    f"{later[-1]} from the same source folder {lesson.folder}; the upper bound of a "
                    "catch-up lesson is the day the material was fetched (`placed` in its sn-fetch.json), "
                    "never a folder label")))
    return [w for w in out if w["file"] in wanted]


def _warn(rel: str, message: str) -> dict:
    return {"file": rel, "line": None, "message": message, "severity": "warning"}
