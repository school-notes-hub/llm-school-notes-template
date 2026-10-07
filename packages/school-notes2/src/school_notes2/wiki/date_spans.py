"""Hand-written lesson dates as the tool writes them (rules 1.22.8): a date span in a lesson line
(`<sub>🗓️ Óra: …</sub>` on a topic page, a lesson log's own `🗓️ Órák: …` line) is rewritten to
exactly what `generate.when()` gives for that lesson – its text and tooltip, nothing else on the
line – and the lessons legend of every subject index becomes the one text `machine.LESSONS_LEGEND`.
`sn close <t> --dates` applies it; `sn check` warns where a span differs.

A span is matched to its lesson only when that is certain: a span that is the text of a link to
a lesson log (`[<span …>](<log>.md#<anchor>)`) – by the anchor, or the log's only lesson, or its
only lesson of the same kind (dated / undated), or lessons that all give the same span; on a
lesson log's own line its undated spans in order to its undated lessons; a span followed by
` - <lesson title>` by that title. Any other span is left as it is. Lesson and textbook lines
are not part of a figure's verdict key, so none of this sends a figure to a recheck."""

import re
from pathlib import Path

from . import markers

# A complete, closed lesson or textbook line (shared with the figure verdict key).
META_LINE = re.compile(r"^[ \t]*<sub>[ \t]*(?:🗓️ (?:Óra|Órák|Lesson|Lessons):|🔖 (?:Tankönyv|Textbook):)"
                       r"(?:(?!</sub>)[^\n])*</sub>(?:\[\^[^\]\s]+\])*[ \t]*$", re.M)
SPAN = re.compile(r'<span class="study-when(?P<unsure> study-when-unsure)?"(?: title="[^"]*")?>[^<]*</span>')
LINK_AFTER = re.compile(r'\]\((?P<target><[^>\n]*>|[^)\s]*)\)')
TITLE_AFTER = re.compile(r"[ \t]+-[ \t]+(?P<title>(?:(?!</sub>| · )[^\n])+?)[ \t]*(?: · |</sub>)")
LESSONS_HEAD = re.compile(r"^# 🗓️ Órák[ \t]*\n", re.M)


def _resolve(match, line: str, offset: int, page: str, found, own_undated: dict):
    """The lesson a span stands for, or None when that is not certain."""
    from . import generate
    by_file: dict = {}
    for lesson in found:
        by_file.setdefault(lesson.file, []).append(lesson)
    start, end = match.start() - offset, match.end() - offset
    linked = line[start - 1:start] == "[" and LINK_AFTER.match(line, end)
    if linked:
        target = linked["target"].strip("<>")
        file, _, anchor = target.partition("#")
        lessons = sorted(by_file.get(file, []), key=lambda x: x.index) if "/" not in file else []
        if anchor:
            lessons = [x for x in lessons if x.data.get("anchor") == anchor]
        if len(lessons) > 1:
            same = [x for x in lessons if x.dated != bool(match["unsure"])]
            lessons = same if same else lessons
        if len(lessons) > 1:
            year = generate.teaching_order.year_of(found)
            if len({generate.when(x, year) for x in lessons}) == 1:
                lessons = lessons[:1]
        return lessons[0] if len(lessons) == 1 else None
    if match["unsure"] and page in own_undated:
        queue = own_undated[page]
        return queue.pop(0) if queue else None
    titled = TITLE_AFTER.match(line, end)
    if titled:
        same = [x for x in found if str(x.data.get("title", "")).strip() == titled["title"].strip()]
        return same[0] if len(same) == 1 else None
    return None


def _blank_blocks(text: str) -> str:
    """The page with its generated blocks blanked (same length): the tool's own text is not
    hand-written."""
    for start, end, _ in markers.spans(text):
        text = text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]
    return text


def page_changes(text: str, page: str, found) -> list[tuple[int, int, str, str]]:
    """(start, end, old, new) for every hand-written date span of the page's lesson lines that
    differs from the generated one."""
    from . import generate, teaching_order
    year = teaching_order.year_of(found)
    own = sorted((x for x in found if x.file == page and not x.dated), key=lambda x: x.index)
    own_undated = {page: list(own)} if own else {}
    out = []
    shown = _blank_blocks(text)
    for line in META_LINE.finditer(shown):
        if not line[0].lstrip().startswith("<sub>🗓️"):
            continue
        for span in SPAN.finditer(text, line.start(), line.end()):
            lesson = _resolve(span, text[line.start():line.end()], line.start(), page, found, own_undated)
            if lesson is None:
                continue
            new = generate.when(lesson, year)
            if new != span[0]:
                out.append((span.start(), span.end(), span[0], new))
    return out


def legend_change(text: str) -> str:
    """A subject index with the one lessons legend between `# 🗓️ Órák` and the lessons table."""
    from .machine import LESSONS_LEGEND
    head = LESSONS_HEAD.search(text)
    table = text.find("<!-- school-notes:generated lessons -->", head.end()) if head else -1
    if table < 0:
        return text
    return text[:head.end()] + "\n" + LESSONS_LEGEND + "\n\n" + text[table:]


def subject_pages(repo: Path):
    """(subject slug, ordered lessons, [(rel, text)]) per subject."""
    from . import generate
    from .pages import md_files, read_text
    for slug in generate.subject_order(repo):
        subject = generate.load_subject(repo, slug)
        found = generate.ordered_lessons(subject)
        pages = [(rel, read_text(repo, rel)) for rel in md_files(repo, f"wiki/{slug}/*.md")]
        yield slug, found, pages


def apply(repo: Path) -> list[tuple[str, int]]:
    """Rewrite the differing spans and legends in place; (page, number of changes)."""
    from ..state import safefs
    done = []
    for _, found, pages in subject_pages(repo):
        for rel, text in pages:
            changes = page_changes(text, rel.rsplit("/", 1)[1], found)
            new = text
            for start, end, _, replacement in sorted(changes, reverse=True):
                new = new[:start] + replacement + new[end:]
            count = len(changes)
            if rel.endswith("/index.md"):
                legend = legend_change(new)
                count += legend != new
                new = legend
            if new != text:
                safefs.write_text(repo, rel, new)
                done.append((rel, count))
    return done


def warnings(repo: Path, paths: list[str]) -> list[dict]:
    """`sn check`: a hand-written date span that differs from the generated one."""
    from . import generate
    wanted = set(paths)
    out = []
    for slug in sorted({p.split("/")[1] for p in paths if p.count("/") == 2 and p.startswith("wiki/")}):
        try:
            subject = generate.load_subject(repo, slug)
        except (ValueError, OSError):
            continue
        found = generate.ordered_lessons(subject)
        from .pages import read_text
        for rel in sorted(p for p in wanted if p.startswith(f"wiki/{slug}/") and p.endswith(".md")):
            try:
                text = read_text(repo, rel)
            except OSError:
                continue
            for start, _, old, new in page_changes(text, rel.rsplit("/", 1)[1], found):
                out.append({"file": rel, "line": text.count("\n", 0, start) + 1, "severity": "warning",
                            "message": f"the date {old} differs from the generated {new}; "
                                       "`sn close <learner> --dates` rewrites it"})
    return out
