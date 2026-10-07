"""The web footnote (Sources and evidence, *Check a fact on the web*): a footnote that holds a
web URL is kept whole on the public site (study-site `publicMarkdown`), so its form is fixed.

The footnote is read as the renderer reads it: with its indented continuation paragraphs, with
reference-style links resolved through the page's link definitions, and with balanced
parentheses inside a link's URL. Accepted, and nothing else:

  [^id]: Title. https://… (ellenőrizve: YYYY-MM-DD).
  [^id]: [Title](https://…) (ellenőrizve: YYYY-MM-DD).      (a publisher or author prefix may
                                                            stand before the link)

The machine decides only what it can decide reliably: the structure, and in the title's
rendered text a number with a locator (page, slide, figure, exercise, chapter, annex, table,
section, paragraph, `§`, `(N)`, a page id) or a word of the private context (textbook,
notebook, teacher, lesson, slide deck, notes). Whether a title names only the web source is
the reviewer's judgement (lektor role text)."""

import html
import re
from datetime import date

from .pages import CODE_FENCE, COMMENT, LABEL

FOOTNOTE_START = re.compile(r"^\[\^([^\]]+)\]:[ \t]?(.*)$")
DEFINITION = re.compile(r"^ {0,3}\[(?!\^)([^\]]+)\]:[ \t]*<?([^\s>]+)>?.*$", re.M)
WEB = re.compile(r"https?://[^\s)>\]\"']+", re.I)
# A link's URL may hold balanced parentheses (`…/Kandela_(mértékegység)`), as in CommonMark.
MD_LINK = re.compile(r"\[(" + LABEL + r")\]\(\s*<?((?:[^()\s<>]|\([^()\s]*\))+)>?((?:\s+[^)]*)?)\)")
REF_LINK = re.compile(r"\[(" + LABEL + r")\]\[([^\]]*)\]|\[([^\[\]^]+)\](?![(\[:])")
HTML_HREF = re.compile(r"(?:href|src)\s*=\s*[\"']?([^\"'\s>]+)", re.I)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
FILE_EXT = re.compile(r"\b[\w.-]+\.(?:jpe?g|png|webp|gif|heic|tiff?|pdf|pptx?|docx?|xlsx?|odp|ods|md|svg)\b", re.I)
PAGE_ID = re.compile(r"\bp\d{4}\b", re.I)
PRIVATE = re.compile(r"(?<![\w/.-])(?:\.\./)*(?:sources|references)/", re.I)
RETRIEVAL_WORDS = re.compile(r"(?i)\b(?:ellenőrizve|megtekintve|letöltve|lekérve|hozzáférés|elérés|retrieved|accessed)\b")
MESSAGE = ("expected exactly `[^id]: Title. https://… (ellenőrizve: YYYY-MM-DD).` or "
           "`[^id]: [Title](https://…) (ellenőrizve: YYYY-MM-DD).` and nothing else; put a private "
           "source pointer in a footnote of its own")

RETRIEVED = re.compile(r" \(ellenőrizve: (\d{4}-\d{2}-\d{2})\)\.")
BARE_URL = re.compile(r"<?(https?://\S+?)>?(?= \(|\s|$)", re.I)
LOCATOR = (r"(?:oldal\w*|old\b|old\.|o\.|dia\w*|lap\w*|kép\w*|ábr\w*|feladat\w*|fejezet\w*|melléklet\w*"
           r"|táblázat\w*|szakasz\w*|bekezdés\w*)")
# A number (digits, a range, or a Roman numeral) right before a locator stem, `§`, a `(N)`
# paragraph mark, a page id.
NUMBERED_LOCATOR = re.compile(r"(?i)(?<!\w)(?:\d+(?:\s*[-–]\s*\d+)?\.?\s*|[IVXLC]+(?:\.\s*|\s+))" + LOCATOR
                              + r"|§|\(\d{1,3}[a-z]?\)|(?<!\w)p\d{4}(?!\w)")
# A word of the private context, at the start of a word (any inflection), never inside a
# longer word (`Napóra`, `munkafüzet` stay).
PRIVATE_WORD = re.compile(r"(?i)(?<!\w)(?:tk\.|tankönyv\w*|füzet\w*|tanár\w*|órá\w*|óra(?!\w)|diasor\w*|jegyzet\w*)")


def visible(text: str) -> str:
    """The page without fenced code and HTML comments (same length: line numbers stay)."""
    blank_out = lambda m: re.sub(r"[^\n]", " ", m[0])     # noqa: E731
    return COMMENT.sub(blank_out, CODE_FENCE.sub(blank_out, text))


def definitions(text: str) -> dict[str, str]:
    """Reference link definitions `[id]: url` of a page, by lower-case id."""
    return {m[1].strip().lower(): m[2] for m in DEFINITION.finditer(visible(text))}


def footnotes(text: str) -> list[tuple[str, int, str]]:
    """(id, line, body) of every footnote definition: its first line and every following
    indented line, blank lines between them included (a continuation paragraph)."""
    lines = visible(text).split("\n")
    out, i = [], 0
    while i < len(lines):
        m = FOOTNOTE_START.match(lines[i])
        if not m:
            i += 1
            continue
        body, j = [m[2]], i + 1
        while j < len(lines):
            if lines[j].startswith(("  ", "\t")) and lines[j].strip():
                body.append(lines[j])
                j += 1
            elif not lines[j].strip() and j + 1 < len(lines) and lines[j + 1].startswith(("  ", "\t")) \
                    and lines[j + 1].strip():
                body.append("")
                j += 1
            else:
                break
        out.append((m[1], i + 1, "\n".join(body)))
        i = j
    return out


