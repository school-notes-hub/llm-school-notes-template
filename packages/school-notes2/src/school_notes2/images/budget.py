"""Daily and monthly budget and the shared image lock (plan 4.6).

learning_image.py knows only school-year caps and has a non-waiting lock; the daily
1 USD budget and the blocking lock shared by all configured learners live here.
"""

import fcntl
import os
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..log import TZ

UNSETTLED = "unknown"


class LockTimeout(TimeoutError):
    pass


def attempts(ledger: dict):
    for job in ledger.get("jobs", {}).values():
        for attempt in job["attempts"]:
            yield job, attempt


def attempt_cost(attempt: dict) -> Decimal:
    """Booked cost; an unresolved attempt counts with its reservation."""
    value = attempt.get("cost_usd")
    return Decimal(str(value if value is not None else attempt.get("reserved_usd", "0")))


def spent_on(ledger: dict, day: date) -> Decimal:
    """Spending of a Budapest calendar day across all learners."""
    total = Decimal(0)
    for _, attempt in attempts(ledger):
        started = datetime.fromisoformat(attempt["started_at"]).astimezone(TZ).date()
        if started == day:
            total += attempt_cost(attempt)
    return total


def spent_in_month(ledger: dict, day: date) -> Decimal:
    """Spending of the Budapest calendar month of `day` across all learners."""
    total = Decimal(0)
    for _, attempt in attempts(ledger):
        started = datetime.fromisoformat(attempt["started_at"]).astimezone(TZ).date()
        if (started.year, started.month) == (day.year, day.month):
            total += attempt_cost(attempt)
    return total


def budget_left(ledger: dict, day: date, daily: Decimal, reservation: Decimal,
                monthly: Decimal | None = None) -> bool:
    """True when the next reservation fits into today's budget and into
    the month's cap."""
    if spent_on(ledger, day) + reservation > daily:
        return False
    return monthly is None or spent_in_month(ledger, day) + reservation <= monthly


def unknown_calls(ledger: dict) -> list[dict]:
    """Paid calls with unknown outcome; while any exists, all generation waits."""
    return [{"job": job["id"], "learner": job["learner"], "attempt": a["number"],
             "started_at": a["started_at"]}
            for job, a in attempts(ledger)
            if a["state"] == UNSETTLED or a.get("cost_usd") is None]


@contextmanager
def images_lock(path: Path, timeout_s: float, poll_s: float = 1.0):
    """Blocking flock with timeout on state/images.lock (all learners share it)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"image lock busy for {timeout_s:.0f}s") from None
                time.sleep(poll_s)
        yield
    finally:
        os.close(fd)
