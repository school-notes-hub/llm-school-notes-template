"""Lesson logs refer to their main topic's current banner, never a copied file."""

from pathlib import Path

from . import frontmatter, markers
from .pages import CODE_FENCE, match_link, relative, resolve, read_page, sub_links

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
        match = match_link(line.strip())
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
    return sub_links(image, relocate)


def update(repo: Path, page: str, text: str) -> str:
    """The tool's banner block: replaced in place, or put at its fixed place
    (`markers.fixed_place`). The writer's own lines are never replaced (E7)."""
    meta = frontmatter.split(text).meta
    value = body(repo, page, meta)
    if BLOCK in markers.names(text):
        return markers.replace(text, BLOCK, value)
    if not value:
        return text
    return markers.at_fixed_place(text, BLOCK, value)
