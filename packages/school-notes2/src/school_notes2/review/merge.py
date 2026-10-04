"""Three-way merge of independent tool-written review transitions and appended sections."""

import json
import re

import yaml

from ..wiki import frontmatter
from .files import BEFORE, DONE_HEADING, compute_status

MISSING = object()
SECTION = re.compile(r"^## (?:Végrehajtva|Válasz) \([^)]+\)$", re.M)


def _value(base, origin, own):
    if own == base or own == origin:
        return origin
    if origin == base:
        return own
    if all(isinstance(v, dict) for v in (base, origin, own)):
        merged = {}
        for key in sorted(base.keys() | origin.keys() | own.keys()):
            value = _value(base.get(key, MISSING), origin.get(key, MISSING), own.get(key, MISSING))
            if value is not MISSING:
                merged[key] = value
        return merged
    raise ValueError("conflicting review transitions")


def _body(base: str, origin: str, own: str) -> str:
    if origin == base or own == base or origin == own:
        return _value(base, origin, own)
    prefix = base.rstrip()
    if not origin.startswith(prefix) or not own.startswith(prefix):
        raise ValueError("the review body was edited, not appended")
    sections = {}
    for text in (origin[len(prefix):], own[len(prefix):]):
        matches = list(SECTION.finditer(text))
        if not matches or text[:matches[0].start()].strip():
            raise ValueError("not a tool closure or reply")
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section = text[match.start():end].strip()
            if match[0] in sections and sections[match[0]] != section:
                raise ValueError("conflicting review sections")
            sections[match[0]] = section
    return prefix + "\n\n" + "\n\n".join(sections[k] for k in sorted(sections)) + "\n"


def _closure_conflict(base, origin, own) -> bool:
    """A rerun restores its before map: it must not undo an upstream transition."""
    for heading in DONE_HEADING.finditer(own.body):
        nxt = re.search(r"^## ", own.body[heading.end():], re.M)
        end = heading.end() + nxt.start() if nxt else len(own.body)
        section = own.body[heading.start():end].strip()
        if section in base.body:
            continue
        before = BEFORE.search(section)
        if before and any(base.meta["items"].get(key) != origin.meta["items"].get(key)
                          for key in json.loads(before.group("items"))):
            return True
    return False


def merge(versions: list[bytes]) -> bytes | None:
    """None leaves genuine content/status conflicts for the owner; never choose a side."""
    try:
        pages = [frontmatter.split(v.decode("utf-8")) for v in versions]
        if not all(isinstance(p.meta.get("items"), dict) and "reviewer" in p.meta for p in pages):
            return None
        if _closure_conflict(*pages):
            return None
        meta = _value(*[{k: v for k, v in p.meta.items() if k != "status"} for p in pages])
        meta["status"] = compute_status(meta["items"])
        return frontmatter.set_keys(_body(*(p.body for p in pages)), meta).encode("utf-8")
    except (ValueError, UnicodeError, yaml.YAMLError):
        return None
