"""One-time chain policy upgrade; only private tool reports change."""

from ..figures import migration_gate
from ..state import safefs
from ..wiki import frontmatter
from . import attempts, files, relations

POLICY = 1
REASON = "elavult: a függő ábra újra sorban van"


def updates(repo):
    known = None
    migrated = safefs.read_json(repo, migration_gate.MARK, {}).get("version")
    waiting = {e["commission"]["id"] for e in safefs.read_json(repo, migration_gate.PATH, [])
               if not e.get("owner_required")}
    for path in files.review_files(repo):
        page = files.read_report(repo, path)
        if page is None or not isinstance(page.meta.get("items"), dict) or page.meta.get("repair_policy") == POLICY:
            continue
        if known is None:
            known = relations.inventory(repo)
        items, details = dict(page.meta["items"]), dict(page.meta.get("item_details", {}))
        for key, status in sorted(items.items()):
            detail = relations.details(page, key)
            if status != "owner" or detail.get("repair_attempts") is not None:
                continue
            if (migrated and detail.get("origin") == "figure" and detail.get("figure_id") in waiting):
                items[key] = "settled"
                detail["migration_note"] = REASON
            elif detail["chain"] == 1 and not attempts.decision(detail, known) and not detail.get("tool_reason"):
                items[key] = "open"
                detail.update(repair_attempts=0, repair_runs=[])
            details[key] = detail
        yield path.relative_to(repo).as_posix(), frontmatter.set_keys(page, {
            "items": items, "item_details": details, "status": files.compute_status(items),
            "repair_policy": POLICY})
