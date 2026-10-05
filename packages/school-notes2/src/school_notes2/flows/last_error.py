"""A local, per-learner receipt for failures without a task; with a durable incident notice."""

from ..log import now_iso
from ..state.files import read_json, write_json
from ..notify import incidents

def record(ctx, step, kind, exc=None):
    if getattr(exc, "incident_reported", False):
        return

    message = incidents.wording(ctx.name, kind, step, exc=exc)
    previous = read_json(ctx.cfg.state_dir / ctx.name / "last-error.json", {})
    at = previous.get("at") if previous.get("class") == kind and previous.get("step") == step else now_iso()
    incidents.record(ctx, kind, step, exc=exc)
    write_json(ctx.cfg.state_dir / ctx.name / "last-error.json",
               {"at": at, "step": step, "class": kind, "message": message})
    ctx.log.event("operation.last_error", "error", message=message)
    if exc is not None:
        exc.incident_reported = True


def clear(ctx, step=None):
    for value in incidents.active(ctx):
        if value["scope"].startswith("operation:") and (step is None or value["scope"] == "operation:" + step):
            incidents.resolve(ctx, value["scope"])
    target = ctx.cfg.state_dir / ctx.name / "last-error.json"
    if step is None or read_json(target, {}).get("step") == step:
        target.unlink(missing_ok=True)
