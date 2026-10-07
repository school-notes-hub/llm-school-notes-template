"""Lesson-log form and the tool-rendered public source pointer (T-162)."""

import re
from pathlib import Path

from . import markers
from .decisions import valid_date
from .pages import CODE_FENCE, COMMENT, find_links, read_page, resolve

BLOCK = "lesson-sources"
TITLE = "Mit tanultunk ezen az órán"
PLURAL_TITLE = "Mit tanultunk ezeken az órákon"


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


PARTIAL = re.compile(r"^(\d{4}-\d{2}-(?:\d\?|\?\d|\?\?))(?=$|[\s(;,])")


def lesson_label(lesson: dict) -> str:
    """The date of one lesson as the 📎 line shows it: the date the writer recorded from the
    notebook page (`date`), else a partly legible one (`date_note` starting with e.g.
    `2026-09-1?`), else none. Never a folder name: a Drive folder's date is its upload label."""
    value = lesson.get("date")
    if value:
        return str(value).replace("-", ". ") + "."
    partial = PARTIAL.match(str(lesson.get("date_note") or ""))
    if not partial:
        return "dátum nélküli óra"
    return partial[1].replace("-", ". ") + ("" if partial[1].endswith("?") else ".")


def source_line(meta: dict, notebook: bool = True) -> str:
    """`📎 Füzet: <dates>[ · Tanári anyag: <names>]`; a lesson log with no notebook source (only
    a teacher's material) starts with `📎 Óra:` instead of `Füzet:`."""
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
        label = lesson_label(lesson)
        if not dates or dates[-1] != label:
            dates.append(label)
        names = lesson.get("materials", [])
        if not isinstance(names, list):
            raise ValueError("`materials` must be a list of public material names")
        for name in names:  # A badly formed name is a warning; it is still shown as text.
            if isinstance(name, str) and name.strip() and name not in materials:
                materials.append(name)
    line = ("📎 Füzet: " if notebook else "📎 Óra: ") + ", ".join(dates)
    if materials:
        line += " · Tanári anyag: " + "; ".join(plain(" ".join(name.split())) for name in materials)
    return line + "\n"


def plain(text: str) -> str:
    # Names are plain text, never Markdown/HTML supplied by metadata.
    return re.sub(r"([\\`*_{}\[\]<>&])", lambda m: "&#" + str(ord(m[1])) + ";", text)


def after_header(text: str, name: str, body: str) -> str:
    """A tool block is replaced where it is (also an empty one the writer left), or put at
    its fixed place (`markers.fixed_place`)."""
    text = markers.clean_nested_notices(text)
    if name in markers.names(text):
        return markers.replace(text, name, body)
    if not body:
        return text
    return markers.at_fixed_place(text, name, body)


def form_problems(repo: Path, rel: str, body: str, meta: dict, *, read=read_page) -> list[str]:
    """Only structure is mechanical; subject matter and coverage stay with the writer."""
    visible = COMMENT.sub("", CODE_FENCE.sub("", body))
    titles = [TITLE, PLURAL_TITLE] if len(meta.get("lessons", [])) > 1 else [TITLE]
    heading = re.search(r"^# (?:" + "|".join(titles) + r")\s*$", visible, re.M)
    if not heading:
        return [f"lesson log needs {' or '.join(repr('# ' + title) for title in titles)} with 3-8 top-level `*`/`-` bullets, "
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
        targets = [m["target"].strip("<>") for m in find_links(point) if not m["img"]]
        if not any(_topic_section(repo, rel, target, topics, read=read) for target in targets):
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


def _topic_section(repo: Path, rel: str, target: str, topics: set[str], *, read=read_page) -> bool:
    file, sep, anchor = target.partition("#")
    resolved = resolve(rel, file)
    if not sep or not anchor or resolved not in topics or resolved is None:
        return False
    try:
        return read(repo, resolved).meta.get("type") == "topic"
    except FileNotFoundError:
        return False
