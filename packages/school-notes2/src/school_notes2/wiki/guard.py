"""Path guard (plan 5.3 "Tilos", 5.4/1, T2): what may the run's LLM have changed?

Git stays outside: the caller passes the run's changes against the base commit
(from `git status`, ignored files excluded, no rename detection), a reader for base
content, and the tool's own recorded writes. The guard only judges.
"""

import hashlib
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..state import safefs
from ..sources import cards
from . import frontmatter, markers
from .machine import machine_keys

ALWAYS = ("wiki/",)
INTERACTIVE = ("references/",)


@dataclass(frozen=True)
class Change:
    path: str
    status: str          # added | modified | deleted


@dataclass(frozen=True)
class Violation:
    path: str
    message: str
    owner: bool          # True: only the owner can decide (8.1); False: back to the writer


@dataclass
class GuardInput:
    worktree: Path
    changes: list[Change]
    base_content: Callable[[str], bytes | None]   # None: the path is not in the base tree
    tool_files: dict[str, str] = field(default_factory=dict)   # path -> sha256 of the file
    tool_parts: dict[str, str] = field(default_factory=dict)   # path -> sha256 of machine parts
    interactive: bool = False
    conflict_files: frozenset[str] = frozenset()
    git_file: bytes | None = None                 # expected bytes of <worktree>/.git


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def machine_parts(text: str) -> str:
    """The parts of a page only the tool writes: machine frontmatter keys and generated blocks."""
    try:
        meta = frontmatter.split(text).meta
    except Exception:            # unreadable frontmatter: compare the whole text instead
        return text
    keys = machine_keys(meta)
    values = "\n".join(f"{k}={meta.get(k)!r}" for k in keys)
    blocks = "\n".join(f"{n}:{markers.read(text, n)}" for n in markers.names(text))
    return values + "\n--\n" + blocks


def _allowed(path: str, g: GuardInput) -> bool:
    """Writable places; dotfiles (`.gitattributes`, `.gitignore`, …) never, because they
    change how Git merges, archives or hides the writer's other files."""
    if any(part.startswith(".") for part in path.split("/")):
        return False
    prefixes = ALWAYS + (INTERACTIVE if g.interactive else ())
    return path.startswith(prefixes) or path in g.conflict_files


def _file_kind(root: Path, rel: str) -> str | None:
    """None for a regular file (or none at all); otherwise what is wrong with it. A symlink
    anywhere on the path counts, not only at its end (plan 7.6)."""
    try:
        mode = safefs.mode(root, rel)
    except safefs.UnsafePath:
        return "symlink"
    if mode is None:
        return None
    return None if stat.S_ISREG(mode) else "not a regular file"


def check_change(change: Change, g: GuardInput) -> list[Violation]:
    path = change.path
    if change.status == "deleted":
        if path in g.conflict_files:
            return []    # a delete/modify conflict the owner settled by deleting
        if path in g.tool_files:
            return [Violation(path, "a file the tool wrote was deleted", True)]
        return [Violation(path, "deleting or renaming a file that existed before the run", False)]
    kind = _file_kind(g.worktree, path)
    if kind:
        return [Violation(path, f"{kind} in the worktree", True)]
    if path in g.conflict_files:
        return []        # 6.7: the owner resolved this file in the session, whatever it holds
    try:
        data = safefs.read_bytes(g.worktree, path)
    except safefs.UnsafePath:                  # swapped for a link after the check
        return [Violation(path, "symlink in the worktree", True)]
    if path == "tools/subjects.json" and g.interactive:
        base = g.base_content(path)
        if base is not None and cards.only_cards_changed(base, data):
            return []
    if path in g.tool_files:
        if _sha(data) != g.tool_files[path]:
            return [Violation(path, "a file the tool wrote was changed afterwards", True)]
        return []
    if not _allowed(path, g):
        return [Violation(path, "the writer may not change files here", False)]
    return check_parts(path, data, g)


def check_parts(path: str, data: bytes, g: GuardInput) -> list[Violation]:
    """Machine keys and generated blocks must equal the base or the tool's own last write."""
    if not path.endswith(".md"):
        return []
    text = data.decode("utf-8", "replace")
    try:
        markers.check(text)
    except markers.MarkerError as exc:
        return [Violation(path, str(exc), False)]
    parts = machine_parts(text)
    base = g.base_content(path)
    if base is not None and machine_parts(base.decode("utf-8", "replace")) == parts:
        return []
    if base is None and not markers.names(text) and parts == machine_parts(_without_machine(text)):
        return []
    if g.tool_parts.get(path) == _sha(parts.encode()):
        return []
    return [Violation(path, "a machine field or a generated block was edited", False)]


def _without_machine(text: str) -> str:
    try:
        meta = frontmatter.split(text).meta
    except Exception:
        return text
    return frontmatter.strip_keys(text, machine_keys(meta))


def run(g: GuardInput) -> list[Violation]:
    found: list[Violation] = []
    if g.git_file is not None:
        if _file_kind(g.worktree, ".git") or not safefs.exists(g.worktree, ".git") \
                or safefs.read_bytes(g.worktree, ".git") != g.git_file:
            found.append(Violation(".git", "the worktree's .git file was replaced", True))
    for change in g.changes:
        found += check_change(change, g)
    return found


def parts_hash(text: str) -> str:
    """What the tool records in `tool_parts` after it writes machine keys or blocks."""
    return _sha(machine_parts(text).encode())
