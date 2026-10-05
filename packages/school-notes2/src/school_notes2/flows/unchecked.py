"""Pages whose independent check (P3 reader or P5 recheck) did not run.

A failed call never lets a change out unchecked: the page is recorded with the commit its
check measures from, the release is held (the notes commit is still pushed), and the next run
of any kind rechecks the page against that commit. A page leaves the list when a recheck ran.
A run for these pages alone starts at most once a round (fix-49). After `LIMIT` failed rechecks
no such run starts any more: the owner gets one mail (`unchecked-limit`) and lifts it with
`school-notes status --clear <learner> unchecked --continue`."""

from ..log import now_iso
from ..state.files import read_json, write_json

LIMIT = 3


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "unchecked.json"


def load(ctx) -> dict:
    return read_json(path(ctx), {})


def old_text(ctx, page: str) -> str | None:
    """The page as it was at the carried base; None when the page is not carried."""
    entry = load(ctx).get(page)
    if entry is None:
        return None
    proc = ctx.worktree("notes").run("show", f"{entry['base']}:{page}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""


def base(ctx, task, page: str) -> str:
    return load(ctx).get(page, {}).get("base") or task.get("base")


def update(ctx, task, failed: dict[str, str], checked: set[str]) -> None:
    """`failed`: page → base of the check that did not run; `checked`: pages checked now."""
    state = load(ctx)
    new = {p: e for p, e in state.items() if p not in checked or p in failed}
    for page, commit in sorted(failed.items()):
        entry = dict(new.get(page) or {"base": commit, "tries": 0})
        if entry.get("run_id") != task.run_id:  # a replayed step counts once
            entry.update(tries=entry["tries"] + 1, run_id=task.run_id, at=now_iso())
        new[page] = entry
    if new != state:
        write_json(path(ctx), dict(sorted(new.items())))
    if failed:
        ctx.log.event("inspection.unchecked", "warning", pages=sorted(failed))
    if set(state) - set(new):
        ctx.log.event("inspection.rechecked", pages=sorted(set(state) - set(new)))
    notify(ctx)


def startable(ctx) -> bool:
    """A run for carried pages alone starts only while a recheck may still succeed."""
    return any(e.get("tries", 0) < LIMIT for e in load(ctx).values())


def exhausted(ctx) -> list[str]:
    return sorted(p for p, e in load(ctx).items() if e.get("tries", 0) >= LIMIT)


def notify(ctx) -> None:
    """One mail while a page waits for the owner after `LIMIT` failed rechecks; over when it
    was rechecked or the owner reset the tries."""
    from ..notify import incidents
    if exhausted(ctx):
        incidents.record(ctx, "unchecked_limit", "unchecked", scope=SCOPE)
    else:
        incidents.resolve(ctx, SCOPE)


SCOPE = "unchecked-limit"


def reset(ctx) -> list[str]:
    """The owner's `--clear <learner> unchecked --continue`: every page gets its tries back."""
    state = load(ctx)
    pages = exhausted(ctx)
    if state:
        write_json(path(ctx), {p: {k: v for k, v in e.items() if k != "run_id"} | {"tries": 0}
                               for p, e in sorted(state.items())})
    ctx.log.event("owner.unchecked_reset", pages=pages)
    notify(ctx)
    return pages
