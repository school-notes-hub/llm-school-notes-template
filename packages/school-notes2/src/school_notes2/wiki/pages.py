"""Reading the wiki: pages, frontmatter, links (shared by check and generate)."""

import hashlib
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..state import safefs
from . import frontmatter

CODE_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
INLINE_CODE = re.compile(r"`[^`\n]*`")
COMMENT = re.compile(r"<!--.*?-->", re.S)
LINK = re.compile(r"(?P<img>!?)\[(?P<text>(?:[^\[\]]|\[[^\]]*\])*)\]\((?P<target><[^>]*>|[^)\s]*)(?:\s+\"[^\"]*\")?\)")
HTML_IMG = re.compile(r"<img\b[^>]*\bsrc=(?P<q>[\"'])(?P<target>.+?)(?P=q)", re.I)
RESERVED = ("index.md", "log.md")


class PageError(ValueError):
    """A page-local metadata error, without quoting private YAML values."""

    def __init__(self, page: str, problems: list[str]):
        super().__init__(f"{page}: " + "; ".join(problems))
        self.page, self.problems = page, problems


@dataclass(frozen=True)
class Link:
    image: bool
    text: str
    target: str     # as written, without the #anchor
    line: int
    fragment: str = ""


# Every access is relative to the repo root through safefs: the worktree is the container's
# and may hold planted symlinks (plan 7.6).

def sha256(repo: Path, rel: str) -> str:
    return hashlib.sha256(safefs.read_bytes(repo, rel)).hexdigest()


def read_text(repo: Path, rel: str) -> str:
    return safefs.read_text(repo, rel)


def read_page(repo: Path, rel: str) -> frontmatter.Page:
    try:
        return frontmatter.split(safefs.read_text(repo, rel))
    except (ValueError, yaml.YAMLError) as exc:
        raise PageError(rel, ["frontmatter is not valid YAML or not a mapping"]) from exc


def is_file(repo: Path, rel: str) -> bool:
    return safefs.is_file(repo, rel)


def md_files(repo: Path, pattern: str = "wiki/**/*.md") -> list[str]:
    """Repo-relative markdown paths matching `pattern`; symlinks are never followed."""
    return safefs.glob(repo, "wiki", pattern)


def wiki_pages(repo: Path) -> list[str]:
    """Repo-relative paths of every published markdown page (B7: no log, no asset READMEs)."""
    return [rel for rel in md_files(repo)
            if rel != "wiki/log.md" and not rel.startswith("wiki/assets/")]


def subjects(repo: Path) -> list[str]:
    """Subject folders: wiki/<subject>/ with an index.md (assets is not a subject)."""
    return sorted(rel.split("/")[1] for rel in md_files(repo, "wiki/*/index.md")
                  if rel.split("/")[1] != "assets")


def _blank(match: re.Match) -> str:
    # Keep line numbers stable while hiding the text from the link scanner.
    return re.sub(r"[^\n]", " ", match.group(0))


def links(text: str) -> list[Link]:
    """Inline links and images outside code and HTML comments, with 1-based line numbers."""
    body = CODE_FENCE.sub(_blank, text)
    body = COMMENT.sub(_blank, body)
    body = INLINE_CODE.sub(_blank, body)
    found = []
    for m in LINK.finditer(body):
        target, _, fragment = m.group("target").strip("<>").partition("#")
        found.append(Link(bool(m.group("img")), m.group("text"), target,
                          body.count("\n", 0, m.start()) + 1, fragment))
    for m in HTML_IMG.finditer(body):
        found.append(Link(True, "", m.group("target").split("#", 1)[0],
                          body.count("\n", 0, m.start()) + 1))
    return found


def is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I)) or target.startswith("//")


def resolve(page_rel: str, target: str) -> str | None:
    """Repo-relative POSIX path of a relative link target; None if it leaves the repo."""
    if not target or is_external(target) or target.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(page_rel), target))
    if joined.startswith("../") or joined == "..":
        return None
    return joined


def relative(from_page: str, to_path: str) -> str:
    return posixpath.relpath(to_path, posixpath.dirname(from_page))
