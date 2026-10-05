"""Version-bound work stops outside Git; archival is replayable after interruption."""

from ..git import discard
from ..notify import Notice, pending
from ..state.files import read_json, write_json


def release(ctx):
    from .. import VERSION
    return str(ctx.release()) if hasattr(ctx, "release") else VERSION


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "set-aside.json"


def work(task):
    from .fix_progress import keys
    if task.get("assigned_work") is not None:
        return sorted(set(task.get("assigned_work", [])) | set(task.get("correction_work", [])) |
                      ({"repair:" + task.get("repair_topic")} if task.get("repair_topic") else set()))
    return sorted(set(task.get("fix_work", [])) | set(keys(
        task.get("open_review_items", []) + task.get("correction_items", []),
        task.get("pending_figures", []) + task.get("correction_figures", []))) |
        ({"repair:" + task.get("repair_topic")} if task.get("repair_topic") else set()))


def blocked(ctx):
    return {key for row in read_json(path(ctx), {}).values() if row["release"] == release(ctx)
            for key in row["work"]}


def record(ctx, task, reason):
    if task.phase == "done":
        return
    rows = read_json(path(ctx), {})
    rows[task.run_id] = {"work": work(task), "release": release(ctx), "reason": reason,
                         "mode": task.get("mode"), "archive": reason in ("program", "bad_work")}
    write_json(path(ctx), dict(sorted(rows.items())))


def resume(ctx, task):
    row = read_json(path(ctx), {}).get(task.run_id, {}) if task else {}
    if not task or task.phase == "done" or row.get("reason") not in ("program", "bad_work"):
        return False
    if not task.get("set_aside"):
        archive = ctx.cfg.root / "archive" / ctx.name
        bundle = discard.discard(ctx.worktree("notes"), task.run_id, archive)
        existing = archive / f"{task.run_id}.bundle"
        task.data["needs_owner"] = None
        task.set_phase("done", set_aside=True, set_aside_reason=row["reason"], release=row["release"],
                       bundle=str(bundle or existing) if bundle or existing.exists() else None)
    return True


def stop(ctx, task, *, reason="program"):
    if task.phase == "done":
        return
    record(ctx, task, reason)  # Durable before discarding the worktree.
    resume(ctx, task)
    from . import operational_report
    operational_report.completed(ctx, task, {}, task.get("active_seconds", 0))


def rollback_notice(ctx, task):
    if not getattr(ctx, "mailer", None):
        return
    pending.send(ctx, Notice(ctx.name, f"error:rollback-{task.run_id}:1", task.run_id,
        "correcting", "program", "Toolhiba: a javítókör két próbája visszagörgetve; "
        "az addig elfogadott eredmény kerül ki, a kontroller javítja.", ""))


def no_progress_notice(ctx, task):
    from ..notify import incidents
    if getattr(ctx, "mailer", None):
        incidents.record(ctx, "program", "no-progress", task=task, scope="no-progress:" + task.run_id)


def progressed(ctx, task):
    rows = read_json(path(ctx), {})
    if rows.get(task.run_id, {}).get("reason") == "no-progress":
        del rows[task.run_id]
        write_json(path(ctx), dict(sorted(rows.items())))
    elif not task.get("no_progress"):
        return
    task.update(no_progress=False)
    from ..notify import incidents
    incidents.resolve(ctx, "no-progress:" + task.run_id)
