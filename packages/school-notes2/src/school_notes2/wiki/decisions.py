"""Open-question anchors and private, human-confirmed decisions (repair plan 7.5)."""

import re
from datetime import date
from pathlib import Path

import yaml

from . import frontmatter, markers
from .pages import CODE_FENCE, PageError, read_page, wiki_pages

ID = re.compile(r"[a-z0-9-]+\Z")
ANCHOR = re.compile(r"^ {0,3}<!--\s*q:\s*(.*?)\s*-->\s*$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
QUESTION_HEADING = re.compile(r"^(?:[^\w]*)(?:Nyitott kérdések|Open questions)$", re.I)
LIST_ITEM = re.compile(r"^ {0,3}(\d+[.)]|[*+-])\s+\S")
OVERVIEW = "docs/review/dontesek.md"


class DecisionError(PageError):
    pass


def valid_date(value) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value))) and bool(date.fromisoformat(str(value)))
    except ValueError:
        return False


def decision_problems(meta: dict) -> list[str]:
    entries = meta.get("decisions", [])
    if not isinstance(entries, list):
        return ["`decisions` must be a list"]
    out, ids = [], []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "claim", "answer", "by", "on"}:
            out.append("each decision needs exactly id, claim, answer, by, on")
            continue
        key = entry["id"]
        if not isinstance(key, str) or not ID.fullmatch(key):
            out.append("decision id must contain only [a-z0-9-]")
        else:
            ids.append(key)
        if any(not isinstance(entry[k], str) or not entry[k].strip() for k in ("claim", "answer")):
            out.append("decision claim and answer must be nonempty strings")
        if entry["by"] not in ("owner", "student", "family", "teacher"):
            out.append("decision by must be owner, student, family or teacher")
        if not valid_date(entry["on"]):
            out.append("decision on must be a real YYYY-MM-DD date")
    if ids != sorted(set(ids)):
        out.append("decision ids must be unique and sorted")
    return out


def _question_sections(lines: list[str]) -> list[list[tuple[int, str]]]:
    sections, current, level = [], None, 0
    for n, line in enumerate(lines, 1):
        heading = HEADING.match(line)
        if heading and len(heading[1]) <= level:
            current = None
        if heading and QUESTION_HEADING.fullmatch(heading[2]):
            current, level = [(n, line)], len(heading[1])
            sections.append(current)
        elif current is not None:
            current.append((n, line))
    return sections


def _question_items(section: list[tuple[int, str]]) -> list[tuple[int, str, int | None]]:
    items, previous, indent = [], None, None
    for n, line in section[1:]:
        entry = LIST_ITEM.match(line)
        if entry:
            leading = len(line) - len(line.lstrip(" "))
            if indent is None:
                indent = leading
            if leading <= indent:
                anchor = previous[0] if previous and ANCHOR.match(previous[1]) else None
                items.append((n, entry[1], anchor))
        if line.strip():
            previous = n, line
    return items


def question_problems(body: str, meta: dict) -> list[tuple[int, str]]:
    """Validate top-level question items; nested explanation lists are not new questions."""
    body = CODE_FENCE.sub(lambda m: "\n" * m.group().count("\n"), body)
    lines = body.splitlines()
    out, seen, used = [], set(), set()
    entries = meta.get("decisions", [])
    decision_ids = {d.get("id") for d in entries
                    if isinstance(d, dict) and isinstance(d.get("id"), str)} \
        if isinstance(entries, list) else set()
    anchors = [(n, m[1]) for n, line in enumerate(lines, 1) if (m := ANCHOR.match(line))]
    for n, key in anchors:
        if not ID.fullmatch(key):
            out.append((n, "question id must contain only [a-z0-9-]"))
        if key in seen:
            out.append((n, f"duplicate question id {key!r}"))
        if key in decision_ids:
            out.append((n, f"{key!r} is both an open question and a decision"))
        seen.add(key)
    for section in _question_sections(lines):
        items = _question_items(section)
        if not items:
            out.append((section[0][0], "empty open-questions section"))
        for count, (n, marker, anchor) in enumerate(items, 1):
            if marker != f"{count}.":
                out.append((n, "open questions need consecutive numbered items (1., 2., ...)"))
            if anchor is None:
                out.append((n, "open question needs a preceding <!-- q: page-key --> anchor"))
            else:
                used.add(anchor)
    out += [(n, "question anchor must precede an open-question item")
            for n, _ in anchors if n not in used]
    return sorted(out)


def snapshot(data: bytes | None) -> tuple:
    """Raw YAML node slices AND their values: formatting and alias changes both count.

    Node marks support quoted keys and flow mappings, unlike line-based key matching.
    Keep original newlines; the cron guard runs before any LF auto-fix.
    """
    text = (data or b"").decode("utf-8")
    match = re.match(r"\A---\r?\n(.*?\r?\n)---(?:\r?\n|$)", text, re.S)
    if not match:
        return (), None
    raw = match[1]
    node = yaml.compose(raw, Loader=frontmatter.Loader)
    if not isinstance(node, yaml.MappingNode):
        return (), None
    spans = []
    for i, (key, value) in enumerate(node.value):
        if key.value != "decisions":
            continue
        end = value.end_mark.index if node.flow_style else (
            node.value[i + 1][0].start_mark.index if i + 1 < len(node.value) else len(raw))
        spans.append(raw[key.start_mark.index:end].encode("utf-8"))
    meta = yaml.load(raw, Loader=frontmatter.Loader) or {}
    return tuple(spans), meta.get("decisions")


def overview(repo: Path, skip=()) -> str:
    lines = ["# Megerősített döntések", ""]
    for rel in sorted(set(wiki_pages(repo)) - set(skip)):
        meta = read_page(repo, rel).meta
        problems = decision_problems(meta)
        if problems:
            raise DecisionError(rel, problems)
        for entry in sorted(meta.get("decisions", []), key=lambda d: d["id"]):
            lines += [f"## {rel} - {entry['id']}", "",
                      f"* Oldal: [{rel}](../../{rel})",
                      f"* Állítás: {_line(entry['claim'])}", f"* Válasz: {_line(entry['answer'])}",
                      f"* Ki: {entry['by']}", f"* Mikor: {entry['on']}", ""]
    return markers.wrap("decisions", "\n".join(lines))


def _line(text: str) -> str:
    return " ".join(text.splitlines())
