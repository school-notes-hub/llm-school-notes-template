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


def refresh_svgs(ctx, task):
    """A provenance receipt (path, sha256, run id) for every SVG under wiki/assets that this
    run created or changed and the tool did not write; only such an SVG is `authored`."""
    from ..wiki.pages import sha256
    from ..wiki.rights import SVG_RECEIPTS
    from . import steps
    repo = ctx.notes_path
    if not safefs.exists(repo, ".git"):
        return
    journal.settle(ctx, task)
    svgs = [p for p in steps.changed_paths(ctx, task) if p.startswith("wiki/assets/") and p.endswith(".svg")
            and p not in task.get("tool_writes", {}) and safefs.is_file(repo, p)]
    if not svgs:
        return
    old = safefs.read_json(repo, SVG_RECEIPTS, {}) if safefs.is_file(repo, SVG_RECEIPTS) else {}
    entries = {(e["path"], e["sha256"]): e for e in old.get("svgs", [])}
    for rel in svgs:
        entries.setdefault((rel, sha256(repo, rel)), {"path": rel, "sha256": sha256(repo, rel), "run_id": task.run_id})
    text = dumps({"rights": "authored", "svgs": [entries[k] for k in sorted(entries)]})
    if not safefs.is_file(repo, SVG_RECEIPTS) or safefs.read_text(repo, SVG_RECEIPTS) != text:
        journal.write(ctx, task, SVG_RECEIPTS, text, whole=True)


def changed_svgs(ctx, task):
    """The SVGs the run under way changed: accepted by the writer's own check (MCP)."""
    from . import steps
    if not safefs.exists(ctx.notes_path, ".git"):
        return []
    return [p for p in steps.changed_paths(ctx, task) if p.startswith("wiki/assets/") and p.endswith(".svg")]
