"""Separate fixed tool literals from authored values copied into generated blocks."""

import re

from ..state import safefs
from ..wiki import frontmatter, generate, markers
from ..wiki.pages import PageError, links, read_page, resolve, wiki_pages


def matches(text, quote):
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    return list(re.finditer(pattern, text)) if pattern else []


def _literals(text):
    from ..reader import notices
    from ..wiki import drafts
    headings = {"notes": "# 📝 Jegyzetek", "review": "# 🔁 Ismétlés",
                "catch-up": "# 📝 Pótolandó", "lessons": generate.TABLE_HEAD.rstrip()}
    for start, end, name in markers.spans(text):
        offset = text.index("\n", start) + 1
        body = text[offset:end - len(markers.CLOSE)]
        fixed = headings.get(name)
        if fixed and body.startswith(fixed + "\n"):
            yield offset, offset + len(fixed)
        if markers.is_notice(name) and body.strip() in (
                notices.PAGE.strip(), notices.SECTION.strip(), notices.FIGURE.strip(), drafts.NOTICE.strip()):
            yield offset, offset + len(body.rstrip())
        if name == "chapters":
            for match in re.finditer(r"^# 📘 ", body, re.M):
                yield offset + match.start(), offset + match.end()
        if name == "lesson-sources" and body.startswith("📎 Füzet: "):
            yield offset, offset + len("📎 Füzet: ")
            split = body.find(" · Tanári anyag: ")
            if split >= 0:
                yield offset + split, offset + split + len(" · Tanári anyag: ")
            # "dátum nélküli óra" is not tool text: it reports a missing lesson date the
            # writer can supply, so a finding about it stays an open item.


def only_literals(text, quote):
    found, literals = matches(text, quote), []
    for start, end in sorted(_literals(text)):
        if literals and not text[literals[-1][1]:start].strip():
            literals[-1] = (literals[-1][0], max(end, literals[-1][1]))
        else:
            literals.append((start, end))
    return bool(found) and all(any(a <= m.start() and m.end() <= b for a, b in literals) for m in found)


def _source_values(repo):
    values = []
    for path in sorted(wiki_pages(repo)):
        try:
            meta = read_page(repo, path).meta
        except PageError:
            continue
        fields = [meta.get("title"), meta.get("description")]
        for lesson in meta.get("lessons") or []:
            if isinstance(lesson, dict):
                fields += [lesson.get("title"), *(lesson.get("materials") or [])]
        values += [(path, value) for value in fields if isinstance(value, str)]
    return values


def _route(text, finding, values):
    found, blocks = matches(text, finding.get("quote", "")), markers.spans(text)
    if not found or not all(any(a <= m.start() and m.end() <= b for a, b, _ in blocks) for m in found):
        return finding
    figures = [(a, b) for a, b, name in blocks if name.startswith("figure-")
               and any(a <= m.start() and m.end() <= b for m in found)]
    if figures:
        if not all(any(a <= m.start() and m.end() <= b for a, b in figures) for m in found):
            return finding
        paths = {resolve(finding["file"], link.target) for a, b in figures
                 for link in links(text[a:b]) if link.image}
        paths = {p for p in paths if p and p.startswith("wiki/assets/")}
    else:
        paths = {path for path, value in values if matches(value, finding["quote"])}
    return {**finding, "file": next(iter(paths)), "reported_file": finding["file"]} if len(paths) == 1 else finding


def partition(repo, findings, notes):
    kept, feedback, literals = [], [], []
    values = _source_values(repo) if findings else []
    for finding in findings:
        path = finding["file"]
        text = safefs.read_text(repo, path) if path.endswith(".md") and safefs.is_file(repo, path) else ""
        if not only_literals(text, finding.get("quote", "")):
            kept.append(_route(text, finding, values))
            continue
        literals.append(finding)
        feedback.append(f"Tool-sablon ({path}): {finding['problem']} "
                        f"Idézet: {finding['quote']} Javaslat: {finding.get('suggestion', '')}")
    return kept, list(notes) + sorted(set(" ".join(n.split()) for n in feedback)), literals


def page_verdicts(pages, original, literals):
    removed_pages = {f["file"] for f in literals} - {f["file"] for f in original if f not in literals}
    return [{**p, "verdict": "ok"} if p["file"] in removed_pages and p["verdict"] == "changes"
            else p for p in pages]


def owner_updates(repo):
    """Pure migration output: only open findings on fixed literals leave the writer queue."""
    from . import files, relations
    for path in files.review_files(repo):
        rel = path.relative_to(repo).as_posix()
        text = safefs.read_text(repo, rel)
        page = frontmatter.split(text)
        items, details = dict(page.meta.get("items", {})), dict(page.meta.get("item_details", {}))
        changed = []
        for key, status in sorted(items.items()):
            item = relations.details(text, key)
            source = item.get("file", "")
            if status != "open" or not source.endswith(".md") or not safefs.is_file(repo, source):
                continue
            if only_literals(safefs.read_text(repo, source), item.get("quote", "")):
                items[key] = "owner"
                details[key] = {**item, "tool_reason": "Rögzített tool-szöveg; a sablon javítása szükséges."}
                changed.append(key)
        if changed:
            yield rel, frontmatter.set_keys(text, {"items": items, "item_details": details,
                                                   "status": files.compute_status(items)})
