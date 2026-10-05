"""Old check errors become durable review work, never a strike against the writer."""

import hashlib
import json
import re
from collections import Counter

from ..git.check_base import Tree
from ..reader import report
from ..review import files, relations
from ..state import safefs
from ..wiki import check as wiki_check
from . import checks, journal

KIND = "inherited-check"
MESSAGE = "Régi hiba, nem a te feladatod, ha az oldal nincs a kiosztásodban: "


def key(problem):
    raw = json.dumps([problem["file"], problem["message"], problem.get("occurrence", 1)], ensure_ascii=False)
    return KIND + ":" + hashlib.sha256(raw.encode()).hexdigest()


def classify(ctx, task, items):
    items = numbered(items)
    errors = wiki_check.errors(items)
    if not errors:
        return items
    base = Tree(ctx.worktree("notes"), task.get("base"))
    paths = sorted({i["file"] for i in errors})
    old = {key(i) for i in numbered(wiki_check.errors(wiki_check.check_files(ctx.notes_path, paths, fs=base)))}
    inherited = [i for i in errors if key(i) in old]
    record(ctx, task, inherited)
    return [{**i, "severity": "warning", "kind": KIND, "id": key(i),
             "message": MESSAGE + i["message"]} if i in inherited else
            {k: v for k, v in i.items() if k != "occurrence"} if i in errors else i for i in items]


def numbered(items):
    counts, out = Counter(), []
    for i in checks.ordered(items):
        if i.get("severity", "error") == "error":
            pair = (i["file"], i["message"])
            counts[pair] += 1
            i = {**i, "occurrence": counts[pair]}
        out.append(i)
    return out


def restored(ctx, task, paths):
    """Restored pages are no longer changes, but their remaining defects need a home."""
    from . import steps
    unchanged = [p for p in sorted(set(paths)) if safefs.is_file(ctx.notes_path, p)
                 and steps.base_reader(ctx, task)(p) == safefs.read_bytes(ctx.notes_path, p)]
    if unchanged:
        classify(ctx, task, wiki_check.check_files(ctx.notes_path, unchanged, fix=False))


def record(ctx, task, problems):
    if not problems:
        return
    journal.settle(ctx, task)
    path = task.get("inspection_report") or f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    if safefs.is_file(ctx.notes_path, path):
        task.update(inspection_report=path)
    active = active_keys(ctx.notes_path)
    unique = {}
    for problem in checks.ordered(problems):
        unique.setdefault(key(problem), problem)
    findings = [{"file": i["file"], "problem": i["message"], "quote": "",
                 "origin": KIND, "category": "szerkezeti", "severity": "hiba",
                 "relates_to": None, "hit_id": k}
                for k, i in sorted(unique.items(), key=lambda entry: (entry[1]["file"], entry[1]["message"], entry[1].get("occurrence", 1)))
                if k not in active]
    if not findings:
        return
    write = lambda repo, rel, text: journal.write(ctx, task, rel, text, whole=True)
    if not safefs.is_file(ctx.notes_path, path):
        files.write_review(ctx.notes_path, task.data["created"][:10],
                           {"verdict": "ok", "findings": []}, "check", task.get("base"), task.get("base"),
                           path=ctx.notes_path / path, write=write)
    label = KIND + ":" + hashlib.sha256(json.dumps(findings, sort_keys=True).encode()).hexdigest()
    report.append(ctx.notes_path, path, findings, [], label, write=write)
    task.update(inspection_report=path)


def active_keys(repo):
    """Also recognize earlier reports whose exact problem has no machine hit ID yet."""
    keys, counts = set(), Counter()
    legacy = []
    for path in files.review_files(repo):
        page = files.read_report(repo, path)
        if page is None:
            continue
        for item_id, status in sorted(page.meta.get("items", {}).items()):
            if status not in ("open", "owner", "disagree"):
                continue
            info = relations.details(page, item_id)
            if info.get("hit_id"):
                keys.add(info["hit_id"])
                continue
            section = re.search(r"^### " + re.escape(item_id) + r" [^\n]*\n(.*?)(?=^###? |\Z)",
                                page.body, re.M | re.S)
            problem = re.search(r"^\*\*Probléma:\*\* (.+)$", section[1], re.M) if section else None
            if problem and info.get("file"):
                legacy.append((info["file"], problem[1]))
    for pair in sorted(legacy):
        while True:
            counts[pair] += 1
            value = key({"file": pair[0], "message": pair[1], "occurrence": counts[pair]})
            if value not in keys:
                keys.add(value)
                break
    return keys
