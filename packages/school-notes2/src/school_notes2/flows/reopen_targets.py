"""Where each `status --reopen` target goes (fix-52): an owner item, a drawn owner figure, a
generated owner image with `--paid` (only when its paid attempts are used up), or a figure that
is only parked and not used up, whose parking is lifted without any paid frame. Every refused
target gets its own plain reason; the command records nothing then."""

from ..figures import pending as figure_pending
from ..review import files
from . import reopen


def sort(ctx, target, targets, paid, show, entries, found) -> str | None:
    """Sorts one target into `found`; returns why it cannot be taken, or None."""
    item, figure = reopen.ITEM.match(target), reopen.FIGURE.match(target)
    if item:
        status, detail = reopen.item_at(show, item[1], item[2])
        if status != files.OWNER:
            return f"not waiting for the owner ({status or 'no such item'})"
        found["items"].append(target)
        fid, own = detail.get("figure_id"), entries.get(detail.get("figure_id"))
        if (own and own["owner_required"] and "figure:" + fid not in targets
                and not figure_pending.generated_at(own["commission"], show)):
            found["figures"].append(fid)  # the item's own drawn figure is reopened with it
        return None
    if not figure:
        return "use docs/review/<file>.md#R<n> or figure:<id>"
    entry = entries.get(figure[1])
    if entry is None:
        return "no pending figure with this id on origin/main"
    kind, problem = _figure(ctx, figure[1], entry, paid, figure_pending.generated_at(entry["commission"], show))
    if kind:
        found[kind].append(figure[1])
        if kind == "paid":
            found["figures"].append(figure[1])
    return problem


def _figure(ctx, fid, entry, paid, generated) -> tuple[str | None, str | None]:
    """(where the figure goes, or the plain reason it cannot be taken)."""
    if entry["owner_required"]:
        if not generated:
            return (None, "a drawn figure costs nothing; reopen it without --paid") if paid else ("figures", None)
        if not paid:
            return None, ("a generated image; its paid attempts are in the image ledger. "
                          "With the owner's approval `--paid` opens one new frame of paid attempts")
        if not paid_used_up(ctx, fid):
            return None, ("waits for the owner, but its paid attempts are not used up "
                          "(another stop); --paid has nothing to approve")
        return "paid", None
    until = _parked_until(ctx, "figure:" + fid)
    from . import unjudged
    if fid in unjudged.stopped(ctx):
        # This stop holds the figure whether it is parked or not: lifting only the parking would
        # promise work that no run does (fix-52b).
        return None, (f"stopped after runs without a figure verdict: "
                      f"school-notes status --clear {ctx.name} unjudged --continue"
                      + (f"; it is also parked until {until[:16].replace('T', ' ')}: after the clear, "
                         f"school-notes status --reopen {ctx.name} figure:{fid}" if until else ""))
    if until:
        if used_up(ctx, entry, generated):
            return None, (f"parked until {until[:16].replace('T', ' ')}, and its attempts are used up: freeing it "
                          "brings no new attempt; a run after the parking hands it to the owner"
                          + (", then --paid" if generated else ""))
        return "unpark", None
    return None, "not waiting for the owner and not parked: the next fix run works on it; nothing to reopen"


def _parked_until(ctx, key) -> str | None:
    from ..state.files import read_json
    from . import fix_progress
    return read_json(fix_progress.path(ctx), {}).get(key) if key in fix_progress.parked(ctx) else None


def used_up(ctx, entry, generated) -> bool:
    """The figure's attempts are used up: freeing it from parking brings no new attempt."""
    if generated:
        return paid_used_up(ctx, entry["commission"]["id"])
    return entry["runs"] >= 3 and not entry.get("review_pending")


def paid_used_up(ctx, fid) -> bool:
    """The image's current frame of paid attempts is exhausted (`generate.exhausted`): a
    candidate still waiting for its verdict is not used up."""
    from ..images import plans
    from ..images.generate import exhausted
    settings = ctx.image_settings()
    job = settings.ledger().get("jobs", {}).get(plans.job_id(settings.learner, fid))
    return bool(job) and exhausted(job, settings.max_attempts)
