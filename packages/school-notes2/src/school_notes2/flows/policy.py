"""One error policy for every entry point (plan 8.1, 8.3).

Transient errors were already retried inside the step; here a failed invocation counts
once (`retries`), and the third failed invocation in a row stops the run. Bad LLM work
counts in `llm_failures` (two in a row stop). Prerequisites never touch a task."""

import traceback

from ..log import Log
from ..notify import Mailer, Notice
from ..state.errors import BadWork, NeedsOwner, Prerequisite, SnError, Transient, WaitingQuota
from ..state.phase import Task

MAX_RETRIES = 3        # the failing hour plus the next two (8.1)
MAX_LLM_FAILURES = 2


def on_error(exc: BaseException, *, task: Task | None, student: str, step: str, log: Log,
             mailer: Mailer | None, interactive: bool = False) -> str:
    """Record `exc` per 8.1 and send the e-mail it calls for; returns the 8.1 class."""
    kind = getattr(exc, "kind", "program")
    log.error(step, exc)
    if kind == "program":
        log.event("traceback", "error", level="error",
                  message="".join(traceback.format_exception(exc))[-4000:])
    if isinstance(exc, Prerequisite):
        _mail(mailer, student, f"prerequisite:{step}", task, step, exc)
        return kind
    if task is None:
        if not isinstance(exc, Transient):   # 8.4: no mail about an intermediate error
            _mail(mailer, student, f"{kind}:{step}", None, step, exc)
        return kind
    task.record_error(kind, str(exc))
    if isinstance(exc, WaitingQuota):
        if task.phase != "waiting_quota":
            task.set_phase("waiting_quota", quota_phase=task.phase)
        return kind
    if kind == "timeout":
        if getattr(exc, "details", {}).get("count", 0) >= 2 or getattr(exc, "details", {}).get("suspended"):
            task.mark_needs_owner("Két egymás utáni időtúllépés; a munka megállt.",
                                  f"Állítsd be az időkorlátot; school-notes status --clear {student} writer --continue",
                                  "timeout")
        return kind
    if isinstance(exc, Transient):
        task.data["retries"] += 1
        task.save()
        if task.data["retries"] >= MAX_RETRIES:
            _stop(task, exc, student, step, mailer, "a transient error did not pass in 3 tries")
    elif isinstance(exc, BadWork):
        if interactive:
            return kind          # the session gets the error through MCP; nothing counts
        task.data["llm_failures"] += 1
        task.save()
        if task.data["llm_failures"] >= MAX_LLM_FAILURES:
            _stop(task, exc, student, step, mailer, "the writer failed twice in a row")
    else:
        _stop(task, exc, student, step, mailer, "")
    return kind


def on_success(task: Task) -> None:
    """A successful invocation ends the retry streak (8.1: a passing second hour)."""
    if task.data["retries"]:
        task.data["retries"] = 0
        task.save()


def _stop(task: Task, exc: BaseException, student: str, step: str, mailer: Mailer | None,
          why: str) -> None:
    todo = getattr(exc, "todo", "") or "see `school-notes status`, then continue or discard"
    reason = f"{why}: {exc}" if why else str(exc)
    task.mark_needs_owner(reason[:500], todo, getattr(exc, "kind", "program"))
    _mail(mailer, student, f"needs_owner:{task.kind}", task, step, exc, reason)


def _mail(mailer, student, kind, task, step, exc, message=None) -> None:
    if mailer is None:
        return
    mailer.send(Notice(student=student, kind=kind, run_id=task.run_id if task else "",
                       step=step, error_class=getattr(exc, "kind", "program"),
                       message=message or str(exc), todo=getattr(exc, "todo", "")))
