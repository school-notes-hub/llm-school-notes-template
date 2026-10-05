"""Durable completion delivery and draining of suppressed legacy notices."""

import json
from dataclasses import asdict, replace

from ..state.files import read_json, write_json
from . import Notice, mailed


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "pending-owner-notices.json"


def send(ctx, notice: Notice) -> bool:
    """Persist before delivery; remove only after send_once has a receipt."""
    pending = read_json(path(ctx), {}) or {}
    pending.setdefault(notice.kind, asdict(notice))
    write_json(path(ctx), dict(sorted(pending.items())))
    return _deliver(ctx, pending, notice.kind)


def retry(ctx) -> None:
    from . import incidents
    incidents.restore_pending(ctx)
    _closed_tasks(ctx)
    pending = read_json(path(ctx), {}) or {}
    for key in sorted(pending):
        _deliver(ctx, pending, key)


def _deliver(ctx, pending, key) -> bool:
    notice = Notice(**pending[key])
    if key.startswith("error:"):
        from . import incidents
        value = read_json(incidents.path(ctx), {}).get(key.split(":")[1], {})
        if value.get("resolved_at") or (value and str(value["generation"]) != key.split(":")[2]):
            del pending[key]
            write_json(path(ctx), dict(sorted(pending.items())))
            return True
    if mailed(notice) and notice.message.lstrip().startswith("{"):
        notice = _legacy_summary(ctx, notice)
        if notice is not None:
            pending[key] = asdict(notice)
            write_json(path(ctx), dict(sorted(pending.items())))
    if notice is not None and ctx.mailer.send_once(notice) is None:
        return False
    del pending[key]
    write_json(path(ctx), dict(sorted(pending.items())))
    return True


def _legacy_summary(ctx, notice):
    """Rebuild pre-hotfix queued JSON from task metadata before any delivery."""
    from ..flows import operational_report as report
    from ..state import phase
    task = next((t for t in phase.all_tasks(ctx.task_root(), ctx.name)
                 if t.run_id == notice.run_id), None)
    receipt = notice.kind.split(":")[2] if notice.kind.count(":") >= 2 else None
    if task is None or receipt not in report.STATES:
        ctx.log.event("notify.suppressed", target=f"{notice.student}:{notice.kind}",
                      reason="legacy summary lacks task metadata")
        return None
    try:
        saved = json.loads(notice.message)
    except ValueError:
        saved = {}
    ended = saved.get("időpont") if isinstance(saved, dict) else None
    if not isinstance(ended, str):
        ended = task.data["updated"]
    mode = ("nightly" if task.kind == "review" else
            task.get("mode", "chat" if task.mode == "interactive" else "run"))
    labels = report.MODES.get(mode, report.MODES["run"])
    return replace(notice, error_class=report.subject(ctx.name, labels, receipt, task),
                   message=report.sentence(ctx.name, labels, task, receipt, ended=ended), todo="")


def _closed_tasks(ctx):
    """Recover a clear interrupted after saving the outcome but before queuing mail."""
    from ..flows import operational_report as report
    from ..state import phase
    for task in phase.all_tasks(ctx.task_root(), ctx.name):
        closed = task.data.get("closed") and task.get("closure_reason")
        if not (closed or task.get("set_aside") or task.phase == "done" and task.get("no_progress")) or task.get("closure_notice_delivered"):
            continue
        receipt = report.terminal(task)
        mode = "nightly" if task.kind == "review" else task.get("mode", "run")
        labels = report.MODES.get(mode, report.MODES["run"])
        prefix = "nightly" if task.kind == "review" else "completion"
        notice = Notice(ctx.name, f"{prefix}:{task.run_id}:{report.completion_key(task, receipt)}", task.run_id,
                        "finish", report.subject(ctx.name, labels, receipt, task),
                        report.sentence(ctx.name, labels, task, receipt), "")
        if send(ctx, notice):
            task.update(closure_notice_delivered=True)
