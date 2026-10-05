"""Mechanical content-protection checks for a repair; semantic coverage stays with review."""

import re

from ..state import safefs
from ..wiki import author, frontmatter, markers, pages
from ..wiki.check import item


def problems(ctx, task, paths):
    if task.get("mode") != "repair" or task.get("queue_only"):
        return []
    from ..flows.steps import base_of
    from ..wiki.author import part
    target = task.get("repair_targets")[0]
    allowed = {target["page"], *target["related"]}
    out = []
    for rel in paths:
        if not rel.startswith("wiki/") or rel == "wiki/log.md" or rel.startswith("wiki/assets/"):
            continue
        raw = ctx.worktree("notes").run("show", f"{base_of(task)}:{rel}", check=False)
        before = raw.stdout.decode("utf-8") if raw.returncode == 0 else ""
        after = safefs.read_text(ctx.notes_path, rel) if safefs.is_file(ctx.notes_path, rel) else ""
        if part(before) == part(after):
            continue
        if rel not in allowed:
            out.append(item(rel, None, "repair: page is outside the assigned target and related pages"))
            continue
        old, new = frontmatter.split(before).meta, frontmatter.split(after).meta
        for key in ("lessons", "date_note", "topics"):
            if _protected(key, old.get(key)) != _protected(key, new.get(key)):
                out.append(item(rel, None, f"repair: preserve existing {key}" + (" (only materials may change)" if key == "lessons" else "")))
        anchors = re.findall(r'<!--\s*q:\s*[^>]+-->|<a\s+[^>]*(?:id|name)=[^>]+>\s*</a>', before)
        if any(a not in after for a in anchors):
            out.append(item(rel, None, "repair: preserve existing anchors"))
        if rel != target["page"] and target["kind"] not in ("lesson-notes", "chapter-summary", "review"):
            if not _related_equal(before, after):
                out.append(item(rel, None, "repair: related lesson logs and summaries allow only link adjustments"))
    return out


def _protected(key, value):
    """A repair may add or correct `lessons[].materials` (plan 7.3: the writer names the teacher
    material of old lesson logs); every other lesson field stays as it was."""
    if key == "lessons" and isinstance(value, list):
        return [{k: v for k, v in lesson.items() if k != "materials"} if isinstance(lesson, dict) else lesson
                for lesson in value]
    return value


def _related_equal(before, after):
    """Ignore only separator changes at a generated notice's former/current position."""
    old, new = (_linkless(author.part(text)) for text in (before, after))
    old_lines, old_gaps = _lines(old.body)
    new_lines, new_gaps = _lines(new.body)
    if old.meta != new.meta or old_lines != new_lines:
        return False
    allowed = set()
    for text in (before, after):
        for start, _, name in markers.spans(text):
            if markers.is_notice(name):
                prefix = frontmatter.split(author.part(text[:start])).body
                allowed.add(len(_lines(prefix)[0]))
    return all(old_gaps.get(i, 0) == new_gaps.get(i, 0) or i in allowed
               for i in old_gaps.keys() | new_gaps.keys())


def _linkless(text):
    # Link labels are prose and stay intact; only their destinations may change.
    return frontmatter.split(pages.LINK.sub(lambda m: m[0].replace(m["target"], "<target>"), text))


def _lines(body):
    lines, gaps, fence = [], {}, None
    for line in body.splitlines():
        mark = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if mark:
            if fence is None:
                fence = mark[1]
            elif mark[1][0] == fence[0] and len(mark[1]) >= len(fence):
                fence = None
        if line.strip() or fence:
            lines.append(line)
        else:
            gaps[len(lines)] = gaps.get(len(lines), 0) + 1
    return lines, gaps


def coverage(result, fetch):
    targets = fetch.get("repair_targets", [])
    if not targets or targets[0]["kind"] != "lesson-notes" or result.get("status") != "done":
        return []
    ledger = result.get("coverage", [])
    if not ledger or not result.get("checks"):
        return [item(".school-notes/result.json", None,
                     "repair: shortening a lesson log requires item coverage and checks")]
    return []
