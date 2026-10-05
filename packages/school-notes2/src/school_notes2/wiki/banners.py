"""Lesson logs refer to their main topic's current banner, never a copied file."""

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
    """The tool's banner block: replaced in place, or put at the fixed place right after
    the frontmatter. The writer's own lines are never replaced (E7)."""
    meta = frontmatter.split(text).meta
    value = body(repo, page, meta)
    if BLOCK in markers.names(text):
        return markers.replace(text, BLOCK, value)
    if not value:
        return text
    return markers.at_fixed_place(text, BLOCK, value)


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
