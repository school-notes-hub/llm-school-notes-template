"""Drawn pending figures the figure reviewer could not judge (fix-49b).

A run whose drawn candidate got no verdict is no try of the figure (REJT-17). A timeout has its
own brake (two in a row stop the run with one mail). Any other failure (format, crash, render)
would come back every day without end, so such runs are counted here, apart from the figure's
tries: after `LIMIT` of them the figure is not assigned any more and the owner gets one mail
(`unjudged-limit`); `school-notes status --clear <learner> unjudged --continue` gives the
figures back. A verdict ends the count."""

from ..log import now_iso
from ..state.files import read_json, write_json

LIMIT = 3
SCOPE = "unjudged-limit"


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "unjudged.json"


def load(ctx) -> dict:
    return read_json(path(ctx), {})


def update(ctx, run_id: str, unjudged: set[str], judged: set[str]) -> None:
    """`unjudged`: figures this run could not have judged (no timeout); `judged`: with a verdict."""
    state = load(ctx)
    new = {fid: e for fid, e in state.items() if fid not in judged or fid in unjudged}
    for fid in sorted(unjudged):
        runs = new.get(fid, {}).get("run_ids", [])
        if run_id not in runs:  # a replayed step counts once
            new[fid] = {"run_ids": sorted([*runs, run_id]), "at": now_iso()}
    if new != state:
        write_json(path(ctx), dict(sorted(new.items())))
    if unjudged:
        ctx.log.event("figure.unjudged", "warning", figures=sorted(unjudged))
    notify(ctx)


def stopped(ctx) -> list[str]:
    return sorted(fid for fid, e in load(ctx).items() if len(e["run_ids"]) >= LIMIT)


def notify(ctx) -> None:
    """One mail while a figure waits after `LIMIT` unjudged runs; over when it was judged or
    the owner gave the figures back."""
    from ..notify import incidents
    if stopped(ctx):
        incidents.record(ctx, "unjudged_limit", "figures", scope=SCOPE)
    else:
        incidents.resolve(ctx, SCOPE)


def reset(ctx) -> list[str]:
    """The owner's `--clear <learner> unjudged --continue`: every figure is assigned again."""
    figures = stopped(ctx)
    if load(ctx):
        write_json(path(ctx), {})
    ctx.log.event("owner.unjudged_reset", figures=figures)
    notify(ctx)
    return figures
