"""Generated blocks inside hand-written files (plan 4.10, 6.7).

A block is the text between `<!-- school-notes:generated NAME -->` and
`<!-- /school-notes:generated -->`, each on its own line. Only the tool writes
inside a block; everything outside stays the author's (LLM or owner).
"""

import re

OPEN = "<!-- school-notes:generated {name} -->"
CLOSE = "<!-- /school-notes:generated -->"
BLOCK = re.compile(
    r"^<!-- school-notes:generated (?P<name>[a-z0-9-]+) -->\n(?P<body>.*?)^<!-- /school-notes:generated -->$",
    re.S | re.M)


class MarkerError(ValueError):
    pass


def names(text: str) -> list[str]:
    return [m.group("name") for m in BLOCK.finditer(text)]


def spans(text: str) -> list[tuple[int, int, str]]:
    """Balanced block extents, including legacy notices nested in another block."""
    stack, found = [], []
    pattern = r"^<!-- school-notes:generated ([a-z0-9-]+) -->$|^<!-- /school-notes:generated -->$"
    for match in re.finditer(pattern, text, re.M):
        if match[1]:
            stack.append((match.start(), match[1]))
        elif stack:
            start, name = stack.pop()
            found.append((start, match.end(), name))
    return sorted(found)


def is_notice(name: str) -> bool:
    return name == "pending" or name.startswith(("pending-section-", "pending-figure-"))


def clean_nested_notices(text: str) -> str:
    """Remove legacy notices inside another block before any regex-based replacement."""
    blocks = spans(text)
    nested = [(a, b) for a, b, name in blocks if is_notice(name)
              and any(start < a and b < end for start, end, _ in blocks)]
    # Only outermost selected ranges; preserve the enclosing block's line boundaries.
    ranges = []
    for start, end in nested:
        if not ranges or start >= ranges[-1][1]:
            ranges.append((start, end + int(text[end:end + 1] == "\n")))
    for start, end in reversed(ranges):
        text = text[:start] + text[end:]
    return text


def remove(text: str, names: set[str]) -> str:
    """Remove all named blocks and their insertion separators, even old duplicates."""
    ranges = []
    for start, end, name in spans(text):
        if name not in names:
            continue
        start -= int(start > 0 and text[start - 1] == "\n")
        end += len(re.match(r"\n{0,2}", text[end:])[0])
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(end, ranges[-1][1]))
        else:
            ranges.append((start, end))
    for start, end in reversed(ranges):
        text = text[:start] + text[end:]
    return text


def check(text: str) -> None:
    """Open and close markers must pair up, each name at most once."""
    opens = len(re.findall(r"^<!-- school-notes:generated [a-z0-9-]+ -->$", text, re.M))
    closes = len(re.findall(r"^<!-- /school-notes:generated -->$", text, re.M))
    found = names(text)
    if opens != closes or opens != len(found):
        raise MarkerError("unpaired generated-block markers")
    if len(set(found)) != len(found):
        raise MarkerError("a generated block appears twice")


def read(text: str, name: str) -> str | None:
    for m in BLOCK.finditer(text):
        if m.group("name") == name:
            return m.group("body")
    return None


def replace(text: str, name: str, body: str) -> str:
    """Put `body` (ending in a newline, or empty) into block `name`; it must exist."""
    text = clean_nested_notices(text)
    if body and not body.endswith("\n"):
        body += "\n"
    for m in BLOCK.finditer(text):
        if m.group("name") == name:
            return text[:m.start("body")] + body + text[m.end("body"):]
    raise MarkerError(f"generated block {name!r} missing")


def wrap(name: str, body: str) -> str:
    if body and not body.endswith("\n"):
        body += "\n"
    return OPEN.format(name=name) + "\n" + body + CLOSE + "\n"


ORDER = {"lesson-banner": 0, "lesson-sources": 1}   # then the ⏳ notices (2)


def rank(name: str) -> int:
    return ORDER.get(name, 2 if is_notice(name) else 3)


def fixed_place(text: str, name: str) -> int:
    """Where a new tool block goes (I6): right after the page title when the body's first
    non-empty line is a `# ` heading, else right after the frontmatter; then past the tool
    blocks already standing there whose canonical rank (banner → 📎 → ⏳) is not higher."""
    from . import frontmatter
    cut = len(text) - len(frontmatter.split(text).body)
    title = re.match(r"(?:[ \t]*\n)*# [^\n]*(?:\n|$)", text[cut:])
    if title:
        cut += title.end()
    for start, end, other in spans(text):
        if start < cut:
            continue
        if text[cut:start].strip() or rank(other) > rank(name):
            break
        # Past the block and its separator, as `remove` and the author-part strip count it,
        # so adding the new block never changes the author text.
        cut = end + len(re.match(r"\n{0,2}", text[end:])[0])
    return cut


def at_fixed_place(text: str, name: str, body: str) -> str:
    """Insert a tool block at its fixed place (see `fixed_place`)."""
    cut = fixed_place(text, name)
    return text[:cut] + "\n" + wrap(name, body) + "\n" + text[cut:]
