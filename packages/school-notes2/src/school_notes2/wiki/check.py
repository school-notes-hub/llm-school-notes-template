"""The mechanical `check` of plan 5.4/5 on markdown files.

Preserves author bytes and reports defects as
check.json items `{file, line, message, severity}`; errors send the run back to the
writer, warnings do not.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import yaml

from ..state import safefs
from . import decisions, drafts, frontmatter, lesson_log, markers, web_footnote
from .pages import CODE_FENCE, COMMENT, INLINE_CODE, LABEL, blank, find_links, links, resolve

TYPES_WITH_CHAPTER = ("topic", "chapter-summary")
LESSON_SUFFIX = "-jegyzet.md"
KNOWN_TYPES = ("topic", "chapter-summary", "lesson-notes", "review", "source-summary",
               "concept", "entity", "question")
# The release's last gate (check-public.py) and this check share one pattern file. The wiki
# check uses only the real secret patterns; machine paths are judged by the output gate (#15).
PATTERNS_FILE = Path(__file__).resolve().parents[4] / "study-site" / "public-patterns.json"


def load_patterns(path: Path = PATTERNS_FILE) -> tuple[str, ...]:
    return tuple(json.loads(path.read_text(encoding="utf-8"))["secrets"])


SECRET_PATTERNS = load_patterns()
SECRET_MESSAGE = "forbidden secret pattern"
# Blocking problems make the writer's output unusable (a secret, broken frontmatter or
# block markers that the tool cannot process); every other error is fixed by the writer
# or becomes an item for the next run.
BLOCKING = "blocking"
CONFLICT = re.compile(r"^(<<<<<<<|>>>>>>>)( |$)", re.M)
TAG = re.compile(r"^(?=.*[a-z])[a-z0-9-]+(/[a-z0-9-]+)*$")
FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
# One 🔖 textbook pointer: up to the next 🔖, tag or line end, or a middle dot that starts the
# next emoji label (`· 🗓️ Óra: …`); a middle dot inside the pointer (`A reformáció · 45-47.
# oldal`) does not end it (fix-52b).
TEXTBOOK = re.compile(r"🔖((?:(?!·\s*[\u2600-\u27bf\U0001f300-\U0001faff])[^🔖<\n])*)")
# A lesson or page number: any digit, or a Roman numeral with "fejezet"/"lecke" (`III. fejezet`,
# `lecke IV`). Machine signs only, the words are never interpreted.
TEXTBOOK_NUMBER = re.compile(r"\d|\b[IVXLC]+\.?\s+(?i:fejezet|lecke)|(?i:fejezet|lecke)\s+[IVXLC]+\b")
TEXTBOOK_MESSAGE = ("the 🔖 textbook line names no lesson or page number: give the identified lesson and "
                    "page, or state that the learner's textbook (named by its grade) does not cover the topic, "
                    "or leave the line out")


def item(file: str, line: int | None, message: str, severity: str = "error", kind: str | None = None) -> dict:
    found = {"file": file, "line": line, "message": message, "severity": severity}
    return {**found, "kind": kind} if kind else found


def autofix(repo: Path, rel: str) -> bool:
    """Compatibility entry point: checking never rewrites author bytes."""
    return False


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_secrets(rel: str, text: str) -> list[dict]:
    """Conflict markers and secrets: every file the writer may change."""
    out = []
    for m in CONFLICT.finditer(text):
        out.append(item(rel, line_of(text, m.start()), "unresolved conflict marker", kind=BLOCKING))
    for pattern in SECRET_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            out.append(item(rel, line_of(text, m.start()), f"{SECRET_MESSAGE} {pattern!r}", kind=BLOCKING))
    return out


def check_text(rel: str, text: str) -> list[dict]:
    """Wiki-page rules: the above plus block markers and formulas."""
    out = check_secrets(rel, text)
    try:
        markers.check(text)
    except markers.MarkerError as exc:
        out.append(item(rel, None, str(exc), kind=BLOCKING))
    out += check_formulas(rel, text)
    out += check_ids(rel, text)
    out += check_web_footnotes(rel, text)
    out += check_public_view(rel, text)
    return out


# The web footnote's form lives in `web_footnote.py`; the public view below reads footnotes the
# same way.
check_web_footnotes = web_footnote.check
web_footnote_problems = web_footnote.problems
_visible, definitions, footnotes, link_targets = (web_footnote.visible, web_footnote.definitions,
                                                  web_footnote.footnotes, web_footnote.link_targets)
WEB, DEFINITION = web_footnote.WEB, web_footnote.DEFINITION


VISIBLE_PATTERNS = tuple(re.compile(p, re.I) for p in
                         json.loads(PATTERNS_FILE.read_text(encoding="utf-8")).get("visible_text", []))


def public_text(text: str) -> str:
    """What the public view shows of a page, as text (same line count): no frontmatter but its
    `title` and `description`, no HTML comment or code, no footnote without a web link (the
    renderer drops those), no link definition; links keep their words, never their targets;
    web URLs left out (a public address may contain any path)."""
    page = frontmatter.split(text) if text.startswith("---") else None
    head_lines = (len(page.raw_meta.split("\n")) + 2) if page and page.has_fm else 0
    lines = _visible(text).split("\n")
    defs = definitions(text)
    for fid, line, body in footnotes(text):
        targets, _ = link_targets(body, defs)
        if not any(WEB.match(t) for t in targets):
            for n in range(line - 1, line - 1 + len(body.split("\n"))):
                lines[n] = ""
    for n in range(head_lines):
        lines[n] = ""
    if page and page.has_fm:
        lines[0] = f"{page.meta.get('title', '')} {page.meta.get('description', '')}"
    body = DEFINITION.sub("", "\n".join(lines))
    return link_targets(body, defs)[1]


def check_public_view(rel: str, text: str) -> list[dict]:
    """The output gate's `visible_text` patterns on the public view of the page, so a page that
    passes `sn done` never fails only at publish. Only published pages (not the log, not asset
    READMEs: `pages.wiki_pages`)."""
    if rel == "wiki/log.md" or rel.startswith("wiki/assets/") or not rel.startswith("wiki/"):
        return []
    try:
        shown = public_text(text)
    except (ValueError, yaml.YAMLError):
        return []                   # unreadable frontmatter: reported on its own
    return [item(rel, line_of(shown, m.start()), f"a private name would be published: {m[0]!r} "
                 "(a sources/ or references/ path or a page or photo id in visible text)")
            for p in VISIBLE_PATTERNS for m in [p.search(shown)] if m]


def check_ids(rel: str, text: str) -> list[dict]:
    """An id the page already has (a heading's, or another link target's) fails the release's
    browser check; the renderer's own slug rule finds it while the writer can still fix it."""
    from . import heading_ids
    return [item(rel, line, f'the link target <a id="{value}"></a> repeats the id of {what}; '
                            "the published page would have this id twice: remove this anchor "
                            "(the heading already gives the same link target) or rename it")
            for line, value, what in heading_ids.duplicates(text)]


