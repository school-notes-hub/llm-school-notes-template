"""Lesson logs refer to their main topic's current banner, never a copied file."""

import yaml
from pathlib import Path

from . import frontmatter, markers
from .pages import CODE_FENCE, LINK, relative, resolve, read_page

BLOCK = "lesson-banner"


def target(repo: Path, page: str, meta: dict, *, read=read_page) -> str | None:
    value = meta.get("banner_from")
    if value is None:
        return None
    if meta.get("type") != "lesson-notes" or not isinstance(value, str) or not value.endswith(".md"):
        raise ValueError("banner_from needs a topic Markdown path on a lesson log")
    dest = resolve(page, value)
    topics = {resolve(page, str(t).split("#", 1)[0]) for lesson in meta.get("lessons", [])
              for t in lesson.get("topics", [])}
    if not dest or dest not in topics or read(repo, dest).meta.get("type") != "topic":
        raise ValueError("banner_from must name a listed topic page")
    return dest


def banner(repo: Path, page: str, *, read=read_page) -> str:
    return leading(read(repo, page).body)


def leading(text: str) -> str:
    # Only a leading image is a header; an illustration later in the lesson is not.
    for line in CODE_FENCE.sub("", text).splitlines():
        if not line.strip() or line.startswith(("<!--", "# ")):
            continue
        match = LINK.fullmatch(line.strip())
        if match and match["img"]:
            return line.strip()
        return ""
    return ""


def body(repo: Path, page: str, meta: dict, *, read=read_page) -> str:
    source = target(repo, page, meta, read=read)
    if not source:
        return ""
    image = banner(repo, source, read=read)
    def relocate(match):
        dest = resolve(source, match["target"].strip("<>"))
        if not dest or not dest.startswith("wiki/assets/"):
            raise ValueError("topic banner must be a local wiki asset")
        return f'![{match["text"]}](<{relative(page, dest)}>)'
    return LINK.sub(relocate, image)


def update(repo: Path, page: str, text: str) -> str:
    meta = frontmatter.split(text).meta
    value = body(repo, page, meta)
    if BLOCK in markers.names(text):
        return markers.replace(text, BLOCK, value)
    if not value:
        return text
    parsed = frontmatter.split(text)
    # Opting into reuse replaces the old leading banner, including its evidence block.
    header = leading(parsed.body)
    if header:
        for match in markers.BLOCK.finditer(text):
            if header in match["body"]:
                return text[:match.start()] + markers.wrap(BLOCK, value).rstrip() + text[match.end():]
        text = text.replace(header, markers.wrap(BLOCK, value).rstrip(), 1)
        return text
    cut = len(text) - len(parsed.body)
    return text[:cut] + "\n" + markers.wrap(BLOCK, value) + "\n" + text[cut:]


def canonical_reference(text: str) -> str:
    """The old header of a newly opted-in lesson is tool-owned, like its replacement."""
    try:
        page = frontmatter.split(text)
    except (ValueError, yaml.YAMLError):
        return text
    if not page.meta.get("banner_from") or not (header := leading(page.body)):
        return text
    empty = markers.wrap(BLOCK, "").rstrip("\n")
    for block in markers.BLOCK.finditer(text):
        if header in block["body"]:
            return text[:block.start()] + empty + text[block.end():]
    return text.replace(header, empty, 1)


def candidate_image(repo: Path, page: str, briefs: list[dict]) -> str | None:
    """Bind a preview's reused banner to its publication bytes, not its review PNG."""
    from ..figures import commissions
    source = target(repo, page, read_page(repo, page).meta)
    for brief in sorted(briefs, key=lambda b: b["id"]):
        if brief["page"] != source or brief["kind"] != "banner":
            continue
        candidate = commissions.candidate(repo, brief)
        if candidate["state"] != "candidate" or not candidate.get("asset"):
            continue
        alt = candidate["alt"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        return f'![{alt}](<{relative(page, candidate["asset"])}>)'
    return None


def required(path: str, meta: dict) -> bool:
    return meta.get("type") in ("topic", "chapter-summary") or (
        len(Path(path).parts) == 3 and path.startswith("wiki/") and
        not path.startswith("wiki/assets/") and path.endswith("/index.md"))


def asset(page: str, text: str) -> str | None:
    match = LINK.fullmatch(leading(text))
    return resolve(page, match["target"].strip("<>")) if match else None


def generated_header(repo, path, text, proof=None):
    from . import rights
    image = asset(path, text)
    from ..state import safefs
    if not image or not safefs.is_file(repo, image):
        return False
    return bool(rights.generated(repo, image, proof))


def pending_header(repo, path, text, waiting):
    from ..figures import commissions
    for marker in commissions.MARKER.finditer(text):
        brief = waiting.get(marker[1])
        if brief is None:
            try:
                brief = commissions.read(repo, marker[1])
            except (ValueError, OSError):
                continue
        if brief["kind"] == "banner" and brief["page"] == path:
            prefix = markers.BLOCK.sub("", text[:marker.start()]).strip()
            if not prefix:
                return True
    return False


def check_required(repo: Path, paths: list[str], *, generated=None) -> list[dict]:
    """Author-touched topics, summaries and subject indexes need generated headers."""
    from ..figures import pending
    from ..state import safefs
    from .check import item
    waiting = {e["commission"]["id"]: e["commission"] for e in pending.load(repo)}
    result = []
    for path in sorted(set(paths)):
        if not path.endswith(".md") or not safefs.is_file(repo, path):
            continue
        page = read_page(repo, path)
        if not required(path, page.meta) or generated_header(repo, path, page.body, generated):
            continue
        if not pending_header(repo, path, page.body, waiting):
            result.append(item(path, None, "page needs a generated leading banner or a banner commission marker; "
                               "replace an ungenerated header with replaces and decision_reason code c"))
    return result
