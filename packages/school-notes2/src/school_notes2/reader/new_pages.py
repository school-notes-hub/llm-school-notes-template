"""Proof that a reader page was first authored in a v2 writer run."""

import json

from ..state import safefs
from ..wiki import frontmatter

PATH = "docs/review/new-pages.json"
TYPES = {"topic", "lesson-notes", "summary", "review"}


def eligible(repo, page):
    return page in safefs.read_json(repo, PATH, {}) and reader_page(repo, page)


def reader_page(repo, page):
    return (page.startswith("wiki/") and page.endswith(".md") and
            safefs.is_file(repo, page) and
            frontmatter.split(safefs.read_text(repo, page)).meta.get("type") in TYPES)


def record(ctx, task):
    from ..flows import journal, steps
    journal.settle(ctx, task)
    previous = safefs.read_json(ctx.notes_path, PATH, {})
    saved = {p: value for p, value in previous.items() if safefs.is_file(ctx.notes_path, p)}
    base = steps.base_reader(ctx, task)
    for page in sorted(steps.llm_snapshot(ctx, task)):
        if reader_page(ctx.notes_path, page) and base(page) is None:
            saved.setdefault(page, task.run_id)
    if saved != previous:
        journal.write(ctx, task, PATH, json.dumps(dict(sorted(saved.items())), ensure_ascii=False, indent=2) + "\n", whole=True)
