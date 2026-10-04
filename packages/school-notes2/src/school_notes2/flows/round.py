"""Hourly sequential rounds, in configuration table order."""

from datetime import datetime

from ..log import TZ
from ..state import phase
from ..state.files import read_json, write_json
from . import context, nightly, operation, run


def now():
    return datetime.now(TZ)


def due(ctx, started, state):
    task = phase.open_task(ctx.task_root(), ctx.name, "review")
    if task is not None and task.data.get("needs_owner"):
        return False
    if task is not None and task.get("timeout_day") == started.date().isoformat():
        return False
    if task is not None and not task.data.get("needs_owner"):
        return True
    return (started.strftime("%H:%M") >= ctx.cfg.nightly_after
            and state.get(ctx.name) != started.date().isoformat())


def round(cfg):
    contexts = [context.make(cfg, name) for name in cfg.students]
    if not contexts:
        return 0
    with operation.admission(contexts[0], "round") as acquired:
        if not acquired:
            return 0
        while True:
            started = now()
            _cycle(cfg, contexts, started)
            # Coalesce missed hours into ONE successor, never replay a backlog.
            if int(now().timestamp() // 3600) <= int(started.timestamp() // 3600):
                return 0


def _cycle(cfg, contexts, started):
    path = cfg.state_dir / "round.json"
    state = read_json(path, {})
    nights = state.get("nightly_started", {})
    cache = {}
    state = {"started": started.isoformat(), "status": "running", "nightly_started": nights}
    write_json(path, state)
    for kind, action in (("nightly", nightly.nightly), ("run", run.run)):
        for ctx in contexts:
            if kind == "nightly" and not due(ctx, started, nights):
                continue
            # A busy learner has not started its night; leave it due next round.
            if not ctx.lock().probe():
                ctx.log.event("round.skip", "learner_locked", target=ctx.name)
                run._lock_alert(ctx, ctx.lock().holder())
                continue
            state.update(step=kind, learner=ctx.name)
            write_json(path, state)
            with operation.scope(ctx, cache=cache):
                action(ctx)
            if kind == "nightly":
                nights[ctx.name] = started.date().isoformat()
                write_json(path, state)
    state.update(status="done", finished=now().isoformat())
    write_json(path, state)
