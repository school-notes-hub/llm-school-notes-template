"""Mechanical content-protection checks for a repair; semantic coverage stays with review."""

import re

from ..state import safefs
from ..wiki import frontmatter, pages
from ..wiki import check as wiki_check
from ..wiki.check import item


def problems(ctx, task, paths):
    if task.get("mode") != "repair" or task.get("queue_only"):
        return []
    from ..flows.steps import _llm_part, base_of
    target = task.get("repair_targets")[0]
    allowed = {target["page"], *target["related"]}
    out = []
    for rel in paths:
        if not rel.startswith("wiki/") or rel == "wiki/log.md" or rel.startswith("wiki/assets/"):
            continue
        raw = ctx.worktree("notes").run("show", f"{base_of(task)}:{rel}", check=False)
        before = raw.stdout.decode("utf-8") if raw.returncode == 0 else ""
        after = safefs.read_text(ctx.notes_path, rel) if safefs.is_file(ctx.notes_path, rel) else ""
        if _llm_part(before) == _llm_part(after):
            continue
        if rel not in allowed:
            out.append(item(rel, None, "repair: page is outside the assigned target and related pages"))
            continue
        old, new = frontmatter.split(before).meta, frontmatter.split(after).meta
        for key in ("lessons", "date_note", "topics"):
            if old.get(key) != new.get(key):
                out.append(item(rel, None, f"repair: preserve existing {key}"))
        anchors = re.findall(r'<!--\s*q:\s*[^>]+-->|<a\s+[^>]*(?:id|name)=[^>]+>\s*</a>', before)
        if any(a not in after for a in anchors):
            out.append(item(rel, None, "repair: preserve existing anchors"))
        if rel != target["page"] and target["kind"] not in ("lesson-notes", "chapter-summary", "review"):
            if _without_links(_llm_part(before)) != _without_links(_llm_part(after)):
                out.append(item(rel, None, "repair: related lesson logs and summaries allow only link adjustments"))
    return out


def _without_links(text):
    # Link labels are prose and stay intact; only their destinations may change.
    return pages.LINK.sub(lambda m: m[0].replace(m["target"], "<target>"), text)


def coverage(result, fetch):
    targets = fetch.get("repair_targets", [])
    if not targets or targets[0]["kind"] != "lesson-notes" or result.get("status") != "done":
        return []
    ledger = result.get("coverage", [])
    if not ledger or not result.get("checks"):
        return [item(".school-notes/result.json", None,
                     "repair: shortening a lesson log requires item coverage and checks")]
    return []


def inherited_learning_problems(ctx, task, paths):
    """A link-only adjustment cannot force the separate lesson-log rewrite forward."""
    if task.get("mode") != "repair" or task.get("queue_only"):
        return set()
    from ..flows.steps import _llm_part, base_of
    target = task.get("repair_targets")[0]
    if target["kind"] in ("lesson-notes", "chapter-summary", "review"):
        return set()
    inherited = set()
    for rel in sorted(set(paths) & set(target["related"])):
        raw = ctx.worktree("notes").run("show", f"{base_of(task)}:{rel}", check=False)
        if raw.returncode != 0 or not safefs.is_file(ctx.notes_path, rel):
            continue
        before, after = raw.stdout.decode(), safefs.read_text(ctx.notes_path, rel)
        if _without_links(_llm_part(before)) != _without_links(_llm_part(after)):
            continue
        old = wiki_check.check_learning(ctx.notes_path, rel, frontmatter.split(before))
        inherited.update((rel, i["message"]) for i in old)
    return inherited
