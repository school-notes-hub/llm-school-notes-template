"""Lesson-log form and the tool-rendered public source pointer (T-162)."""

import re
from pathlib import Path

from . import frontmatter, markers
from .decisions import valid_date
from .pages import CODE_FENCE, COMMENT, LINK, read_page, resolve

BLOCK = "lesson-sources"
TITLE = "Mit tanultunk ezen az órán"


def is_lesson(rel: str, meta: dict) -> bool:
    return meta.get("type") == "lesson-notes" or rel.endswith("-jegyzet.md")


def material_problems(lesson: dict) -> list[str]:
    materials = lesson.get("materials", [])
    if not isinstance(materials, list):
        return ["`materials` must be a list of public material names"]
    out = []
    for name in materials:
        if not isinstance(name, str) or not re.fullmatch(r"\S(?:[^\r\n]*\S)? \([^()\r\n]+\)", name) \
                or name != name.strip() or any(ord(c) < 32 for c in name):
            out.append("each material needs a single-line public name and kind: Name (kind)")
        elif re.search(r"(?:^|[/\\\s])\S+\.(?:pdf|pptx?|jpe?g|png|heic|docx?|xlsx?|odp|ods|key)"
                       r"(?:\s|$)", name, re.I) \
                or re.match(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9-]+ \(", name):
            out.append("material names must not be technical file names")
    return out


def source_line(meta: dict) -> str:
    dates, materials = [], []
    lessons = meta.get("lessons")
    if not isinstance(lessons, list):
        raise ValueError("`lessons` must be a list")
    for lesson in lessons:
        if not isinstance(lesson, dict):
            raise ValueError("each lesson must be a mapping")
        if not isinstance(lesson.get("topics", []), list):
            raise ValueError("lesson `topics` must be a list")
        value = lesson.get("date")
        if value is not None and not valid_date(value):
            raise ValueError("lesson date must be a real YYYY-MM-DD date")
        label = str(value).replace("-", ". ") + "." if value else "dátum nélküli óra"
        if not dates or dates[-1] != label:
            dates.append(label)
        problems = material_problems(lesson)
        if problems:
            raise ValueError("; ".join(problems))
        for name in lesson.get("materials", []):
            if name not in materials:
                materials.append(name)
    line = "📎 Füzet: " + ", ".join(dates)
    if materials:
        line += " · Tanári anyag: " + "; ".join(_plain(name) for name in materials)
    return line + "\n"


def _plain(text: str) -> str:
    # Names are plain text, never Markdown/HTML supplied by metadata.
    return re.sub(r"([\\`*_{}\[\]<>&])", lambda m: "&#" + str(ord(m[1])) + ";", text)


def after_header(text: str, name: str, body: str) -> str:
    """Insert once, after the leading banner (or title/placeholder while it is pending)."""
    text = markers.clean_nested_notices(text)
    if name in markers.names(text):
        return markers.replace(text, name, body)
    if not body:
        return text
    cut = header_end(text)
    return text[:cut] + "\n" + markers.wrap(name, body) + "\n" + text[cut:]


def header_end(text: str) -> int:
    """After the leading banner, its description and any enclosing generated block."""
    page = frontmatter.split(text)
    # Hide multiline comments without changing offsets; retain pending image markers.
    visible = COMMENT.sub(lambda m: m[0] if re.match(r"<!-- (?:image|figure):", m[0])
                          else re.sub(r"[^\n]", " ", m[0]), page.body)
    offset, title_end = 0, 0
    for line in visible.splitlines(keepends=True):
        offset += len(line)
        if re.match(r"\s*(?:!\[|<img\b|<!-- (?:image|figure):)", line):
            break
        if re.match(r"^# ", line):
            title_end = offset
        elif line.strip() and not line.startswith("<!--"):
            offset = title_end
            break
    else:
        offset = title_end
    cut = len(text) - len(page.body) + offset
    description = re.match(r"\s*<!-- image-description\b.*?-->(?:\n|$)", text[cut:], re.S)
    if description:
        cut += description.end()
    return markers.outside(text, cut)


def form_problems(repo: Path, rel: str, body: str, meta: dict) -> list[str]:
    """Only structure is mechanical; subject matter and coverage stay with the writer."""
    visible = COMMENT.sub("", CODE_FENCE.sub("", body))
    heading = re.search(r"^# " + TITLE + r"\s*$", visible, re.M)
    if not heading:
        return [f"lesson log needs '# {TITLE}' with 3-8 top-level `*`/`-` bullets, "
                "each linking `<topic>.md#<section>`"]
    section = re.split(r"^# ", visible[heading.end():], maxsplit=1, flags=re.M)[0]
    points = _learning_points(section)
    out = []
    if not 3 <= len(points) <= 8:
        out.append("lesson log needs 3-8 top-level `*`/`-` bullets, each linking `<topic>.md#<section>`")
    topics = {resolve(rel, str(t).split("#", 1)[0]) for lesson in meta.get("lessons", [])
              if isinstance(lesson, dict) and isinstance(lesson.get("topics", []), list)
              for t in lesson.get("topics", [])}
    for point in points:
        targets = [m["target"].strip("<>") for m in LINK.finditer(point) if not m["img"]]
        if not any(_topic_section(repo, rel, target, topics) for target in targets):
            out.append("each learning point must link a listed topic page's teaching section")
    return out


def _learning_points(section: str) -> list[str]:
    points, indent = [], None
    for line in section.splitlines():
        bullet = re.match(r"^( {0,3})[*+-] (.*)", line)
        if bullet and (indent is None or len(bullet[1]) <= indent):
            indent = len(bullet[1]) if indent is None else indent
            points.append(bullet[2])
        elif points and (not line.strip() or len(line) - len(line.lstrip(" ")) > indent):
            points[-1] += "\n" + line
    return points


def _topic_section(repo: Path, rel: str, target: str, topics: set[str]) -> bool:
    file, sep, anchor = target.partition("#")
    resolved = resolve(rel, file)
    if not sep or not anchor or resolved not in topics or resolved is None:
        return False
    try:
        return read_page(repo, resolved).meta.get("type") == "topic"
    except FileNotFoundError:
        return False
