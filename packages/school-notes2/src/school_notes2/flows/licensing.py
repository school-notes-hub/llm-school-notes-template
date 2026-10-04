"""Replayable request filing in the existing content phase; no license wait or new phase."""

from ..figures import requests
from ..state import safefs
from ..wiki.public import dumps
from . import learning


def refresh(ctx, task, result, pages=()):
    learning._settle_pending(ctx, task)
    value = requests.collect(ctx.notes_path, result.get("figure_requests", []), pages)
    if not value and not safefs.is_file(ctx.notes_path, requests.PATH):
        return
    text = dumps(value)
    if not safefs.is_file(ctx.notes_path, requests.PATH) or safefs.read_text(ctx.notes_path, requests.PATH) != text:
        learning._write(ctx, task, requests.PATH, text, whole=True)
