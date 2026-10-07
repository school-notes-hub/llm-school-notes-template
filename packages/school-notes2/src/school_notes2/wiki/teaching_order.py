"""When the class taught what (shared rules 1.22.5: *Lesson-notes pages*, *Subject index*,
*Stable order*), computed from the lesson logs' `lessons` only.

**Bounds.** A lesson's range is its notebook `date`, or the range of its `date_note`
(`<X> után, legkésőbb <Y>` – strictly after X, so the earliest day is X+1 –, `<X>-től`,
`<X> és <Y> között`, `<X> vagy <Y>`); no lower bound is "", no upper bound NEVER.

**Evidence of order.** A lesson certainly comes before another when they stand in one lesson
log in that order (the notebook order), when their pages are successive pages of one notebook
folder (a source folder that holds one notebook – one PDF, or pages split from one; a catch-up
folder of separate photos mixes notebooks and is no evidence), when the later one names the
earlier in its `after` (`<lesson log>.md`: after its last lesson; `<lesson log>.md#<n>`: after its
n-th lesson, from 1; for lessons the dates cannot order), or when its range ends before the
other's begins.
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
from . import hu_dates

ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
LATEST = re.compile(r"legkésőbb\s+(\d{4}-\d{2}-\d{2})")
GRADE = re.compile(r"^\d{1,2}\. évfolyam: ")
NEVER = hu_dates.NEVER


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
    notebook: bool = False  # the folder holds one notebook: its page order is evidence
    before: set = field(default_factory=set)       # ids of the lessons certainly before it (`ordered`)
    after_problem: str = ""                         # an `after` that names no lesson, contradicts dates or closes a circle
    graph: bool = False                             # `before` comes from the order graph

    @property
    def key(self) -> tuple:
        """Presentation order: chronology, then a deterministic fallback (no evidence)."""
        return (self.lo, self.hi, self.folder, self.position, self.file, self.index)


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


def _structural(found: list[Lesson]) -> tuple[dict, list[tuple[Lesson, str]]]:
    """The order graph's evidence edges (id(a) → ids it certainly precedes): one lesson log's
    notebook order, the page order of one notebook folder, and `after`. An `after` that names no
    lesson, contradicts certain dates or closes a circle is a problem and left out."""
    edges: dict[int, set[int]] = {id(x): set() for x in found}
    by_file: dict[str, list[Lesson]] = {}
    for lesson in found:
        by_file.setdefault(lesson.file, []).append(lesson)
    for lessons in by_file.values():
        lessons.sort(key=lambda x: x.index)
        for a, b in zip(lessons, lessons[1:]):
            edges[id(a)].add(id(b))
    folders: dict[str, dict[tuple, list[Lesson]]] = {}
    for lesson in found:
        if lesson.notebook and lesson.folder:
            folders.setdefault(lesson.folder, {}).setdefault(lesson.position, []).append(lesson)
    for positions in folders.values():
        groups = [positions[k] for k in sorted(positions)]
        for earlier, later in zip(groups, groups[1:]):
            for a in earlier:
                edges[id(a)] |= {id(b) for b in later}
    problems = []
    afters = []
    for lesson in found:
        ref = lesson.data.get("after")
        if ref in (None, ""):
            continue
        m = AFTER.match(str(ref))
        target = None
        if m and m[1] in by_file:
            logs = by_file[m[1]]
            n = int(m[2]) if m[2] else len(logs)
            target = logs[n - 1] if 1 <= n <= len(logs) else None
        if target is None or target is lesson:
            problems.append((lesson, f"`after: {ref}` names no lesson of this subject (`<lesson log>.md` or "
                                     "`<lesson log>.md#<n>`, n from 1)"))
            continue
        t_lo, _, _ = bounds(target.data)
        _, l_hi, _ = bounds(lesson.data)
        if t_lo and l_hi != NEVER and t_lo > l_hi:
            problems.append((lesson, f"`after: {ref}` contradicts the dates: that lesson is not before "
                                     f"{l_hi}"))
            continue
        afters.append((target, lesson))
    for target, lesson in afters:
        if id(target) in _reach(edges, id(lesson)) or target is lesson:
            problems.append((lesson, f"`after: {lesson.data.get('after')}` closes a circle with the "
                                     "notebook order or another `after`"))
            continue
        edges[id(target)].add(id(lesson))
    return edges, problems


def _reach(edges: dict, start: int) -> set[int]:
    """Every node reachable from `start` (not itself unless on a circle)."""
    seen, stack = set(), list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(edges.get(node, ()))
    return seen


def _topological(found: list[Lesson], edges: dict) -> list[Lesson]:
    """The lessons in an order every edge respects, ties by `Lesson.key`; a circle left by
    contradictory data is broken at the smallest key (deterministic)."""
    import heapq
    by_id = {id(x): x for x in found}
    indegree = {id(x): 0 for x in found}
    for a, targets in edges.items():
        for b in targets:
            indegree[b] += 1
    heap = [(x.key, id(x)) for x in found if indegree[id(x)] == 0]
    heapq.heapify(heap)
    out, done = [], set()
    while len(out) < len(found):
        if not heap:
            rest = min((x for x in found if id(x) not in done), key=lambda x: x.key)
            indegree[id(rest)] = 0
            heap = [(rest.key, id(rest))]
        _, node = heapq.heappop(heap)
        if node in done:
            continue
        done.add(node)
        out.append(by_id[node])
        for b in edges.get(node, ()):
            indegree[b] -= 1
            if indegree[b] == 0 and b not in done:
                heapq.heappush(heap, (by_id[b].key, b))
    return out


def _narrow(found: list[Lesson], edges: dict) -> None:
    """Never earlier than a lesson that certainly precedes, never later than one that follows."""
    order = _topological(found, edges)
    by_id = {id(x): x for x in found}
    for a in order:
        for b in (by_id[i] for i in edges[id(a)]):
            if not b.dated and a.lo > b.lo:
                b.lo = a.lo
    for b in reversed(order):
        for a in (x for x in found if id(b) in edges[id(x)]):
            if not a.dated and b.hi < a.hi:
                a.hi = b.hi


def known_before(a: Lesson, b: Lesson) -> bool:
    """Evidence only: the combined order graph of `ordered` (notebook order, notebook folders,
    `after`, non-overlapping ranges); for lessons outside it the same rules directly."""
    if b.graph:
        return id(a) in b.before
    if a.file == b.file:
        return a.index < b.index
    if a.notebook and b.notebook and a.folder and a.folder == b.folder and a.position != b.position:
        return a.position < b.position
    return a.hi < b.lo


AFTER = re.compile(r"^([^#\s]+\.md)(?:#(\d+))?$")


def ordered(pages: list[tuple[str, dict]], notebooks: set[str] | None = None) -> list[Lesson]:
    """Every lesson of a subject, oldest first, with its `uncertain` mark (`notebooks`: the
    source folders that hold one notebook). One graph serves ordering, transitivity and circle
    detection: the evidence edges, then the ranges narrowed along them, then an edge wherever a
    range ends before another begins."""
    found = [lesson for file, meta in pages for lesson in page_lessons(file, meta)]
    for lesson in found:
        lesson.notebook = lesson.folder in (notebooks or set())
    edges, problems = _structural(found)
    for lesson, problem in problems:
        lesson.after_problem = problem
    _narrow(found, edges)
    for a in found:
        for b in found:
            if a is not b and a.hi < b.lo:
                edges[id(a)].add(id(b))
    for lesson in found:
        lesson.graph = True
    for lesson in found:                      # `before` holds the ids that certainly precede it
        lesson.before = set()
    for a in found:
        for node in _reach(edges, id(a)):
            if node != id(a):
                next(x for x in found if id(x) == node).before.add(id(a))
    found = _topological(found, edges)
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


def year_of(found: list[Lesson]) -> int:
    return hu_dates.school_year([d for lesson in found for d in (lesson.lo, lesson.hi)])


def span(chapter: Chapter, until: Lesson | None = None, year: int = 0) -> str:
    """When the chapter was taught, in learner words (`hu_dates`): from its start to the latest
    possible day of its lessons that do not certainly come after the current chapter's start
    (`until`; never cut as if certain); exact days for one or two dated lessons, else parts of
    months; the current chapter (no `until`) `… óta`; as a quiet date item (`hu_dates.meta`). An
    undated start, or an undated end of a finished chapter, makes it uncertain (`~`, the range in
    its tooltip)."""
    first = chapter.start
    taught = [lesson for lesson in chapter.lessons
              if not known_before(lesson, first) and (until is None or not known_before(until, lesson))]
    taught = taught or [first]

    def latest(lesson: Lesson) -> str:
        return lesson.lo if lesson.dated else (lesson.hi if lesson.hi != NEVER else lesson.lo)

    last = max(taught, key=lambda lesson: (latest(lesson), lesson.dated))
    if all(lesson.dated for lesson in taught) and len({lesson.lo for lesson in taught}) <= 2:
        start, end = hu_dates.short(first.lo, year), hu_dates.short(last.lo, year)
    else:
        start = hu_dates.part(first.lo or first.hi, year) if (first.lo or first.hi != NEVER) else "?"
        end = hu_dates.part(latest(last), year) if latest(last) else "?"
    notes = []
    if not first.dated:
        notes.append(f"a kezdete dátum nélküli óra ({hu_dates.range_text(first.lo, first.hi, year)})")
    if until is not None and not last.dated and last is not first:
        notes.append(f"a vége dátum nélküli óra ({hu_dates.range_text(last.lo, last.hi, year)})")
    text = f"{start} óta" if until is None else hu_dates.between(start, end)
    return hu_dates.meta(text, ("Nem biztos: " + "; ".join(notes)) if notes else "", unsure=bool(notes))


def spans(found: list[Chapter], year: int = 0) -> dict[str, str]:
    """chapter id → its span; the chapter started last is the current one."""
    started = by_start(found)
    if not started:
        return {}
    current = started[-1]
    return {c.id: span(c, None if c is current else current.start, year) for c in started}


def order_warnings(repo: Path, paths: list[str]) -> list[dict]:
    """Teaching-order items for the pages in `paths` (`sn check`, `sn done`): an error for an
    `after` that names no lesson or closes a circle; warnings on the subject
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
            if lesson.after_problem:
                out.append({**_warn(f"wiki/{slug}/{lesson.file}",
                                    f"lessons[{lesson.index}] ({lesson.data.get('title', '')}): {lesson.after_problem}"),
                            "severity": "error"})
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
