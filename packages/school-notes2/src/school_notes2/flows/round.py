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
    from . import transient_retry
    if task is not None and not transient_retry.ready(task):
        return False
    if task is not None and task.data.get("needs_owner"):
        return task.data["needs_owner"]["class"] == "transient"
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
            progressed = _cycle(cfg, contexts, started)
            # Coalesce missed hours into ONE successor, never replay a backlog.
            if not progressed and int(now().timestamp() // 3600) <= int(started.timestamp() // 3600):
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
    progressed = False
    for kind, action in (("run", run.run), ("nightly", nightly.nightly)):
        for ctx in contexts:
            try:
                if getattr(ctx, "round_failed", False) or kind == "nightly" and getattr(ctx, "night_failed", False):
                    continue
                if kind == "nightly" and not _night_ready(contexts, now()):
                    continue
                before = {t.run_id for t in phase.all_tasks(ctx.task_root(), ctx.name) if t.phase == "done"}
                result = _step(ctx, kind, action, started, state, path, cache)
                if kind == "nightly" and result:
                    ctx.night_failed = True
                if kind == "run":
                    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
                    ctx.round_failed = bool(result or any(t.kind == "notes" and t.open and t.data.get("needs_owner") for t in tasks))
                    progressed |= result in (None, 0) and any(t.kind == "notes" and t.phase == "done" and t.run_id not in before
                                      and not t.get("set_aside") and not t.get("no_progress") and not t.data.get("closed") for t in tasks)
            except Exception as exc:
                if kind == "run":
                    ctx.round_failed = True
                else:
                    ctx.night_failed = True
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
    return progressed


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
    return result


def _night_ready(contexts, current):
    from .work_pending import ready
    from datetime import timedelta
    hour, minute = map(int, contexts[0].cfg.nightly_after.split(":"))
    due_at = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due_at > current:
        due_at -= timedelta(days=1)
    deadline = due_at.replace(hour=6, minute=0)
    if deadline < due_at:
        deadline += timedelta(days=1)
    return current >= deadline or not any(ready(ctx) for ctx in contexts if not getattr(ctx, "round_failed", False))
