"""Resolve textbook lines against the private book index, extracting only cited pages."""

import re
from pathlib import PurePosixPath

from ..state import safefs
from ..wiki import frontmatter, pages

NUMBERS = r"\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*"
PRINTED = re.compile(r"(" + NUMBERS + r")\.\s*oldal|pages?\s+(" + NUMBERS + r")", re.I)


def _books(page, targets):
    found = set()
    for target in targets:
        path = pages.resolve(page, target)
        if path and path.startswith("references/") and PurePosixPath(path).name in ("README.md", "index.md", "document.md"):
            found.add(str(PurePosixPath(path).parent))
    return sorted(found)


def _numbers(line):
    result = set()
    for match in PRINTED.finditer(line):
        for span in (match[1] or match[2]).split(","):
            ends = [int(n) for n in re.split(r"\s*[-–]\s*", span)]
            result.update(range(ends[0], ends[-1] + 1))
    return sorted(result)


def _excerpt(repo, book, number):
    index, document = book + "/index.md", book + "/document.md"
    if not safefs.is_file(repo, document):
        return {"status": "index-only", "book": book}
    if not safefs.is_file(repo, index):
        return {"status": "missing-index", "book": book}
    starts = {}
    for line in safefs.read_text(repo, index).splitlines():
        if line.startswith("* "):
            starts.update((int(p), int(n)) for p, n in re.findall(r"(?:^\* | · )(\d+): (\d+)", line))
    if number not in starts:
        return {"status": "unmapped-page", "book": book, "page": number}
    first = starts[number]
    following = sorted(n for n in starts.values() if n > first)
    last = following[0] - 1 if following else None
    return {"status": "available", "document": document, "page": number,
            "first_line": first, "last_line": last, "text": safefs.read_lines(repo, document, first, last)}


def collect(repo, members):
    result = []
    for page in sorted(p for p in members if p.endswith(".md")):
        text = safefs.read_text(repo, page)
        body = pages.CODE_FENCE.sub("", frontmatter.split(text).body)
        lines = [line for line in body.splitlines() if "🔖" in line]
        if not lines:
            continue
        meta = frontmatter.split(text).meta
        targets = [s.get("resource", "") for s in meta.get("sources", [])]
        targets += [l.target for l in pages.links(body) if not l.image]
        cited = _books(page, targets)
        if not cited:
            subject = PurePosixPath(page).parent.name
            cited = sorted({str(PurePosixPath(p).parent) for p in
                            safefs.glob(repo, f"references/{subject}", f"references/{subject}/*/README.md")})
        for line in lines:
            books = _books(page, [l.target for l in pages.links(line)]) or cited
            numbers = _numbers(line)
            row = {"file": page, "line": line, "books": books, "excerpts": []}
            if len(books) == 1 and numbers:
                row["excerpts"] = [_excerpt(repo, books[0], n) for n in numbers]
            else:
                row["status"] = "unresolved-book" if len(books) != 1 else "no-page-range"
            result.append(row)
    return result
