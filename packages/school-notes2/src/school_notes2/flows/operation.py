"""VM admission and the operation-local LLM policy context."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import sys
import time
from types import SimpleNamespace

from ..log import TZ, now_iso
from ..state.files import write_json
from ..state.lock import StudentLock

TIMING = ContextVar("school_notes_timing", default=None)
CURRENT = ContextVar("school_notes_operation", default=None)
VM_HELD = ContextVar("school_notes_vm_held", default=False)


def vm_lock(cfg):
    return StudentLock(cfg.state_dir / "operations", "vm")


@contextmanager
def admission(ctx, kind, *, manual=False):
    if VM_HELD.get():
        yield True
        return
    lock = vm_lock(ctx.cfg)
    if not lock.try_acquire(kind):
        holder = lock.holder()
        ctx.log.bind(student="VM", run_id="").event("round.skip", "locked", message="kör fut, kilépek", holder=holder)
        if manual:
            print(f"A VM-zár foglalt: {holder.get('kind', 'ismeretlen munka')} tartja "
                  f"{holder.get('since', 'ismeretlen időpont')} óta; próbáld újra a kör vége után.",
                  file=sys.stderr)
        if holder.get("since") and (datetime.now(TZ) - datetime.fromisoformat(holder["since"])).total_seconds() > 43200:
            from . import last_error
            last_error.record(vm_context(ctx), "vm-lock", "lock_held")
        yield False
        return
    token = VM_HELD.set(True)
    try:
        from . import last_error
        last_error.clear(vm_context(ctx), "vm-lock")
        yield True
    finally:
        VM_HELD.reset(token)
        lock.release()


@contextmanager
def scope(ctx, manual=False, cache=None):
    token = CURRENT.set((ctx, manual, {} if cache is None else cache))
    try:
        yield
    finally:
        CURRENT.reset(token)


def entry(kind, *, manual=False):
    default_manual = manual
    def decorate(fn):
        @wraps(fn)
        def wrapped(ctx, *args, manual=None, **kwargs):
            current = CURRENT.get()
            manual = default_manual if manual is None else manual
            manual = manual or bool(current and current[1])
            with admission(ctx, kind, manual=manual or kind == "clear") as acquired:
                if not acquired:
                    return 75 if manual or kind == "clear" else 0
                with scope(ctx, manual, current[2] if current else None):
                    return _invoke(ctx, kind, fn, args, kwargs)
        return wrapped
    return decorate


def _invoke(ctx, kind, fn, args, kwargs):
    from ..state import phase
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    before = {t.run_id: t.data for t in tasks}
    started = time.monotonic()
    timing = TIMING.set((started, {t.run_id: t.get("active_seconds", 0) for t in tasks}))
    active_path = ctx.cfg.state_dir / ctx.name / "active.json"
    successful = False
    try:
        write_json(active_path, {"kind": kind, "started": now_iso(),
                               "baseline": {t.run_id: t.get("active_seconds", 0) for t in tasks}})
        result = fn(ctx, *args, **kwargs)
        successful = result in (None, 0)
        return result
    except Exception as exc:
        from . import last_error
        last_error.record(ctx, kind, getattr(exc, "kind", "program"), exc)
        raise
    finally:
        _report(ctx, kind, started, before, successful, active_path, timing)


def _report(ctx, kind, started, before, successful, active_path, timing):
    from ..state import phase
    from . import operational_report
    try:
        if successful and kind in ("run", "nightly", "repair", "chat", "owner"):
            # A completed task proves recovery; a skipped/empty step does not.
            completed = phase.all_tasks(ctx.task_root(), ctx.name)
            if any(t.phase == "done" and before.get(t.run_id) != t.data for t in completed):
                from . import last_error
                last_error.clear(ctx)
        if kind in ("run", "nightly", "repair", "chat", "owner", "clear"):
            operational_report.ended(ctx, kind, started, before, successful=successful)
    except Exception as exc:
        ctx.log.error("report.failed", exc)
        from . import last_error
        last_error.record(ctx, "report_failed", "report_failed", exc)
    finally:
        active_path.unlink(missing_ok=True)
        TIMING.reset(timing)


def vm_context(ctx):
    return SimpleNamespace(name="VM", cfg=ctx.cfg, log=ctx.log.bind(student="VM", run_id=""), mailer=ctx.mailer)
