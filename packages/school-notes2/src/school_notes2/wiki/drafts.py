"""Persistent draft age, reset only by an additional linked lesson (repair plan 7.11)."""

from datetime import date
from pathlib import Path

from . import frontmatter, lesson_log, markers
from .decisions import valid_date
from .pages import read_page, resolve, wiki_pages

KEY = "draft_tracking"
NOTICE = "⏳ Ez a téma az órán folytatódik; a jegyzet az eddig tanult részt tartalmazza.\n"


def lesson_keys(repo: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in sorted(wiki_pages(repo)):
        meta = read_page(repo, rel).meta
        if not lesson_log.is_lesson(rel, meta):
            continue
        for n, lesson in enumerate(meta.get("lessons") or []):
            if not isinstance(lesson, dict):
                continue
            key = f"{rel}#{n}"
            targets = [rel] + [resolve(rel, str(t).split("#", 1)[0])
                               for t in lesson.get("topics") or []]
            for target in targets:
                if target:
                    found.setdefault(target, []).append(key)
    return {rel: sorted(set(keys)) for rel, keys in sorted(found.items())}


def tracking(meta: dict, lessons: list[str], today: date) -> dict:
    old = meta.get(KEY) or {}
    previous = old.get("lessons", [])
    since = old.get("since")
    if not since or set(lessons) - set(previous):
        since = today.isoformat()
    return {"since": str(since), "lessons": sorted(set(previous) | set(lessons))}


def problems(meta: dict) -> list[str]:
    if KEY not in meta:
        return []
    state = meta[KEY]
    if not isinstance(state, dict) or set(state) != {"since", "lessons"} \
            or not valid_date(state["since"]) or not isinstance(state["lessons"], list) \
            or any(not isinstance(key, str) for key in state["lessons"]):
        return ["invalid tool-written draft_tracking (since date and lessons list required)"]
    if state["lessons"] != sorted(set(state["lessons"])):
        return ["draft_tracking lessons must be unique and sorted"]
    return []


def update(text: str, lessons: list[str], today: date) -> str:
    meta = frontmatter.split(text).meta
    if meta.get("status") == "draft":
        text = frontmatter.set_keys(text, {KEY: tracking(meta, lessons, today)})
        if markers.read(text, "pending") in (None, "", NOTICE):
            text = lesson_log.after_header(text, "pending", NOTICE)
        return text
    if KEY in meta:
        text = frontmatter.set_keys(text, {}, remove=(KEY,))
    # Keep the empty tool block, as with other generated wiki blocks.
    if markers.read(text, "pending") == NOTICE:
        text = markers.replace(text, "pending", "")
    return text


def warnings(repo: Path, today: date) -> list[tuple[str, str]]:
    linked = lesson_keys(repo)
    out = []
    for rel in sorted(wiki_pages(repo)):
        meta = read_page(repo, rel).meta
        if meta.get("status") != "draft" or problems(meta):
            continue
        state = tracking(meta, linked.get(rel, []), today)
        if (today - date.fromisoformat(state["since"])).days > 14:
            out.append((rel, "draft is more than 14 days old without a new lesson; "
                             "resolve it or explain why it remains draft"))
    return out