def link_targets(body: str, defs: dict[str, str]) -> tuple[list[str], str]:
    """(every link target of a text – inline, reference-style, raw HTML, bare web URL – and the
    text with link targets removed, link texts kept)."""
    targets = []

    def inline(m):
        targets.append(m[2])
        return " " + m[1] + " "

    def reference(m):
        # [text][label], [text][] (collapsed) or [label] (shortcut); unknown labels stay text
        text = m[1] if m[1] is not None else m[3]
        label = (m[2] if m[2] else text if m[1] is not None else m[3]).strip().lower()
        if label in defs:
            targets.append(defs[label])
            return " " + text + " "
        return m[0]
    rest = MD_LINK.sub(inline, body)
    rest = REF_LINK.sub(reference, rest)
    targets += HTML_HREF.findall(rest)
    rest = HTML_HREF.sub(" ", rest)
    targets += WEB.findall(rest)
    return targets, WEB.sub(" ", rest)


def rendered(text: str) -> str:
    """A title's text as the reader sees it: no emphasis, code or strike marks, no HTML tags,
    escapes and entities resolved (`**oldal**` is `oldal`)."""
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\\(.)", r"\1", re.sub(r"(?<!\\)[*_~`]+", "", text))
    return " ".join(html.unescape(text).split())


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return f"'{text[:60]}…'" if len(text) > 60 else f"'{text}'"


def title_problems(title: str) -> list[str]:
    """A number with a locator and a private-context word in the title's rendered text."""
    shown, out = rendered(title), []
    for pattern, what in ((NUMBERED_LOCATOR, "a page, slide, figure, exercise or section number"),
                          (PRIVATE_WORD, "a word of the private context")):
        m = pattern.search(shown)
        if m:
            out.append(f"{what} in the title: {_quote(shown[max(0, m.start() - 15):m.end() + 15])}")
    return out


def _tail(after: str, what: str) -> list[str]:
    """`after` (what follows the URL or the link) must be exactly ` (ellenőrizve: YYYY-MM-DD).`."""
    m = RETRIEVED.search(after)
    if not m:
        return [f"after the {what} not exactly ' (ellenőrizve: YYYY-MM-DD).': {_quote(after)}"]
    out = []
    if m.start():
        out.append(f"text between the {what} and the date: {_quote(after[:m.start()])}")
    if after[m.end():].strip():
        out.append(f"text after the retrieval date: {_quote(after[m.end():])}")
    try:
        date.fromisoformat(m[1])
    except ValueError:
        out.append(f"the retrieval date {m[1]} is not a real date")
    return out


def form_problems(body: str) -> list[str]:
    """What a web footnote body has besides one of the two forms (empty: exactly the form)."""
    first, *rest = body.split("\n")
    out = ["a continuation paragraph"] if any(line.strip() for line in rest) else []
    line = first.strip()
    link = next((m for m in MD_LINK.finditer(line) if WEB.match(m[2])), None)
    bare = BARE_URL.search(line)
    if link:
        title, url = line[:link.start()] + " " + link[1], link[2]       # a prefix is part of the title
        if link[3].strip() or "<" in link[0][len(link[1]) + 2:]:
            out.append("a link with angle brackets or a link title")
        out += _tail(line[link.end():], "link")
    elif bare:
        url, before, after = bare[1], line[:bare.start()], line[bare.end():]
        if bare[0].startswith("<"):
            out.append("the URL in angle brackets")
        title = before.rstrip()
        if title and not (before.endswith(" ") and title[-1] in ".?!"):
            out.append(f"the title does not end with '. ' before the URL: {_quote(title[-30:])}")
        out += _tail(after, "URL")
    else:
        return out + ["the URL is not written in the footnote (a reference-style or HTML link)"]
    if not url.lower().startswith("https://"):
        out.append("not an https URL")
    return out + title_problems(title)


def problems(body: str, defs: dict[str, str] | None = None) -> list[str]:
    """What is wrong with one footnote body that holds a web link (empty: fine or no web link)."""
    targets, rest = link_targets(body, defs or {})
    if not any(WEB.match(t) for t in targets):
        return []
    out = []
    if len(targets) != 1:
        out.append("more than one link, or a link that is not a web URL")
    if PRIVATE.search(body):
        out.append("a sources/ or references/ path")
    if FILE_EXT.search(rest):
        out.append("a file name")
    if PAGE_ID.search(rest):
        out.append("a page or photo id")
    if not ISO_DATE.search(rest):
        out.append("no retrieval date (YYYY-MM-DD)")
    if not re.search(r"[^\W\d_]", RETRIEVAL_WORDS.sub(" ", ISO_DATE.sub(" ", rest))):
        out.append("no title")
    return out + [p for p in form_problems(body) if p not in out]


def check(rel: str, text: str) -> list[dict]:
    """Page-check items `{file, line, message, severity}`, one per bad web footnote."""
    defs = definitions(text)
    out = []
    for fid, line, body in footnotes(text):
        found = problems(body, defs)
        if found:
            out.append({"file": rel, "line": line, "message": f"[^{fid}]: {'; '.join(found)} – {MESSAGE}",
                        "severity": "error"})
    return out
