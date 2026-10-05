"""Pinned, content-derived nightly ranges; no size or commit-count cutoff."""

import difflib
import json
import re
from functools import cache

from ..figures import commissions
from ..wiki.author import part
from ..reader import units
from ..state import safefs
from ..schemas import validate
from ..wiki import frontmatter
from ..wiki.pages import resolve, wiki_pages
from . import nightly, relations

STATE = "docs/review/nightly-state.json"


def text(repo, commit, path):
    proc = repo.run("show", f"{commit}:{path}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""


def is_fix(repo, commit):
    return "School-Notes-Run: fix" in repo.out("show", "-s", "--format=%B", commit).splitlines()


def author_text(repo, commit, path):
    """Retry markers are tool output, even when the nightly report is in the range."""
    value = text(repo, commit, path)
    raw = text(repo, commit, "docs/figure-pending.json")
    entries = json.loads(raw) if raw else []
    for entry in entries:
        brief = entry["commission"]
        if brief["page"] == path and brief["id"].startswith("retry-"):
            for kind in ("figure", "image"):
                value = value.replace(f"<!-- {kind}: {brief['id']} -->\n\n", "")
    return part(value)


def author_changes(repo, base, head):
    result = []
    for status, path in sorted(nightly.changed(repo, base, head, ("wiki",))):
        if status == "D":
            continue
        if path.endswith(".md"):
            if author_text(repo, base, path) == author_text(repo, head, path):
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


def asset_pages(work):
    """Render companions share the embedding pages of the published output."""
    related = relations.related_pages(work)
    result = {path: set(pages) for path, pages in related.items()}
    for receipt in sorted(safefs.glob(work, "wiki/assets", "wiki/assets/**/render.json")):
        folder = receipt.rsplit("/", 1)[0]
        companions = set(safefs.glob(work, folder, folder + "/*"))
        try:
            value = safefs.read_json(work, receipt, {})
        except (OSError, ValueError):
            value = {}
        if isinstance(value, dict):
            source, outputs = value.get("source"), value.get("outputs", {})
            if isinstance(source, str):
                companions.add(resolve("x", source))
            if isinstance(outputs, dict):
                companions.update(resolve(receipt, name) for name in outputs)
        companions = {p for p in companions if p and p.startswith("wiki/assets/")}
        pages = set().union(*(related.get(p, set()) for p in sorted(companions)))
        for path in sorted(companions):
            result.setdefault(path, set()).update(pages)
    return result


def affected(repo, work, base, head):
    changed = author_changes(repo, base, head)
    related, published = asset_pages(work), set(wiki_pages(work))
    closures = closure_changes(repo, base, head)
    pages, assets = set(), {}
    for path in sorted(set(changed) | {item.get("file", "") for item in closures.values()}):
        if path in published:
            pages.add(path)
        elif not path.endswith(".md") and related.get(path):
            # A shared image belongs to its first primary topic, by path.
            page = min(related[path], key=lambda p: (commissions.topic(work, p), p))
            pages.add(page)
            assets[path] = page
    grouped = units.collect(work, sorted(pages))
    for unit in grouped:
        unit["changed"] = sorted(pages & set(unit["pages"]))
        unit["context"] = sorted(set(unit["context"]) | {
            path for path, page in assets.items() if page in unit["pages"]})
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
        blobs = [repo.run("show", f"{commit}:{path}", check=False).stdout
                 for commit in (unit["base"], head)]
        if blobs[0] == blobs[1]:
            continue
        if any(nightly._text(data, path) is None for data in blobs):
            out.append(f"Binary file {path}\n")
            continue
        old, new = (data.decode("utf-8", "replace") for data in blobs)
        if path.endswith(".md"):
            old, new = part(old), part(new)
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


def unblocked(entries, state_dir, learner):
    """Forget failures/blocks cleared by the owner, consistently in run and status."""
    from ..state.files import read_json
    cleared = read_json(state_dir / learner / "nightly-cleared.json", {}).get("at", "")
    return sorted((e for e in entries if not cleared or e.get("at", "") > cleared),
                  key=lambda e: e["topic"])
