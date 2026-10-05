"""Private owner notes in the completion report and the existing notification path."""

from ..mcp.redact import redact
from ..notify import Notice
from ..notify import pending
from ..state.files import read_json, write_json
from . import writer


def completion(ctx, task):
    merged = writer.merge(writer.results(task, required=False))
    from ..figures import requests as figure_requests, licenses
    requests = [r for r in figure_requests.active(ctx.notes_path)
                if licenses.permission(ctx.notes_path, r) is None]
    task.update(figure_requests=requests)
    for request in requests:
        pending.send(ctx, Notice(ctx.name, f"license:{request['id']}:{request['source']}:{request['page']}",
                                 task.run_id, "finish", "licenckérelem",
                                 f"Anyag: {request['source']}; kivágás: {request['crop']}; "
                                 f"cél: {request['purpose']}; hely: {request['page']}",
                                 "Dönts a kép felhasználási jogáról a tulajdonosi munkamenetben."))
    notes = redact(merged["owner_notes"] + task.get("scope_owner_notes", [])
                   + task.get("reader_owner_notes", []) + task.get("recheck_owner_notes", [])
                   + task.get("correction_result", {}).get("owner_notes", [])
                   + read_json(task.dir / "report.json", {}).get("owner_notes", []))
    notes = list(dict.fromkeys(notes))
    report = {"run_id": task.run_id, "phase": task.phase,
              "mode": task.get("mode", "chat" if task.mode == "interactive" else "run"), "owner_notes": notes,
              "reader_coverage": task.get("reader_coverage", []),
              "branch": f"notes/{task.run_id}" if task.get("no_push") else None}
    write_json(task.dir / "report.json", report)
    ctx.log.event("run.report", **report)
    from ..repair import failure
    failure.notify(ctx, task)
    from .operational_report import at_finish
    return at_finish(ctx, task, report)
