"""One-time chain policy upgrade; only private tool reports change."""

from ..figures import migration_gate
from ..state import safefs
from ..wiki import frontmatter
from . import attempts, files, relations

POLICY = 1
REASON = "elavult: az ábra elkészült vagy újra sorban van"


def updates(repo):
    known = None
    owners = {e["commission"]["id"] for e in safefs.read_json(repo, migration_gate.PATH, [])
              if e.get("owner_required") is True}
    for path in files.review_files(repo):
        page = files.read_report(repo, path)
        if page is None or not isinstance(page.meta.get("items"), dict) or page.meta.get("repair_policy") == POLICY:
            continue
        if known is None:
            known = relations.inventory(repo)
        items, details = dict(page.meta["items"]), dict(page.meta.get("item_details", {}))
        for key, status in sorted(items.items()):
            detail = relations.details(page, key)
            if status != "owner" or "repair_attempts" in detail:
                continue
            if detail.get("origin") == "figure":
                if detail.get("figure_id") not in owners:
                    items[key] = "settled"
                    detail["migration_note"] = REASON
            elif detail["chain"] == 1 and not attempts.decision(detail, known) and not detail.get("tool_reason"):
                items[key] = "open"
                detail.update(repair_attempts=0, repair_runs=[])
            details[key] = detail
        yield path.relative_to(repo).as_posix(), frontmatter.set_keys(page, {
            "items": items, "item_details": details, "status": files.compute_status(items),
            "repair_policy": POLICY})
