"""Replayable request filing in the existing content phase; no license wait or new phase."""

from ..figures import requests
from ..state import safefs
from ..wiki.public import dumps
from . import journal


def refresh(ctx, task, result, pages=()):
    journal.settle(ctx, task)
    value = requests.collect(ctx.notes_path, result.get("figure_requests", []), pages)
    if not value and not safefs.is_file(ctx.notes_path, requests.PATH):
        return
    text = dumps(value)
    if not safefs.is_file(ctx.notes_path, requests.PATH) or safefs.read_text(ctx.notes_path, requests.PATH) != text:
        journal.write(ctx, task, requests.PATH, text, whole=True)


def for_fetch(repo, fetch):
    from ..review import relations
    allowed = None
    if fetch["mode"] == "repair":
        allowed = {t["page"] for t in fetch["repair_targets"]}
    elif fetch["mode"] == "fix":
        allowed = {relations.details(safefs.read_text(repo, i["file"]), i["item_id"]).get("file")
                   for i in fetch["open_review_items"]}
    subjects = {p["subject"] for p in fetch["packages"]}
    if fetch.get("subject"):
        subjects = {fetch["subject"]}
    return [r for r in requests.approved(repo)
            if (allowed is None or r["page"] in allowed)
            and (fetch["mode"] == "interactive" or allowed is not None or r["page"].split("/")[1] in subjects)]
