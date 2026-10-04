"""Warn about private source references mixed into a public web footnote."""

import re

from . import source_refs as refs

WEB = re.compile(r"https?://", re.I)


def scan(rel, text, old="", *, full=False):
    if not rel.startswith("wiki/") or not rel.endswith(".md") or rel == "wiki/log.md":
        return []
    masked = refs.COMMENT.sub(lambda m: refs.blank(m[0]), text)
    changed = set(range(1, len(masked.splitlines()) + 1)) if full else refs.changed_lines(old, text)
    out = []
    # Link-reference URLs can be defined outside the footnote.
    definitions = {m[1].lower(): (m[2], masked[:m.start()].count("\n") + 1) for m in re.finditer(
        r"^ {0,3}\[([^\]^]+)\]:\s*(https?://\S+)", masked, re.M | re.I)}
    for block in blocks(masked):
        value = "\n".join(line for _, line in block)
        referenced = sorted({label.lower() for label in re.findall(r"(?<!!)\[([^\]]+)\](?![:(])", value)} & definitions.keys())
        web = WEB.search(value) or referenced
        if not web or not any(p.search(value) for p in refs.PATTERNS):
            continue
        if not any(n in changed for n, _ in block) and not any(definitions[k][1] in changed for k in referenced):
            continue
        line = block[0][0]
        digest = refs.line_hash(value + "\n" + "\n".join(definitions[k][0] for k in referenced))
        out.append({"file": rel, "line": line, "severity": "warning", "kind": "public_footnote",
                    "id": f"{rel}:footnote:{digest}", "line_hash": digest, "occurrence": 1,
                    "message": "A webes lábjegyzetben csak a nyilvános hivatkozás állhat; "
                               "a privát forráshelyet tedd külön lábjegyzetbe. Ez figyelmeztetés, nem hiba."})
    return out


def blocks(text):
    blocks, current, fence = [], [], None
    for n, line in enumerate(text.splitlines(), 1):
        delimiter = refs.FENCE.match(line)
        if delimiter:
            fence = None if fence and delimiter[1][0] == fence[0] and len(delimiter[1]) >= len(fence) else delimiter[1]
        if fence or delimiter:
            if current:
                blocks.append(current)
                current = []
            continue
        if refs.FOOTNOTE.match(line):
            if current:
                blocks.append(current)
            current = [(n, line)]
        elif current and (not line.strip() or line.startswith(("    ", "\t"))):
            current.append((n, line))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks
