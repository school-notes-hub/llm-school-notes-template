"""Canonical author text, excluding machine-owned metadata and generated blocks."""

import re

from . import frontmatter, machine, markers


def part(text: str, *, legacy_notices=False) -> str:
    """The text without generated blocks and machine frontmatter keys."""
    from ..figures.commissions import MARKER
    # Strip notices before normalizing figure and banner blocks, including old nesting.
    if not legacy_notices:
        text = markers.clean_nested_notices(text)
        text = markers.remove(text, {name for _, _, name in markers.spans(text) if markers.is_notice(name)})
    text = markers.BLOCK.sub(lambda m: f"<!-- figure: {m['name'][7:]} -->"
                             if m["name"].startswith("figure-") else m[0], text)
    text = MARKER.sub(lambda m: f"<!-- figure: {m[1]} -->", text)
    # Adding a tool block is not an author edit either. Strip its insertion separators,
    # preserving whitespace everywhere else (including the author's code examples).
    text = re.sub(r"\n?" + markers.BLOCK.pattern + r"\n{0,2}", "", text, flags=re.S | re.M)
    try:
        meta = frontmatter.split(text).meta
    except Exception:  # noqa: BLE001 - unreadable frontmatter: compare the whole text
        return text
    return frontmatter.strip_keys(text, machine.machine_keys(meta))


def tool_lines(text: str) -> set[int]:
    """1-based numbers of the lines the tool owns: generated blocks (banner, 📎, ⏳, indexes)
    and machine frontmatter keys. Every other line is the author's. Shared by the recheck and
    the nightly triage: a finding on a tool line is an owner note, never an item."""
    lines = set()
    for start, end, _ in markers.spans(text):
        lines.update(range(text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 2))
    try:
        page = frontmatter.split(text)
    except Exception:  # noqa: BLE001 - unreadable frontmatter: only the blocks are known
        return lines
    if page.has_fm and page.raw_meta:
        keys, n = machine.machine_keys(page.meta), 2  # line 1 is the opening fence
        for key, chunk in frontmatter.blocks(page.raw_meta):
            size = chunk.count("\n") + 1
            if key in keys:
                lines.update(range(n, n + size))
            n += size
    return lines
