"""Read-only migration forecast using the same exact job identity as generation."""

import json

from ..images.generate import attempts_used, awaiting_review, exhausted
from ..images.plans import job_id
from ..state import safefs
from . import migrate_pending as migration, pending


def preview(ctx, repo):
    work = ctx.notes_path
    if safefs.read_json(work, migration.MARK, {}).get("version") == migration.VERSION:
        entries, texts = pending.load(work), {}
    else:
        texts, _ = migration.plan(work, repo)
        entries = json.loads(texts[pending.PATH])
    generated = [e for e in entries if is_generated(work, e["commission"], texts)]
    settings = ctx.image_settings() if generated else None
    ledger = settings.ledger() if settings else {"jobs": {}}
    result = []
    for entry in sorted(entries, key=lambda e: e["commission"]["id"]):
        brief = entry["commission"]
        key = job_id(settings.learner, brief["id"]) if entry in generated else None
        job = ledger.get("jobs", {}).get(key, {"attempts": []})
        owner = entry["owner_required"] or bool(key and exhausted(job, settings.max_attempts))
        exists = safefs.is_file(work, brief["page"])
        result.append({"id": brief["id"], "kind": brief["kind"], "job_id": key,
                       "paid_attempts_used": attempts_used(job), "owner_required": owner,
                       "assignable_after_migration": exists and not owner,
                       "free_recheck": bool(key and awaiting_review(job)), "page_exists": exists})
    return result


def is_generated(work, brief, texts):
    return brief["kind"] in ("banner", "infographic") or (
        safefs.is_file(work, brief["page"]) and f"<!-- image: {brief['id']} -->" in
        texts.get(brief["page"], safefs.read_text(work, brief["page"])))
