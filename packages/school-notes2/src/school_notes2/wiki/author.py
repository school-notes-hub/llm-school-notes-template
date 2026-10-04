"""Canonical author text, excluding machine-owned metadata and generated blocks."""

import re

from . import frontmatter, machine, markers


def part(text: str, *, legacy_notices=False) -> str:
    """The text without generated blocks and machine frontmatter keys."""
    from ..figures.commissions import MARKER
    from ..wiki.banners import canonical_reference
    # Strip notices before normalizing figure and banner blocks, including old nesting.
    if not legacy_notices:
        text = markers.clean_nested_notices(text)
        text = markers.remove(text, {name for _, _, name in markers.spans(text) if markers.is_notice(name)})
    text = canonical_reference(text)
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
