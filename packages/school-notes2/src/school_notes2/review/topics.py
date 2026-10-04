"""Pinned, content-derived nightly ranges; no size or commit-count cutoff."""

import difflib
import json
import re
from functools import cache

from ..figures import commissions
from ..flows.steps import _llm_part
from ..reader import units
from ..state import safefs
from ..schemas import validate
from ..wiki import frontmatter
from . import nightly, relations

STATE = "docs/review/nightly-state.json"


def text(repo, commit, path):
    proc = repo.run("show", f"{commit}:{path}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""


def is_fix(repo, commit):
    return "School-Notes-Run: fix" in repo.out("show", "-s", "--format=%B", commit).splitlines()


def author_changes(repo, base, head):
    result = []
    for status, path in sorted(nightly.changed(repo, base, head, ("wiki",))):
        if status == "D":
            continue
        if path.endswith(".md"):
            if _llm_part(text(repo, base, path)) == _llm_part(text(repo, head, path)):
                continue
        result.append(path)
    return result


def closure_changes(repo, base, head):
    """Initial reports are tool output; later status/closure changes are assignments."""
    found = {}
    for status, path in sorted(nightly.changed(repo, base, head, ("docs/review",))):
        if status == "D" or not path.endswith(".md"):
            continue
        old, new = text(repo, base, path), text(repo, head, path)
        if status == "A":
            # A report can be created and then closed within this same range.
            added = repo.out("log", "--reverse", "--format=%H", "--diff-filter=A",
                             f"{base}..{head}", "--", path).split()
            if not added:
                continue
            old = text(repo, added[0], path)
        before, after = frontmatter.split(old).meta, frontmatter.split(new).meta
        for item, state in sorted(after.get("items", {}).items()):
            details = relations.details(new, item)
            if state not in ("fixed", "disagree") or (state == "fixed" and details.get("recheck")) or (state == "disagree" and details.get("response")):
                continue
            # Also account for a new closure of a previously reopened item.
            if before.get("items", {}).get(item) != state or closure_signature(old, item) != closure_signature(new, item):
                found[path + "#" + item] = {**details, "status": state}
    return found


def affected(repo, work, base, head):
    changed = author_changes(repo, base, head)
    related = relations.related_pages(work)
    pages = set()
    for path in changed:
        if path.endswith(".md") and not path.startswith("wiki/assets/"):
            pages.add(path)
        elif path in related:
            # A shared image belongs to its first primary topic, by path.
            pages.add(min(related[path], key=lambda p: (commissions.topic(work, p), p)))
        else:
            pages.add(path)
    closures = closure_changes(repo, base, head)
    for item in closures.values():
        path = item.get("file", "")
        if path in related:
            pages.add(min(related[path], key=lambda p: (commissions.topic(work, p), p)))
        elif path:
            pages.add(path)
    grouped = units.collect(work, sorted(pages))
    covered = {p for u in grouped for p in u["pages"]}
    for path in sorted(pages - covered):
        if safefs.is_file(work, path):
            grouped.append({"topic": path, "pages": [path], "context": [],
                            "keys": {path: units.page_key(work, path)} if path.endswith(".md") else {}})
    for unit in grouped:
        unit["changed"] = sorted(pages & set(unit["pages"]))
    return sorted(grouped, key=lambda u: u["topic"])


def plan(repo, work, base, head, state):
    done = {r["topic"]: r["commit"] for r in state.get("done_topics", [])}
    blocked = {r["topic"]: r for r in state.get("blocked_topics", [])}
    @cache
    def ranges(a, b):
        return {u["topic"]: u for u in affected(repo, work, a, b)}

    @cache
    def history(start):
        return repo.out("rev-list", "--reverse", "--topo-order", f"{start}..{head}").split()

    @cache
    def touched_at(commit):
        parent = repo.out("rev-parse", f"{commit}^").strip()
        return ranges(parent, commit)

    result, skipped = [], []
    initial = set(ranges(base, head))
    for topic in sorted(initial | set(done) | set(blocked)):
        start = blocked.get(topic, {}).get("since_commit", done.get(topic, base))
        current = ranges(start, head).get(topic)
        if current is None:
            skipped.append(topic)
            continue
        touched = [commit for commit in history(start) if topic in touched_at(commit)]
        mode = "targeted" if touched and all(is_fix(repo, c) for c in touched) else "full"
        pages = current["changed"] if mode == "targeted" else current["pages"]
        pages = [p for p in pages if p.endswith(".md") and not p.startswith("wiki/assets/")]
        result.append({**current, "base": start, "mode": mode, "commits": touched,
                       "assigned_pages": pages, "blocked": topic in blocked})
    return result, skipped


def patch(repo, unit, head):
    out = []
    for path in sorted(set(unit["pages"] + unit["context"])):
        old, new = text(repo, unit["base"], path), text(repo, head, path)
        if path.endswith(".md"):
            old, new = _llm_part(old), _llm_part(new)
        out.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                         "a/" + path, "b/" + path))
    return "".join(line if line.endswith("\n") else line + "\n" for line in out)


def load(repo):
    return validated(safefs.read_json(repo, STATE, {"done_topics": [], "blocked_topics": []}))


def read_state(repo, head):
    return validated(json.loads(text(repo, head, STATE) or '{"done_topics": [], "blocked_topics": []}'))


def closure_signature(text, item):
    sections = re.split(r"(?m)^## Végrehajtva", text)[1:]
    return [(section.splitlines()[0], line) for section in sections for line in section.splitlines()
            if re.match(r"^\* " + re.escape(item) + r" – (?:javítva|nem ért egyet)", line)]


def validated(state):
    validate("nightly-state", state)
    for field in ("done_topics", "blocked_topics", "failed_topics"):
        names = [r["topic"] for r in state.get(field, [])]
        if len(names) != len(set(names)):
            raise ValueError(f"{field}: duplicate topic")
    return state
