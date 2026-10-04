"""One-time derivation of the v2 index data from today's hand-written indexes (plan 11/3).

Reads the v1 subject indexes and root index and produces: `chapters` and `description`
in each subject index, `chapter`/`order` on chapter pages, `lessons` on lesson-notes pages
(instead of `lesson_dates`), generated-block markers, and subjects.json in root-list order.
The migration script calls `migrate(repo)`; T1 then regenerates and compares.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter, markers

LINK = re.compile(r"\[([^\]]+)\]\(([^)#\s]+)(?:#[^)]*)?\)")
TOPIC = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
NOTE_LINK = re.compile(r"\[[^\]]+\]\(([^)#\s]+)(?:#([^)\s]+))?\)")
GRADE = re.compile(r"^\d+\. évfolyam: ")
TRIM = ("", "<br />")


@dataclass
class Migration:
    warnings: list[str] = field(default_factory=list)
    page_keys: dict[str, dict] = field(default_factory=dict)   # repo-relative path -> keys


def slugify(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(heading, first line, end line exclusive) for every `# ` heading of the body."""
    heads = [i for i, ln in enumerate(lines) if ln.startswith("# ")]
    return [(lines[i], i, heads[k + 1] if k + 1 < len(heads) else len(lines))
            for k, i in enumerate(heads)]


def content_end(lines: list[str], start: int, end: int) -> int:
    """End of a section's content: trailing blank and `<br />` lines belong outside."""
    while end > start and lines[end - 1].strip() in TRIM:
        end -= 1
    return end


def chapter_id(title: str, taken: set[str]) -> str:
    base = slugify(GRADE.sub("", title)) or "fejezet"
    if base in taken:
        base = slugify(title)
    taken.add(base)
    return base


def parse_chapters(lines, secs, slug, mig) -> tuple[list[dict], tuple[int, int] | None]:
    chapters, taken, span = [], set(), None
    for heading, start, end in secs:
        if not heading.startswith("# 📘 "):
            continue
        title = heading[len("# 📘 "):].strip()
        cid = chapter_id(title, taken)
        chapters.append({"id": cid, "title": title})
        files = [m.group(2) for ln in lines[start + 1:end] if ln.startswith("* ")
                 for m in [LINK.search(ln)] if m]
        for pos, file in enumerate(files, start=1):
            mig.page_keys.setdefault(f"wiki/{slug}/{file}", {}).update(chapter=cid, order=pos * 10)
        last = content_end(lines, start, end)
        span = (span[0] if span else start, last)
    return chapters, span


def parse_date(cell: str) -> dict:
    cell = cell.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cell):
        return {"date": cell}
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}); (.+)", cell)
    if m:
        return {"date": m.group(1), "date_note": m.group(2)}
    m = re.fullmatch(r"\? \((.+)\)", cell)
    if m:
        return {"date_note": m.group(1)}
    return {"date_note": cell} if cell not in ("", "?") else {}


def parse_row(row: str) -> tuple[dict, str] | None:
    """A lessons-table row (4 columns, or the legacy 3-column form) → (lesson, lesson-notes file)."""
    cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
    if len(cells) == 4:
        date, title, note_cell, topic_cell = cells
    elif len(cells) == 3:
        date, title, mixed = cells
        note_cell, _, topic_cell = mixed.partition(";")
    else:
        return None
    note = NOTE_LINK.search(note_cell)
    if not note:
        return None
    lesson = parse_date(date) | {"title": title,
                                 "topics": [f for _, f in TOPIC.findall(topic_cell)]}
    if note.group(2):
        lesson["anchor"] = note.group(2)      # the lesson's section on the notes page
    return lesson, note.group(1)


def parse_lessons(lines, secs, slug, mig) -> tuple[int, int] | None:
    sec = next((s for s in secs if s[0].startswith("# 🗓️ Órák")), None)
    if not sec:
        return None
    table = [i for i in range(sec[1], sec[2]) if lines[i].startswith("|")]
    if not table:
        return None
    per_page: dict[str, list] = {}
    for i in table[2:]:
        parsed = parse_row(lines[i])
        if parsed is None:
            mig.warnings.append(f"wiki/{slug}/index.md:{i + 1}: lesson row not understood")
            continue
        lesson, file = parsed
        per_page.setdefault(file, []).append(lesson)
    for file, items in per_page.items():   # the table is newest first; pages keep notebook order
        mig.page_keys.setdefault(f"wiki/{slug}/{file}", {})["lessons"] = list(reversed(items))
    return table[0], table[-1] + 1


