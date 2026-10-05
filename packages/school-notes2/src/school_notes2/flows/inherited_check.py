"""Old check errors become durable review work, never a strike against the writer."""

import hashlib
import json
import re
from collections import Counter

import yaml

from ..git.check_base import Tree
from ..reader import report
from ..review import attempts, files, relations
from ..state import safefs
from ..wiki import check as wiki_check
from ..wiki import frontmatter, lesson_log
from . import checks, journal

KIND = "inherited-check"
MESSAGE = "Régi hiba, önmagában nem blokkolja ezt a futást: "


def key(problem):
    raw = json.dumps([problem["file"], problem["message"], problem.get("occurrence", 1)], ensure_ascii=False)
    return KIND + ":" + hashlib.sha256(raw.encode()).hexdigest()


def classify(ctx, task, items, *, persist=False):
    items = numbered(items)
    errors = wiki_check.errors(items)
    if not errors:
        return items
    try:
        base = Tree(ctx.worktree("notes"), task.get("base"))
        paths = sorted({i["file"] for i in errors})
        previous = wiki_check.errors(wiki_check.check_files(ctx.notes_path, paths, fs=base))
        if any(i["message"].startswith("frontmatter is not valid YAML:") for i in previous):
            raise ValueError("invalid base YAML")
        inherited = unchanged(ctx.notes_path, base, errors, previous)
    except (ValueError, yaml.YAMLError):
        ctx.log.event("check.base", "warning", message="Base check unavailable; all errors remain blocking.")
        inherited = []
    if persist:
        record(ctx, task, inherited)
    return [{**i, "severity": "warning", "kind": KIND, "id": key(i),
             "message": MESSAGE + i["message"]} if i in inherited else
            {k: v for k, v in i.items() if k != "occurrence"} if i in errors else i for i in items]


def unchanged(repo, base, current, previous):
    """Counts cannot hide replacements, even if a new match precedes an old one."""
    old, new = {}, {}
    for fs, items, groups in ((base, previous, old), (safefs, current, new)):
        for i in items:
            text = fs.read_text(repo, i["file"]) if fs.is_file(repo, i["file"]) else ""
            lines, n = text.splitlines(), i.get("line")
            aggregate = i["message"].startswith("unbalanced ") or i["message"] in (
                "unpaired generated-block markers", "a generated block appears twice")
            content = lines[n - 1] if n and 0 < n <= len(lines) else text if aggregate else i["message"]
            groups.setdefault((i["file"], i["message"]), Counter())[content] += 1
    allowed = {pair for pair, counts in new.items() if counts <= old.get(pair, Counter())}
    return [i for i in current if (i["file"], i["message"]) in allowed]


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
        classify(ctx, task, wiki_check.check_files(ctx.notes_path, unchanged, fix=False), persist=True)


def record(ctx, task, problems):
    problems = [i for i in problems if not deferred_lesson(ctx, task, i["file"])]
    if not problems:
        return
    journal.settle(ctx, task)
    path = task.get("inspection_report") or f"docs/review/{task.data['created'][:10]}-{task.run_id}-run.md"
    if safefs.is_file(ctx.notes_path, path):
        task.update(inspection_report=path)
    reopen(ctx, task, {key(i) for i in problems})
    active = active_keys(ctx.notes_path)
    unique = {}
    for problem in checks.ordered(problems):
        unique.setdefault(key(problem), problem)
    findings = [{"file": i["file"], "problem": i["message"], "quote": quote(ctx.notes_path, i),
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


def quote(repo, problem):
    n = problem.get("line")
    if not n:
        return ""
    lines = safefs.read_text(repo, problem["file"]).splitlines() if safefs.is_file(repo, problem["file"]) else []
    return lines[n - 1] if 0 < n <= len(lines) else f"{n}. sor"


def deferred_lesson(ctx, task, path):
    if task.get("mode") != "repair":
        return False
    targets = task.get("repair_targets", [])
    if path in {t["page"] for t in targets} or not safefs.is_file(ctx.notes_path, path):
        return False
    return lesson_log.is_lesson(path, frontmatter.split(safefs.read_text(ctx.notes_path, path)).meta)


def reopen(ctx, task, hits):
    """Reopen the same finding; journal and attempt identity make replay idempotent."""
    from . import correction_round
    run_id = correction_round.identity(task, 1) if task.get("mode") == "fix" else task.run_id
    for path in files.review_files(ctx.notes_path):
        page = files.read_report(ctx.notes_path, path)
        if page is None:
            continue
        items, details = dict(page.meta.get("items", {})), dict(page.meta.get("item_details", {}))
        changed = False
        for item_id, status in sorted(items.items()):
            detail = relations.details(page, item_id)
            if status != "fixed" or detail.get("hit_id") not in hits:
                continue
            attempts.record(detail, run_id)
            items[item_id], details[item_id] = attempts.failed_status(detail), detail
            changed = True
        if changed:
            journal.write(ctx, task, path.relative_to(ctx.notes_path).as_posix(), frontmatter.set_keys(page, {
                "items": items, "item_details": details, "status": files.compute_status(items)}), whole=True)
