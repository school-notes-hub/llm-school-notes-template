"""Copy host image-ledger provenance once in the main content flow, never in a job."""

from ..state import safefs
from ..wiki.public import dumps
from . import journal


def outputs(settings):
    return sorted({a[key] for entry in settings.ledger()["jobs"].values()
                   if entry["learner"] == settings.learner
                   for a in entry["attempts"] if a.get("state") in ("generated", "accepted", "rejected")
                   for key in ("sha256", "preview_sha256") if a.get(key)})


def refresh(ctx, task):
    journal.settle(ctx, task)
    hashes = outputs(ctx.image_settings())
    if not hashes:
        return
    path = "docs/evidence/image-generation/ledger.json"
    text = dumps({"rights": "generated", "outputs": hashes})
    if not safefs.is_file(ctx.notes_path, path) or safefs.read_text(ctx.notes_path, path) != text:
        journal.write(ctx, task, path, text, whole=True)


def rights(ctx):
    from ..wiki.pages import sha256
    hashes = set(outputs(ctx.image_settings()))
    return lambda rel: ("generated", "host image ledger") if sha256(ctx.notes_path, rel) in hashes else None