# A reference image `![alt][ref]` / `![alt][]` whose label is defined; an undefined one is text.
REF_IMAGE = re.compile(r"!\[(?P<text>" + LABEL + r")\]\[(?P<ref>[^\[\]\n]*)\]")
LATEX = re.compile(r"\\[A-Za-z]+|[\^_](?:\{|[A-Za-z0-9])")
OPENER = {"[": ("]", "\\[…\\]", "$$…$$"), "(": (")", "\\(…\\)", "$…$")}


def alt_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of every confirmed image alt text: an inline image with a complete destination, or
    a reference image whose label is defined on the page (the shared `pages.LABEL`)."""
    defs = definitions(text)
    spans = [m.span("text") for m in find_links(text) if m["img"]]
    for m in find_links(text, REF_IMAGE):
        label = (m["ref"] or m["text"]).strip().lower()
        if label in defs:
            spans.append(m.span("text"))
    return spans


def check_formulas(rel: str, text: str) -> list[dict]:
    """`$$` display math must pair up (the build compiles the formulas themselves). Image alt text
    is never rendered as math, so it is masked (spaces, newlines kept), never deleted. Neither
    renderer reads `\\[…\\]` or `\\(…\\)` as math (Markdown makes them plain brackets): LaTeX
    between them is a warning that names the form that renders."""
    body = CODE_FENCE.sub(blank, text)
    body = INLINE_CODE.sub(blank, body)
    for start, end in alt_spans(body):
        body = body[:start] + re.sub(r"[^\n]", " ", body[start:end]) + body[end:]
    if body.count("$$") % 2:
        return [item(rel, None, "unbalanced $$ display-math delimiter")]
    out = []
    escapes = list(re.finditer(r"\\(.)", body, re.S))
    for i, m in enumerate(escapes):
        if m[1] not in OPENER:
            continue
        closer, shown, use = OPENER[m[1]]
        stop = re.search(r"\n[ \t]*\n", body[m.end():])
        limit = m.end() + stop.start() if stop else len(body)
        close = next((e for e in escapes[i + 1:] if e.start() < limit and e[1] == closer), None)
        content = body[m.end():close.start() if close else limit]
        if LATEX.search(content):
            out.append(item(rel, line_of(body, m.start()), f"{shown} does not render as math, use {use}",
                            severity="warning"))
    return out


def check_links(repo: Path, rel: str, text: str, *, fs=safefs) -> list[dict]:
    out = []
    for link in links(text):
        target = link.target
        if link.image and not (resolve(rel, target) or "").startswith(("wiki/assets/", "sources/", "references/")):
            out.append(item(rel, link.line, "embedded image must be a local file under wiki/assets/"))
            continue
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("/") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            out.append(item(rel, link.line, f"absolute or non-relative link {target!r}"))
            continue
        resolved = resolve(rel, target)
        if resolved is None:
            out.append(item(rel, link.line, f"link leaves the repository: {target!r}"))
        elif link.image and resolved.startswith(("sources/", "references/")):
            out.append(item(rel, link.line, "a source or reference image may not be embedded; "
                                            "link it instead"))
        elif target.endswith("/") or fs.is_dir(repo, resolved):
            out.append(item(rel, link.line, f"link to a directory {target!r}; link its index.md"))
        elif not fs.is_file(repo, resolved) and resolved.startswith(("sources/", "references/")):
            # Citation-only targets (4.10): the site turns them into quotes, and v1 sources
            # live in the archive repository (B16) – the writer cannot fix such a link.
            out.append(item(rel, link.line, f"cited source is not in this repository: "
                                            f"{target!r}", "warning"))
        elif not fs.is_file(repo, resolved):
            out.append(item(rel, link.line, f"link target does not exist: {target!r}"))
        elif link.image and resolved.lower().endswith(".mp4"):
            out += check_animation(repo, rel, link.line, resolved, fs=fs)
    return out


def check_animation(repo: Path, rel: str, line: int, video: str, *, fs=safefs) -> list[dict]:
    """An animation is a tool render under wiki/assets/ (render.json lists it) with its
    same-named .png poster, the static counterpart used in print."""
    if not video.startswith("wiki/assets/"):
        return [item(rel, line, "an animation must be a rendered file under wiki/assets/")]
    poster = video[:-4] + ".png"
    folder, name = video.rsplit("/", 1)
    out = []
    if not fs.is_file(repo, poster):
        out.append(item(rel, line, f"the animation needs its poster image {poster.rsplit('/', 1)[1]!r}"))
    receipt = f"{folder}/render.json"
    try:
        outputs = json.loads(fs.read_text(repo, receipt)).get("outputs") or {}
    except (FileNotFoundError, ValueError):
        outputs = {}
    if name not in outputs:
        out.append(item(rel, line, "the animation is not a tool render (no render.json entry); "
                                   "render it with `visual_tools.py render povray --frames`"))
    return out


def chapter_ids(repo: Path, rel: str, *, fs=safefs) -> set[str] | None:
    index = f"{Path(rel).parent.as_posix()}/index.md"
    if not fs.is_file(repo, index):
        return None
    chapters = frontmatter.split(fs.read_text(repo, index)).meta.get("chapters") or []
    return {c.get("id") for c in chapters if isinstance(c, dict)}


def check_meta(repo: Path, rel: str, meta: dict, *, fs=safefs) -> list[dict]:
    """Frontmatter rules by page type (plan 4.9; wiki-structure)."""
    name = Path(rel).name
    if name == "index.md":
        return check_index_meta(rel, meta)
    if rel == "wiki/log.md" or rel.startswith("wiki/assets/"):
        return []
    if rel.count("/") < 2:
        return []        # top-level info pages (a-projektrol.md) are free-form
    # A lesson-notes page gets `type: lesson-notes` from the tool (machine key, 4.9), so the
    # writer cannot and need not write it.
    lesson_page = name.endswith(LESSON_SUFFIX)
    required = ("title", "description") if lesson_page else ("type", "title", "description")
    out = [item(rel, None, f"frontmatter {key!r} missing") for key in required
           if not isinstance(meta.get(key), str) or not meta.get(key).strip()]
    if not FILE_NAME.match(name):
        out.append(item(rel, None, "file names are accent-free lowercase kebab-case", "warning"))
    kind = meta.get("type") or ("lesson-notes" if lesson_page else None)
    if kind and kind not in KNOWN_TYPES:
        out.append(item(rel, None, f"unknown page type {kind!r}", "warning"))
    for tag in meta.get("tags") or []:
        if not isinstance(tag, str) or not TAG.match(tag):
            out.append(item(rel, None, f"tag {tag!r} must be lowercase kebab-case, not numeric", "warning"))
    if kind in TYPES_WITH_CHAPTER:
        out += check_chapter(repo, rel, meta, fs=fs)
    if kind == "lesson-notes":
        out += check_lessons(repo, rel, meta, fs=fs)
    return out


def check_index_meta(rel: str, meta: dict) -> list[dict]:
    if rel == "wiki/index.md":
        return []
    chapters = meta.get("chapters")
    if not isinstance(chapters, list):
        return [item(rel, None, "subject index needs a `chapters` list")]
    out, seen = [], set()
    for c in chapters:
        if not isinstance(c, dict) or not re.fullmatch(r"[a-z0-9-]+", str(c.get("id", ""))) \
                or not str(c.get("title", "")).strip():
            out.append(item(rel, None, f"chapter entry {c!r} needs an `id` (kebab-case) and a `title`"))
        elif c["id"] in seen:
            out.append(item(rel, None, f"chapter id {c['id']!r} appears twice"))
        else:
            seen.add(c["id"])
    return out


def check_chapter(repo: Path, rel: str, meta: dict, *, fs=safefs) -> list[dict]:
    out = []
    ids = chapter_ids(repo, rel, fs=fs)
    if meta.get("chapter") is None:
        out.append(item(rel, None, "`chapter` missing (an id from the subject index `chapters`)"))
    elif ids is not None and meta["chapter"] not in ids:
        out.append(item(rel, None, f"chapter {meta['chapter']!r} is not in the subject index"))
    if not isinstance(meta.get("order"), int) or isinstance(meta.get("order"), bool):
        out.append(item(rel, None, "`order` missing or not an integer (10, 20, ...)"))
    return out


def check_lessons(repo: Path, rel: str, meta: dict, *, fs=safefs) -> list[dict]:
    lessons = meta.get("lessons")
    if not isinstance(lessons, list):
        return [item(rel, None, "`lessons` list missing")]
    out = []
    folder = Path(rel).parent.as_posix()
    for n, lesson in enumerate(lessons, start=1):
        if not isinstance(lesson, dict) or not str(lesson.get("title", "")).strip():
            out.append(item(rel, None, f"lesson {n}: `title` missing"))
            continue
        if lesson.get("date") is not None and not decisions.valid_date(lesson["date"]):
            out.append(item(rel, None, f"lesson {n}: `date` must be YYYY-MM-DD"))
        out += [item(rel, None, f"lesson {n}: {message}",
                     "error" if "technical file names" in message else "warning")
                for message in lesson_log.material_problems(lesson)]
        if not isinstance(lesson.get("topics", []), list):
            out.append(item(rel, None, f"lesson {n}: `topics` must be a list"))
            continue
        for topic in lesson.get("topics") or []:
            if not _topic_exists(repo, folder, str(topic).split("#", 1)[0], fs=fs):
                out.append(item(rel, None, f"lesson {n}: topic page {topic!r} does not exist"))
        anchor = lesson.get("anchor")
        if anchor and f'id="{anchor}"' not in fs.read_text(repo, rel):
            out.append(item(rel, None, f"lesson {n}: anchor {anchor!r} has no "
                                       f'<a id="{anchor}"></a> on this page', "warning"))
    return out


def _topic_exists(repo: Path, folder: str, topic: str, *, fs=safefs) -> bool:
    target = resolve(f"{folder}/index.md", topic)
    return target is not None and fs.is_file(repo, target)


def _same(repo: Path, rel: str, sha: str | None, *, fs=safefs) -> bool:
    target = resolve("x", rel) if rel else None      # normalised, refuses leaving the repo
    return bool(target) and fs.is_file(repo, target) and hashlib.sha256(fs.read_bytes(repo, target)).hexdigest() == sha


def check_renders(repo: Path, receipts: list[str] | None = None, *, fs=safefs) -> list[dict]:
    """render.json must still describe its source and outputs (no re-rendering here)."""
    out = []
    for rel in (sorted(receipts) if receipts is not None else
                fs.glob(repo, "wiki/assets", "wiki/assets/**/render.json")):
        try:
            data = json.loads(fs.read_text(repo, rel))
        except ValueError:
            out.append(item(rel, None, "render.json is not valid JSON"))
            continue
        if (not isinstance(data, dict) or not isinstance(data.get("source"), str)
                or not isinstance(data.get("outputs"), dict)
                or any(not isinstance(info, dict) for info in data["outputs"].values())):
            out.append(item(rel, None, "render.json has invalid source/outputs fields"))
            continue
        if not _same(repo, data["source"], data.get("source_sha256"), fs=fs):
            out.append(item(rel, None, "the figure source changed after rendering; render again"))
        base = rel.rsplit("/", 1)[0]
        for name, info in (data.get("outputs") or {}).items():
            if not _same(repo, f"{base}/{name}", (info or {}).get("sha256"), fs=fs):
                out.append(item(rel, None, f"rendered output {name!r} differs from render.json"))
    return out


def check_files(repo: Path, paths: list[str], *, today: date | None = None, fs=safefs, fix=True) -> list[dict]:
    """Check the run's changed markdown files and every render.json.

    Only files the writer may change are judged: wiki pages get every rule, `references/`
    only the secret and machine-path patterns. Tool-written files (docs/review,
    docs/evidence, sources/) are never reported to the writer, who could not fix them."""
    out = []
    for rel in sorted(set(paths)):
        if not rel.endswith(".md") or not fs.is_file(repo, rel):
            continue
        if rel.startswith("references/"):
            out += check_secrets(rel, fs.read_text(repo, rel, errors="replace"))
            continue
        if not rel.startswith("wiki/") or rel.startswith("wiki/assets/"):
            continue
        if fs is safefs and fix:
            autofix(repo, rel)
        text = fs.read_text(repo, rel).replace("\r\n", "\n")
        out += check_text(rel, text)
        try:
            page = frontmatter.split(text)
        except Exception as exc:
            out.append(item(rel, 1, f"frontmatter is not valid YAML: {exc}", kind=BLOCKING))
            continue
        out += check_meta(repo, rel, page.meta, fs=fs)
        out += check_learning(repo, rel, page, fs=fs)
        out += check_links(repo, rel, text, fs=fs)
        out += check_figure_sections(repo, rel, text, fs=fs)
        out += [item(rel, line, TEXTBOOK_MESSAGE, "warning") for line in textbook_lines(rel, text)]
    if fs is safefs:
        from . import date_spans
        out += order_warnings(repo, paths) + date_spans.warnings(repo, paths)
    if fs is safefs and not errors(out):
        out += [item(rel, None, message, "warning")
                for rel, message in drafts.warnings(repo, today or date.today(), paths=paths)]
    return out + check_renders(repo, fs=fs)


def check_figure_sections(repo: Path, rel: str, text: str, *, fs=safefs) -> list[dict]:
    """Every inserted figure on the page must still stand in the section its commission names
    (`anchor`): a renamed or removed heading leaves its verdict uncheckable. The message names the
    page, the figure and the missing title, and the fix (sn 0.3.9)."""
    from ..figures.context import section, with_markers
    out = []
    for name in markers.names(text):
        if not name.startswith("figure-"):
            continue
        fid = name[7:]
        evidence = f"docs/evidence/media/{fid}/figure.json"
        try:
            brief = json.loads(fs.read_text(repo, evidence)).get("commission") if fs.is_file(repo, evidence) else None
        except (ValueError, AttributeError):
            brief = None
        if not isinstance(brief, dict) or brief.get("kind") == "banner" or brief.get("page") != rel:
            continue
        anchor = str(brief.get("anchor", ""))
        try:
            body, _ = section(with_markers(text), anchor)
        except ValueError:
            out.append(item(rel, None, (
                f"figure {fid}: its commission names the section „{anchor}”, which is not on the page "
                "exactly once (renamed or removed?), so the figure's verdict cannot be checked: restore "
                f"that heading, or the controller sets the commission's `anchor` in {evidence} to the "
                "figure's current heading (then the figure is looked at again)")))
            continue
        if f"<!-- figure: {fid} -->" not in body:
            out.append(item(rel, None, (
                f"figure {fid}: it stands outside the section „{anchor}” its commission names: move it "
                f"back, or the controller updates the commission's `anchor` in {evidence}")))
    return out


def order_warnings(repo: Path, paths: list[str]) -> list[dict]:
    from . import teaching_order
    return teaching_order.order_warnings(repo, paths)


def textbook_lines(rel: str, text: str) -> list[int]:
    """Lines of a subject page with a 🔖 textbook pointer that has no lesson or page number
    (fix-52). Every pointer of a line is looked at on its own; only the presence of a number
    counts, never the words. Code and HTML comments are not visible text; the root legend and
    the indexes explain the line and are not checked."""
    if rel.count("/") < 2 or rel.endswith("/index.md"):
        return []
    body = INLINE_CODE.sub(blank, COMMENT.sub(blank, CODE_FENCE.sub(blank, text)))
    return [n for n, line in enumerate(body.split("\n"), start=1)
            if any(not TEXTBOOK_NUMBER.search(part) for part in TEXTBOOK.findall(line))]


def check_learning(repo: Path, rel: str, page: frontmatter.Page, *, fs=safefs) -> list[dict]:
    out = [item(rel, None, message, kind=BLOCKING) for message in
           decisions.decision_problems(page.meta) + drafts.problems(page.meta)]
    offset = len(page.raw_meta.splitlines()) + 2 if page.has_fm else 0
    out += [item(rel, line + offset, message, "warning")
            for line, message in decisions.question_problems(page.body, page.meta)]
    if "status" in page.meta and page.meta["status"] not in ("draft", "stable", "deprecated"):
        out.append(item(rel, None, "status must be draft, stable or deprecated"))
    visible = markers.BLOCK.sub("", CODE_FENCE.sub("", page.body))
    if re.search(r"^\s*(?:<sub>)?📎", visible, re.M):
        out.append(item(rel, None, "the tool renders the source pointer; supply lessons[].materials", "warning"))
    if lesson_log.is_lesson(rel, page.meta):
        try:
            lesson_log.source_line(page.meta)
        except ValueError as exc:
            out.append(item(rel, None, str(exc), kind=BLOCKING))
        if isinstance(page.meta.get("lessons"), list):
            out += [item(rel, None, message, "warning")
                    for message in lesson_log.form_problems(repo, rel, page.body, page.meta,
                                                read=lambda repo, path: frontmatter.split(fs.read_text(repo, path)))]
    elif lesson_log.BLOCK in markers.names(page.body):
        out.append(item(rel, None, "source pointer belongs only on a lesson log", "warning"))
    return out


def errors(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("severity", "error") == "error"]
