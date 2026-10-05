"""Freeze legacy pending bookkeeping until its explicit migration has run."""

from ..notify import Notice, pending as owner_notices
from ..state import safefs

MARK = "docs/figure-pending-migrations.json"
PATH = "docs/figure-pending.json"


def blocked(repo):
    return not safefs.is_file(repo, MARK) and bool(safefs.read_json(repo, PATH, []))


def notify(ctx, repo):
    if not blocked(repo):
        return False
    message = "a függő ábrák migrációja még nem futott le"
    ctx.log.event("figure.migration_required", message)
    owner_notices.send(ctx, Notice(ctx.name, "figure-pending-migration", "", "figures", "migráció",
        message, f"Futtasd a függő ábrák migrációját: python -m school_notes2.figures.migrate_pending {ctx.name}"))
    return True


def concerns(repo, finding):
    if not blocked(repo):
        return False
    from .commissions import MARKER
    from ..wiki.pages import links, resolve
    ids = {m[1] for m in MARKER.finditer(finding.get("quote", ""))}
    ids.add(finding.get("figure_id", finding.get("id")))
    assets = {finding.get("asset"), finding.get("file")}
    assets.update(resolve(finding.get("file", ""), link.target)
                  for link in links(finding.get("quote", "")) if link.image)
    for entry in safefs.read_json(repo, PATH, []):
        brief = entry["commission"]
        if brief["id"] in ids or brief.get("replaces") and brief["replaces"] in assets:
            return True
    return False
