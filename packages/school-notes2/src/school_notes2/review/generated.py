"""Route findings about tool-owned text to private template feedback."""

import re

from ..state import safefs
from ..wiki import markers


def matches(text, quote):
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    return list(re.finditer(pattern, text)) if pattern else []


def only_generated(text, quote):
    found = matches(text, quote)
    blocks = markers.spans(text)
    return bool(found) and all(any(start <= m.start() and m.end() <= end
                                   for start, end, _ in blocks) for m in found)


def partition(repo, findings, notes):
    kept, feedback = [], []
    for finding in findings:
        path = finding["file"]
        text = safefs.read_text(repo, path) if safefs.is_file(repo, path) else ""
        if not only_generated(text, finding.get("quote", "")):
            kept.append(finding)
            continue
        feedback.append(f"Tool-sablon ({path}): {finding['problem']} "
                        f"Idézet: {finding['quote']} Javaslat: {finding.get('suggestion', '')}")
    return kept, list(notes) + sorted(set(" ".join(n.split()) for n in feedback))


def page_verdicts(pages, original, kept):
    removed_pages = {f["file"] for f in original} - {f["file"] for f in kept}
    return [{**p, "verdict": "ok"} if p["file"] in removed_pages and p["verdict"] == "changes"
            else p for p in pages]
