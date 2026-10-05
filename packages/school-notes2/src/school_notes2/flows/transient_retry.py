"""Clock-bound transient retries, independent of cron frequency."""

from datetime import datetime, timedelta

from ..log import TZ

INTERVAL = timedelta(minutes=30)
LIMIT = 3


def now():
    return datetime.now(TZ)


def failed(task):
    at = now()
    after = task.get("transient_after")
    if not after or at >= datetime.fromisoformat(after):
        task.data["retries"] += 1
        task.update(transient_after=(at + INTERVAL).isoformat())
    return task.data["retries"] >= LIMIT


def ready(task):
    if task is None:
        return True
    owner = task.data.get("needs_owner") or {}
    if owner.get("class") == "transient":
        # Once stopped, permit one probe in each following clock hour.
        at = datetime.fromisoformat(owner["at"])
        return now() >= at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    after = task.get("transient_after")
    return not after or now() >= datetime.fromisoformat(after)


def resume(task):
    if not ready(task):
        return False
    if task is not None and (task.data.get("needs_owner") or {}).get("class") == "transient":
        # Keep the exhausted budget: a failed hourly probe stops until the next hour.
        from ..log import now_iso
        task.data["needs_owner"] = None
        task.data["retries"] = LIMIT - 1
        task.update(transient_after=None, completion_generation=task.get("completion_generation", 0) + 1,
                    resumed_at=now_iso(), active_at_resume=task.get("active_seconds", 0))
    return True
