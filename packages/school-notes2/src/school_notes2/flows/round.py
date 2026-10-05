"""Hourly sequential rounds, in configuration table order."""

from datetime import datetime
from types import SimpleNamespace

from ..log import Log, TZ
from ..notify import Mailer
from ..state import phase
from ..state.files import read_json, write_json
from . import context, install_pending, nightly, operation, run


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
    day = started.date().isoformat()
    started_today = any(t.kind == "review" and t.data["created"][:10] == day
                        for t in phase.all_tasks(ctx.task_root(), ctx.name))
    return (started.strftime("%H:%M") >= ctx.cfg.nightly_after
            and state.get(ctx.name) != day and not started_today)


def round(cfg):
    contexts = _contexts(cfg)
    if not contexts:
        return 0
    with operation.admission(contexts[0], "round") as acquired:
        if not acquired:
            return 0
        while True:
            if install_pending.waiting(operation.vm_context(contexts[0])):
                return 0
            started = now()
            _cycle(cfg, contexts, started)
            # Coalesce missed hours into ONE successor, never replay a backlog.
            if int(now().timestamp() // 3600) <= int(started.timestamp() // 3600):
                return 0


def _contexts(cfg):
    contexts = []
    for name in cfg.students:
        try:
            contexts.append(context.make(cfg, name))
        except Exception as exc:
            from . import last_error
            log = Log(cfg.log_path, student=name)
            mailer = Mailer(cfg.secrets_dir / "msmtprc", cfg.email_to, cfg.state_dir / "notify.json",
                            log, cfg.timeouts.msmtp_s)
            fallback = SimpleNamespace(name=name, cfg=cfg, log=log, mailer=mailer)
            log.error("round.context", exc)
            last_error.record(fallback, "round", "program", exc)
    return contexts


def _cycle(cfg, contexts, started):
    path = cfg.state_dir / "round.json"
    state = read_json(path, {})
    nights = state.get("nightly_started", {})
    cache = {}
    state = {"started": started.isoformat(), "status": "running", "nightly_started": nights,
             "pending_learners": [ctx.name for ctx in contexts]}
    write_json(path, state)
    for kind, action in (("nightly", nightly.nightly), ("run", run.run)):
        for ctx in contexts:
            try:
                _step(ctx, kind, action, started, state, path, cache)
            except Exception as exc:
                ctx.log.error("round.step", exc, step=kind)
                from . import last_error
                last_error.record(ctx, kind, "round_step", exc)
            finally:
                if kind == "run":
                    state["pending_learners"].remove(ctx.name)
                    write_json(path, state)
    state.update(status="done", finished=now().isoformat())
    write_json(path, state)
    from .status_text import snapshot
    snapshot(cfg)


def _step(ctx, kind, action, started, state, path, cache):
    nights = state["nightly_started"]
    if kind == "nightly" and not due(ctx, started, nights):
        return
    # A busy learner has not started its night; leave it due next round.
    if not ctx.lock().probe():
        ctx.log.event("round.skip", "learner_locked", target=ctx.name)
        run._lock_alert(ctx, ctx.lock().holder())
        return
    previous = phase.open_task(ctx.task_root(), ctx.name, "review") if kind == "nightly" else None
    day = started.date().isoformat()
    resumed_older = previous is not None and previous.data["created"][:10] < day
    state.update(step=kind, learner=ctx.name)
    write_json(path, state)
    with operation.scope(ctx, cache=cache):
        result = action(ctx)
    if kind == "nightly" and result in (None, 0) and not resumed_older:
        # An empty night also consumes today; only an older continuation is exempt.
        nights[ctx.name] = day
        write_json(path, state)