def wrap_lines(lines: list[str], spans: list[tuple[str, int, int]]) -> list[str]:
    """Insert marker lines around each (name, start, end) span; empty spans insert a pair."""
    out = list(lines)
    # Insert from the bottom up; at equal starts the longer span goes first, so an
    # empty span placed at another block's start ends up before that block.
    for name, start, end in sorted(spans, key=lambda s: (s[1], s[2]), reverse=True):
        out[end:end] = [markers.CLOSE]
        out[start:start] = [markers.OPEN.format(name=name)]
    return out


def migrate_subject_index(repo: Path, slug: str, description: str, mig: Migration) -> None:
    path = repo / "wiki" / slug / "index.md"
    page = frontmatter.split(path.read_text(encoding="utf-8"))
    lines = page.body.split("\n")
    secs = sections(lines)
    chapters, ch_span = parse_chapters(lines, secs, slug, mig)
    spans = []
    if ch_span:
        spans.append(("chapters", *ch_span))
    lesson_span = parse_lessons(lines, secs, slug, mig)
    if lesson_span:
        spans.append(("lessons", *lesson_span))
    spans += list_spans(lines, secs)
    body = "\n".join(wrap_lines(lines, spans))
    text = frontmatter.set_keys(page_text(page, body), {"description": description,
                                                        "chapters": chapters})
    path.write_text(text, encoding="utf-8")


def page_text(page: frontmatter.Page, body: str) -> str:
    return f"---\n{page.raw_meta}\n---\n{body}" if page.has_fm else body


def list_spans(lines, secs) -> list[tuple[str, int, int]]:
    """The review section (with its trailing separator) and the notes section."""
    review = next((s for s in secs if s[0].startswith("# 🔁 Ismétlés")), None)
    notes = next((s for s in secs if s[0].startswith("# 📝 Jegyzetek")), None)
    spans = []
    if review:
        spans.append(("review", review[1], review[2]))
    elif notes:
        spans.append(("review", notes[1], notes[1]))
    if notes:
        spans.append(("notes", notes[1], content_end(lines, notes[1], notes[2])))
    return spans


def migrate_root(repo: Path, mig: Migration) -> dict[str, str]:
    """Wrap the root subject list; returns {slug: description} in today's order."""
    path = repo / "wiki" / "index.md"
    page = frontmatter.split(path.read_text(encoding="utf-8"))
    lines = page.body.split("\n")
    sec = next((s for s in sections(lines) if s[0].startswith("# 📚")), None)
    found: dict[str, str] = {}
    if sec is None:
        mig.warnings.append("wiki/index.md: no 📚 subject list")
        return found
    rows = [i for i in range(sec[1], sec[2]) if lines[i].startswith("* ")]
    for i in rows:
        m = re.match(r"\* (?:\S+ )?\[[^\]]+\]\(([a-z0-9-]+)/index\.md\) - (.*)$", lines[i])
        if m:
            found[m.group(1)] = m.group(2)
    if rows:
        body = "\n".join(wrap_lines(lines, [("subjects", rows[0], rows[-1] + 1)]))
        path.write_text(page_text(page, body), encoding="utf-8")
    return found


def reorder_subjects_json(repo: Path, order: list[str]) -> None:
    path = repo / "tools" / "subjects.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    subjects = data.get("subjects", {})
    data["subjects"] = {k: subjects[k] for k in order if k in subjects} | {
        k: v for k, v in subjects.items() if k not in order}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_page_keys(repo: Path, mig: Migration) -> None:
    for rel, keys in sorted(mig.page_keys.items()):
        path = repo / rel
        if not path.is_file():
            mig.warnings.append(f"{rel}: listed in an index but missing")
            continue
        text = path.read_text(encoding="utf-8")
        remove = ("lesson_dates",) if "lessons" in keys else ()
        path.write_text(frontmatter.set_keys(text, keys, remove=remove), encoding="utf-8")


def migrate(repo: Path) -> Migration:
    mig = Migration()
    descriptions = migrate_root(repo, mig)
    reorder_subjects_json(repo, list(descriptions))
    for slug in sorted(p.parent.name for p in (repo / "wiki").glob("*/index.md")):
        if slug != "assets":
            migrate_subject_index(repo, slug, descriptions.get(slug, ""), mig)
    undated_lesson_pages(repo, mig)
    apply_page_keys(repo, mig)
    return mig


def undated_lesson_pages(repo: Path, mig: Migration) -> None:
    """Lesson-notes pages missing from every lessons table still switch to `lessons`."""
    for path in sorted((repo / "wiki").glob("*/*.md")):
        rel = path.relative_to(repo).as_posix()
        meta = frontmatter.split(path.read_text(encoding="utf-8")).meta
        if meta.get("type") == "lesson-notes" and "lessons" not in mig.page_keys.get(rel, {}):
            mig.page_keys.setdefault(rel, {})["lessons"] = []
            mig.warnings.append(f"{rel}: in no lessons table; `lessons` left empty")
