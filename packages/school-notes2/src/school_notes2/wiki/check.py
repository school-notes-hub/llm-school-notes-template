"""The mechanical `check` of plan 5.4/5 on markdown files.

Fixes what is unambiguous (line endings, final newline) and returns the rest as
check.json items `{file, line, message, severity}`; errors send the run back to the
writer, warnings do not.
"""

import json
import re
from datetime import date
from pathlib import Path

from ..state import safefs
from . import decisions, drafts, frontmatter, lesson_log, markers
from .pages import CODE_FENCE, links, resolve, sha256

SIZE_WARN = 40 * 1024
TYPES_WITH_CHAPTER = ("topic", "chapter-summary")
LESSON_SUFFIX = "-jegyzet.md"
KNOWN_TYPES = ("topic", "chapter-summary", "lesson-notes", "review", "source-summary",
               "concept", "entity", "question")
# The release's last gate (check-public.py) and this check share one pattern file, so the
# check tells the writer everything the gate would stop (5.4/5). Secrets and machine paths
# only (4.10): footnotes naming photos stay in the wiki; the public view leaves them out.
PATTERNS_FILE = Path(__file__).resolve().parents[4] / "study-site" / "public-patterns.json"


def load_patterns(path: Path = PATTERNS_FILE) -> tuple[str, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(data["secrets"]) + tuple(data["machine_paths"])


SECRET_PATTERNS = load_patterns()
CONFLICT = re.compile(r"^(<<<<<<<|>>>>>>>)( |$)", re.M)
TAG = re.compile(r"^(?=.*[a-z])[a-z0-9-]+(/[a-z0-9-]+)*$")
FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPOGRAPHY = re.compile("[–—“”‘’]")


def item(file: str, line: int | None, message: str, severity: str = "error") -> dict:
    return {"file": file, "line": line, "message": message, "severity": severity}


def autofix(repo: Path, rel: str) -> bool:
    """CRLF to LF and a final newline: unambiguous, so the tool fixes them itself."""
    data = safefs.read_bytes(repo, rel)
    fixed = data.replace(b"\r\n", b"\n")
    if fixed and not fixed.endswith(b"\n"):
        fixed += b"\n"
    if fixed != data:
        safefs.write_bytes(repo, rel, fixed)
        return True
    return False


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_secrets(rel: str, text: str) -> list[dict]:
    """Conflict markers, secrets and machine paths: every file the writer may change."""
    out = []
    for m in CONFLICT.finditer(text):
        out.append(item(rel, line_of(text, m.start()), "unresolved conflict marker"))
    for pattern in SECRET_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            out.append(item(rel, line_of(text, m.start()),
                            f"forbidden secret or machine-path pattern {pattern!r}"))
    return out


def check_text(rel: str, text: str) -> list[dict]:
    """Wiki-page rules: the above plus block markers, size, formulas, punctuation."""
    out = check_secrets(rel, text)
    try:
        markers.check(text)
    except markers.MarkerError as exc:
        out.append(item(rel, None, str(exc)))
    if len(text.encode()) > SIZE_WARN:
        out.append(item(rel, None, "page is over 40 KB; consider splitting it", "warning"))
    out += check_formulas(rel, text)
    if TYPOGRAPHY.search(CODE_FENCE.sub("", _body(text))):
        out.append(item(rel, None, "typographic dash or quote; the wiki uses ASCII punctuation "
                                   "outside verbatim quotes", "warning"))
    return out


def _body(text: str) -> str:
    try:
        return frontmatter.split(text).body
    except Exception:
        return text


def check_formulas(rel: str, text: str) -> list[dict]:
    """Display-math delimiters must pair up; the build compiles the formulas themselves."""
    body = CODE_FENCE.sub("", text)
    body = re.sub(r"`[^`\n]*`", "", body)
    if body.count("$$") % 2:
        return [item(rel, None, "unbalanced $$ display-math delimiter")]
    if body.count("\\[") != body.count("\\]") or body.count("\\(") != body.count("\\)"):
        return [item(rel, None, "unbalanced \\[ \\] or \\( \\) math delimiter")]
    return []


def check_links(repo: Path, rel: str, text: str) -> list[dict]:
    out = []
    for link in links(text):
        target = link.target
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
        elif target.endswith("/") or safefs.is_dir(repo, resolved):
            out.append(item(rel, link.line, f"link to a directory {target!r}; link its index.md"))
        elif not safefs.is_file(repo, resolved) and resolved.startswith(("sources/", "references/")):
            # Citation-only targets (4.10): the site turns them into quotes, and v1 sources
            # live in the archive repository (B16) – the writer cannot fix such a link.
            out.append(item(rel, link.line, f"cited source is not in this repository: "
                                            f"{target!r}", "warning"))
        elif not safefs.is_file(repo, resolved):
            out.append(item(rel, link.line, f"link target does not exist: {target!r}"))
        elif link.image and resolved.lower().endswith(".mp4"):
            out += check_animation(repo, rel, link.line, resolved)
    return out


def check_animation(repo: Path, rel: str, line: int, video: str) -> list[dict]:
    """An animation is a tool render under wiki/assets/ (render.json lists it) with its
    same-named .png poster, the static counterpart used in print."""
    if not video.startswith("wiki/assets/"):
        return [item(rel, line, "an animation must be a rendered file under wiki/assets/")]
    poster = video[:-4] + ".png"
    folder, name = video.rsplit("/", 1)
    out = []
    if not safefs.is_file(repo, poster):
        out.append(item(rel, line, f"the animation needs its poster image {poster.rsplit('/', 1)[1]!r}"))
    receipt = f"{folder}/render.json"
    try:
        outputs = json.loads(safefs.read_text(repo, receipt)).get("outputs") or {}
    except (FileNotFoundError, ValueError):
        outputs = {}
    if name not in outputs:
        out.append(item(rel, line, "the animation is not a tool render (no render.json entry); "
                                   "render it with `visual_tools.py render povray --frames`"))
    return out


def chapter_ids(repo: Path, rel: str) -> set[str] | None:
    index = f"{Path(rel).parent.as_posix()}/index.md"
    if not safefs.is_file(repo, index):
        return None
    chapters = frontmatter.split(safefs.read_text(repo, index)).meta.get("chapters") or []
    return {c.get("id") for c in chapters if isinstance(c, dict)}


def check_meta(repo: Path, rel: str, meta: dict) -> list[dict]:
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
        out.append(item(rel, None, "file names are accent-free lowercase kebab-case"))
    kind = meta.get("type") or ("lesson-notes" if lesson_page else None)
    if kind and kind not in KNOWN_TYPES:
        out.append(item(rel, None, f"unknown page type {kind!r}", "warning"))
    for tag in meta.get("tags") or []:
        if not isinstance(tag, str) or not TAG.match(tag):
            out.append(item(rel, None, f"tag {tag!r} must be lowercase kebab-case, not numeric"))
    if kind in TYPES_WITH_CHAPTER:
        out += check_chapter(repo, rel, meta)
    if kind == "lesson-notes":
        out += check_lessons(repo, rel, meta)
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


def check_chapter(repo: Path, rel: str, meta: dict) -> list[dict]:
    out = []
    ids = chapter_ids(repo, rel)
    if meta.get("chapter") is None:
        out.append(item(rel, None, "`chapter` missing (an id from the subject index `chapters`)"))
    elif ids is not None and meta["chapter"] not in ids:
        out.append(item(rel, None, f"chapter {meta['chapter']!r} is not in the subject index"))
    if not isinstance(meta.get("order"), int) or isinstance(meta.get("order"), bool):
        out.append(item(rel, None, "`order` missing or not an integer (10, 20, ...)"))
    return out


def check_lessons(repo: Path, rel: str, meta: dict) -> list[dict]:
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
        out += [item(rel, None, f"lesson {n}: {message}")
                for message in lesson_log.material_problems(lesson)]
        if not isinstance(lesson.get("topics", []), list):
            out.append(item(rel, None, f"lesson {n}: `topics` must be a list"))
            continue
        for topic in lesson.get("topics") or []:
            if not _topic_exists(repo, folder, str(topic).split("#", 1)[0]):
                out.append(item(rel, None, f"lesson {n}: topic page {topic!r} does not exist"))
        anchor = lesson.get("anchor")
        if anchor and f'id="{anchor}"' not in safefs.read_text(repo, rel):
            out.append(item(rel, None, f"lesson {n}: anchor {anchor!r} has no "
                                       f'<a id="{anchor}"></a> on this page', "warning"))
    return out


def _topic_exists(repo: Path, folder: str, topic: str) -> bool:
    target = resolve(f"{folder}/index.md", topic)
    return target is not None and safefs.is_file(repo, target)


def _same(repo: Path, rel: str, sha: str | None) -> bool:
    target = resolve("x", rel) if rel else None      # normalised, refuses leaving the repo
    return bool(target) and safefs.is_file(repo, target) and sha256(repo, target) == sha


def check_renders(repo: Path, receipts: list[str] | None = None) -> list[dict]:
    """render.json must still describe its source and outputs (no re-rendering here)."""
    out = []
    for rel in (sorted(receipts) if receipts is not None else
                safefs.glob(repo, "wiki/assets", "wiki/assets/**/render.json")):
        try:
            data = json.loads(safefs.read_text(repo, rel))
        except ValueError:
            out.append(item(rel, None, "render.json is not valid JSON"))
            continue
        if (not isinstance(data, dict) or not isinstance(data.get("source"), str)
                or not isinstance(data.get("outputs"), dict)
                or any(not isinstance(info, dict) for info in data["outputs"].values())):
            out.append(item(rel, None, "render.json has invalid source/outputs fields"))
            continue
        if not _same(repo, data["source"], data.get("source_sha256")):
            out.append(item(rel, None, "the figure source changed after rendering; render again"))
        base = rel.rsplit("/", 1)[0]
        for name, info in (data.get("outputs") or {}).items():
            if not _same(repo, f"{base}/{name}", (info or {}).get("sha256")):
                out.append(item(rel, None, f"rendered output {name!r} differs from render.json"))
    return out


def check_files(repo: Path, paths: list[str], *, today: date | None = None) -> list[dict]:
    """Check the run's changed markdown files and every render.json.

    Only files the writer may change are judged: wiki pages get every rule, `references/`
    only the secret and machine-path patterns. Tool-written files (docs/review,
    docs/evidence, sources/) are never reported to the writer, who could not fix them."""
    out = []
    for rel in sorted(set(paths)):
        if not rel.endswith(".md") or not safefs.is_file(repo, rel):
            continue
        if rel.startswith("references/"):
            out += check_secrets(rel, safefs.read_text(repo, rel, errors="replace"))
            continue
        if not rel.startswith("wiki/") or rel.startswith("wiki/assets/"):
            continue
        autofix(repo, rel)
        text = safefs.read_text(repo, rel)
        out += check_text(rel, text)
        try:
            page = frontmatter.split(text)
        except Exception as exc:
            out.append(item(rel, 1, f"frontmatter is not valid YAML: {exc}"))
            continue
        out += check_meta(repo, rel, page.meta)
        out += check_learning(repo, rel, page)
        out += check_links(repo, rel, text)
    if not errors(out):
        out += [item(rel, None, message, "warning")
                for rel, message in drafts.warnings(repo, today or date.today(), paths=paths)]
    return out + check_renders(repo)


def check_learning(repo: Path, rel: str, page: frontmatter.Page) -> list[dict]:
    out = [item(rel, None, message) for message in
           decisions.decision_problems(page.meta) + drafts.problems(page.meta)]
    offset = len(page.raw_meta.splitlines()) + 2 if page.has_fm else 0
    out += [item(rel, line + offset, message)
            for line, message in decisions.question_problems(page.body, page.meta)]
    if "status" in page.meta and page.meta["status"] not in ("draft", "stable", "deprecated"):
        out.append(item(rel, None, "status must be draft, stable or deprecated"))
    visible = markers.BLOCK.sub("", CODE_FENCE.sub("", page.body))
    if re.search(r"^\s*(?:<sub>)?📎", visible, re.M):
        out.append(item(rel, None, "the tool renders the source pointer; supply lessons[].materials"))
    if lesson_log.is_lesson(rel, page.meta) and isinstance(page.meta.get("lessons"), list):
        out += [item(rel, None, message)
                for message in lesson_log.form_problems(repo, rel, page.body, page.meta)]
    elif lesson_log.BLOCK in markers.names(page.body):
        out.append(item(rel, None, "source pointer belongs only on a lesson log"))
    return out


def errors(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("severity", "error") == "error"]
