"""Warning-only source references on changed public lines (repair plan 8.2)."""

import difflib
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter

import yaml

from . import decisions, frontmatter, markers
from .check import PATTERNS_FILE

MESSAGE = ('source reference in visible text: "{match}". If the sentence teaches the subject, '
           'rewrite it so that it is understandable without the source (the location may '
           'additionally go into a private footnote). If it is an allowed form (textbook line, '
           'lesson-log source line, open question) or a false match, leave it. '
           'Warning only; it never blocks.')
PATTERNS = tuple(re.compile(p, re.I) for p in
                 json.loads(PATTERNS_FILE.read_text())["source_refs"])
COMMENT = re.compile(r"<!--.*?-->", re.S)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FOOTNOTE = re.compile(r"^ {0,3}\[\^[^\]]+\]:")


def blank(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def normalized(line: str) -> str:
    return " ".join(unicodedata.normalize("NFC", line).split())


def line_hash(line: str) -> str:
    return hashlib.sha256(normalized(line).encode()).hexdigest()


def changed_lines(old: str, new: str) -> set[int]:
    diff = difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False)
    return {n + 1 for tag, _, _, first, last in diff.get_opcodes() if tag != "equal"
            for n in range(first, last)}


def _frontmatter(text: str) -> str:
    match = re.match(r"\A---\n(.*?\n)---(?:\n|$)", text, re.S)
    if not match:
        return text
    masked = list(blank(match[0]))
    try:
        node = yaml.compose(match[1], Loader=frontmatter.Loader)
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if key.value in ("title", "description"):
                    start, end = value.start_mark.index + 4, value.end_mark.index + 4
                    masked[start:end] = text[start:end]
    except yaml.YAMLError:
        pass  # YAML errors belong to the structural check.
    return "".join(masked) + text[match.end():]


def visible_markdown(text: str) -> list[str]:
    fm = re.match(r"\A---\n.*?\n---(?:\n|$)", text, re.S)
    meta_lines = fm[0].count("\n") if fm else 0
    text = _frontmatter(text)
    text = markers.BLOCK.sub(lambda m: blank(m[0]) if m["name"] == "lesson-sources" else m[0], text)
    text = COMMENT.sub(lambda m: blank(m[0]), text)
    out, fence, language, question_level, footnote = [], None, "", 0, False
    in_list = False
    for n, line in enumerate(text.splitlines(), 1):
        delimiter = FENCE.match(line)
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
                out.append("")
            else:
                out.append(line.split("%%", 1)[0] if language == "mermaid" and not question_level else "")
            continue
        if delimiter:
            fence, language = delimiter[1], delimiter[2].strip().lower()
            out.append("")
            continue
        heading = decisions.HEADING.match(line)
        if heading and question_level and len(heading[1]) <= question_level:
            question_level = 0
        if heading and decisions.QUESTION_HEADING.fullmatch(heading[2]):
            question_level = len(heading[1])
        if FOOTNOTE.match(line):
            footnote = True
        elif line.strip() and not line.startswith(("    ", "\t")):
            footnote = False
        if question_level or footnote or re.match(r"^\s*(?:>\s*)?🔖\s*(?:Tankönyv|Textbook):", line):
            out.append("")
            continue
        if n > meta_lines:
            if decisions.LIST_ITEM.match(line):
                in_list = True
            elif line.strip() and not line[0].isspace():
                in_list = False
            if not in_list and line.startswith(("    ", "\t")):
                out.append("")
                continue
        # Keep labels/alt/captions, not link destinations or HTML attributes.
        line = re.sub(r"<img\b[^>]*>", _image_alt, line, flags=re.I)
        line = re.sub(r"(!?\[[^\]]*\])\([^)]*\)", r"\1", line)
        line = re.sub(r"<[^>]+>", "", line)
        out.append(html.unescape(line))
    return out


def _image_alt(match) -> str:
    alt = re.search(r"\balt\s*=\s*([\"'])(.*?)\1", match[0], re.I)
    return alt[2] if alt else ""


def visible_svg(text: str) -> list[str]:
    """Keep text/title/desc contents, with original line positions (including tspans)."""
    text = COMMENT.sub(lambda m: blank(m[0]), text)
    masked = list(blank(text))
    for m in re.finditer(r"<(?:[\w-]+:)?(text|title|desc)\b[^>]*>(.*?)</(?:[\w-]+:)?\1\s*>", text, re.S):
        masked[m.start(2):m.end(2)] = m[2]
    visible = re.sub(r"<[^>]+>", lambda m: blank(m[0]), "".join(masked))
    return html.unescape(visible).splitlines()


def scan(rel: str, text: str, old: str = "", *, full: bool = False) -> list[dict]:
    if rel == "wiki/log.md" or not rel.startswith("wiki/"):
        return []
    if rel.endswith(".svg"):
        visible = visible_svg(text)
    elif rel.endswith(".md") and not rel.startswith("wiki/assets/"):
        visible = visible_markdown(text)
    else:
        return []
    changed = set(range(1, len(visible) + 1)) if full else changed_lines(old, text)
    counts, out = Counter(), []
    for n, (raw, public) in enumerate(zip(text.splitlines(), visible), 1):
        digest = line_hash(raw)
        counts[digest] += 1  # Across the whole file, not just changed or matching lines.
        matches = sorted({m[0] for p in PATTERNS for m in p.finditer(public)})
        if n not in changed or not matches:
            continue
        occurrence = counts[digest]
        out.append({"file": rel, "line": n, "severity": "warning", "kind": "source_ref",
                    "id": f"{rel}:{digest}:{occurrence}", "line_hash": digest,
                    "occurrence": occurrence, "message": MESSAGE.format(match='; '.join(matches))})
    return out
