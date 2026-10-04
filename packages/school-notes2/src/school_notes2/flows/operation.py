"""VM admission and the operation-local LLM policy context."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import time

from ..log import TZ
from ..notify import Notice
from ..state.lock import StudentLock

TIMING = ContextVar("school_notes_timing", default=None)
CURRENT = ContextVar("school_notes_operation", default=None)
VM_HELD = ContextVar("school_notes_vm_held", default=False)


def vm_lock(cfg):
    return StudentLock(cfg.state_dir / "operations", "vm")


@contextmanager
def admission(ctx, kind):
    if VM_HELD.get():
        yield True
        return
    lock = vm_lock(ctx.cfg)
    if not lock.try_acquire(kind):
        holder = lock.holder()
        ctx.log.event("round.skip", "locked", message="kör fut, kilépek", holder=holder)
        if holder.get("since") and (datetime.now(TZ) - datetime.fromisoformat(holder["since"])).total_seconds() > 43200:
            ctx.mailer.send(Notice("VM", "lock_held", "", kind, "zár",
                                   "A kör vagy a chat 12 órája fut.", "Ellenőrizd a futó munkát; a zárat nem törjük fel."))
        yield False
        return
    token = VM_HELD.set(True)
    try:
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


def entry(kind):
    def decorate(fn):
        @wraps(fn)
        def wrapped(ctx, *args, manual=False, **kwargs):
            with admission(ctx, kind) as acquired:
                if not acquired:
                    return 0
                current = CURRENT.get()
                with scope(ctx, manual, current[2] if current else None):
                    from ..state import phase
                    from . import operational_report
                    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
                    before = {t.run_id: t.data for t in tasks}
                    started = time.monotonic()
                    timing = TIMING.set((started, {t.run_id: t.get("active_seconds", 0) for t in tasks}))
                    try:
                        return fn(ctx, *args, **kwargs)
                    finally:
                        if kind in ("run", "nightly", "repair", "chat", "owner"):
                            try:
                                operational_report.ended(ctx, kind, started, before)
                            except (OSError, ValueError) as exc:
                                ctx.log.error("report.failed", exc)
                        TIMING.reset(timing)
        return wrapped
    return decorate
