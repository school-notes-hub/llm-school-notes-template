"""Private owner notes in the completion report and the existing notification path."""

from ..mcp.redact import redact
from ..notify import Notice
from ..notify import pending
from ..state.files import write_json
from . import writer


def completion(ctx, task):
    notes = redact(writer.merge(writer.results(task, required=False))["owner_notes"])
    report = {"run_id": task.run_id, "phase": task.phase,
              "mode": task.get("mode", task.mode), "owner_notes": notes,
              "branch": f"notes/{task.run_id}" if task.get("no_push") else None}
    write_json(task.dir / "report.json", report)
    ctx.log.event("run.report", **report)
    if notes:
        pending.send(ctx, Notice(ctx.name, f"owner_notes:{task.run_id}", task.run_id,
                                    "finish", "owner_notes", "\n\n".join(notes),
                                    "Olvasd át a kihagyott lépések indokát és a jobb javaslatot."))
    from ..repair import failure
    failure.notify(ctx, task)
    return report
