"""Targeted reviews can create findings only on changed final lines."""

import difflib
import re


def changed(old, new):
    a, b = old.splitlines(), new.splitlines()
    return {n + 1 for tag, _, _, start, end in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            if tag != "equal" for n in range(start, end)}


def excerpts(old, new):
    numbers = changed(old, new)
    return [{"line": n, "text": line} for n, line in enumerate(new.splitlines(), 1) if n in numbers]


def partition(findings, old_text, new_text, pages):
    kept, notes = [], []
    for finding in findings:
        page, quote = finding["file"], finding.get("quote", "")
        text = new_text(page) if page in pages else ""
        pattern = r"\s+".join(re.escape(word) for word in quote.split())
        matches = list(re.finditer(pattern, text)) if pattern else []
        lines = set()
        if len(matches) == 1:
            match = matches[0]
            lines = set(range(text[:match.start()].count("\n") + 1, text[:match.end()].count("\n") + 2))
        if page in pages and len(matches) != 1:
            kept.append({**finding, "line": None, "unlocated": True})
        elif lines and lines & changed(old_text(page), text):
            kept.append(finding)
        else:
            notes.append(f"Célzott ellenőrzésen kívüli lelet ({page}): {finding['problem']} Idézet: {quote}")
    return kept, notes
