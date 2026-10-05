"""A local, per-learner receipt for failures without a task; with a durable incident notice."""

from ..log import now_iso
from ..state.files import read_json, write_json
from ..notify import incidents

def record(ctx, step, kind, exc=None):
    if getattr(exc, "incident_reported", False):
        return

    message = incidents.wording(ctx.name, kind, step, exc=exc)
    previous = read_json(ctx.cfg.state_dir / ctx.name / "last-error.json", {})
    same = previous.get("class") == kind and previous.get("step") == step
    at = previous.get("at") if same else now_iso()
    retry_path = ctx.cfg.state_dir / ctx.name / "operation-retries.json"
    retries = read_json(retry_path, {})
    previous_retry = retries.get(step, {})
    attempts = (previous_retry.get("count", 0) if previous_retry.get("class") == kind else 0) + 1
    retry_limit = {"transient": 3, "bad_work": 2}.get(kind, 0)
    attempts = attempts if retry_limit else 0
    if attempts:
        retries[step] = {"class": kind, "count": attempts}
    else:
        retries.pop(step, None)
    stopped = not retry_limit or attempts >= retry_limit
    if not stopped:
        reason = "átmeneti működési hiba" if kind == "transient" else "hibás munkakimenet"
        message = reason + "; nincs teendőd, a tool a következő körben újrapróbálja"
    if stopped:
        incidents.record(ctx, kind, step, exc=exc)
    write_json(ctx.cfg.state_dir / ctx.name / "last-error.json",
               {"at": at, "step": step, "class": kind, "message": message, "attempts": attempts})
    write_json(retry_path, retries)
    ctx.log.event("operation.last_error", "error", message=message)
    if exc is not None:
        exc.incident_reported = True


def clear(ctx, step=None):
    retry_path = ctx.cfg.state_dir / ctx.name / "operation-retries.json"
    retries = read_json(retry_path, {})
    if step is None:
        retries.clear()
    else:
        retries.pop(step, None)
    if retry_path.exists():
        write_json(retry_path, retries)
    for value in incidents.active(ctx):
        if value["scope"].startswith("operation:") and (step is None or value["scope"] == "operation:" + step):
            incidents.resolve(ctx, value["scope"])
    target = ctx.cfg.state_dir / ctx.name / "last-error.json"
    if step is None or read_json(target, {}).get("step") == step:
        target.unlink(missing_ok=True)
