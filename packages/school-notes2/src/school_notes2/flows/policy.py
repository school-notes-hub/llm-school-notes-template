"""One error policy for every entry point (plan 8.1, 8.3).

Transient errors were already retried inside the step; here a failed invocation counts
once per half hour (`retries`); a third failure stops until the next hourly probe. Bad writer
work is counted per call (`correction_calls`); a run-level bad result stops the task. Nothing is
ever discarded: a stopped task keeps its worktree and a program error is released by the next
tool release. Prerequisites never touch a task."""

import traceback

from . import transient_retry
from ..log import Log
from ..notify import Mailer, Notice
from ..state.errors import BadWork, Prerequisite, Transient, WaitingQuota
from ..state.phase import Task

MAX_RETRIES = transient_retry.LIMIT


def on_error(exc: BaseException, *, task: Task | None, student: str, step: str, log: Log,
             mailer: Mailer | None, interactive: bool = False) -> str:
    """Record `exc` per 8.1 and send the e-mail it calls for; returns the 8.1 class."""
    kind = getattr(exc, "kind", "program")
    log.error(step, exc)
    if kind == "program":
        log.event("traceback", "error", level="error",
                  message="".join(traceback.format_exception(exc))[-4000:])
    if task is None or isinstance(exc, Prerequisite):
        from .operation import CURRENT
        from . import last_error
        current = CURRENT.get()
        if current:
            last_error.record(current[0], step, kind, exc)
    if isinstance(exc, Prerequisite):
        _mail(mailer, student, f"prerequisite:{step}", task, step, exc)
        return kind
    if task is None:
        if not isinstance(exc, Transient):   # 8.4: no mail about an intermediate error
            _mail(mailer, student, f"{kind}:{step}", None, step, exc)
        return kind
    if hasattr(exc, "items"):
        from . import checks
        task.update(last_check_problems=checks.ordered(exc.items))
    task.record_error(kind, str(exc))
    if isinstance(exc, WaitingQuota):
        if task.phase != "waiting_quota":
            task.set_phase("waiting_quota", quota_phase=task.phase)
        return kind
    if kind == "timeout":
        details = getattr(exc, "details", {})
        if details.get("count", 0) >= 2 or details.get("suspended"):
            role = details.get("role", "writer")
            task.mark_needs_owner("Két egymás utáni időtúllépés; a munka megállt.",
                                  f"Állítsd be az időkorlátot; school-notes status --clear {student} {role} --continue",
                                  "timeout")
            task.data["needs_owner"]["role"] = role   # only this role's clear lifts the stop
            task.save()
        return kind
    if isinstance(exc, Transient):
        if transient_retry.failed(task):
            _stop(task, exc, student, step, mailer, "a transient error did not pass in 3 tries")
    elif isinstance(exc, BadWork) and interactive:
        pass  # The session gets the error through MCP; nothing counts.
    else:
        _stop(task, exc, student, step, mailer, "")
    return kind


def on_success(task: Task) -> None:
    """A successful invocation ends the retry streak (8.1: a passing second hour)."""
    from .operation import CURRENT
    from ..notify import incidents
    if CURRENT.get() and task.phase == "done":
        incidents.completed(CURRENT.get()[0], task)
    if task.data["retries"] or task.get("transient_after"):
        task.data["retries"] = 0
        task.update(transient_after=None)


def _stop(task: Task, exc: BaseException, student: str, step: str, mailer: Mailer | None,
          why: str) -> None:
    todo = getattr(exc, "todo", "") or "see `school-notes status`, then continue or discard"
    reason = f"{why}: {exc}" if why else str(exc)
    task.mark_needs_owner(reason[:500], todo, getattr(exc, "kind", "program"))
    from .operation import CURRENT
    from ..notify import incidents
    if CURRENT.get():
        task.data["needs_owner"]["release"] = release(CURRENT.get()[0])
        task.save()
        incidents.task_error(CURRENT.get()[0], task, step, exc)
    _mail(mailer, student, f"needs_owner:{task.kind}", task, step, exc, reason)


def _mail(mailer, student, kind, task, step, exc, message=None) -> None:
    if mailer is None:
        return
    mailer.send(Notice(student=student, kind=kind, run_id=task.run_id if task else "",
                       step=step, error_class=getattr(exc, "kind", "program"),
                       message=message or str(exc), todo=getattr(exc, "todo", "")))


def release(ctx):
    """The installed release; a program stop is lifted by the next one."""
    from .. import VERSION
    return str(ctx.release()) if hasattr(ctx, "release") else VERSION
