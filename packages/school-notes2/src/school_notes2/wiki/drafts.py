"""Persistent draft age, reset only by an additional linked lesson (repair plan 7.11)."""

from datetime import date
from pathlib import Path

from . import lesson_log
from .decisions import valid_date
from .pages import PageError, read_page, resolve, wiki_pages

KEY = "draft_tracking"


def lesson_keys(repo: Path, skip=()) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for rel in sorted(set(wiki_pages(repo)) - set(skip)):
        meta = read_page(repo, rel).meta
        if not lesson_log.is_lesson(rel, meta):
            continue
        lessons = meta.get("lessons")
        if not isinstance(lessons, list) or any(not isinstance(lesson, dict) or
                not isinstance(lesson.get("topics", []), list) for lesson in lessons):
            raise PageError(rel, ["lessons must be a list of mappings with topic lists"])
        for n, lesson in enumerate(lessons):
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


def warnings(repo: Path, today: date, *, paths: list[str] | None = None) -> list[tuple[str, str]]:
    linked = lesson_keys(repo)
    out = []
    available = set(wiki_pages(repo))
    for rel in sorted(available if paths is None else available.intersection(paths)):
        meta = read_page(repo, rel).meta
        if meta.get("status") != "draft" or problems(meta):
            continue
        state = tracking(meta, linked.get(rel, []), today)
        if (today - date.fromisoformat(state["since"])).days > 14:
            out.append((rel, "draft is more than 14 days old without a new lesson; "
                             "resolve it or explain why it remains draft"))
    return out
