"""Durable owner notices, independent of a completed task's lifetime."""

from dataclasses import asdict

from ..state.files import read_json, write_json
from . import Notice


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "pending-owner-notices.json"


def send(ctx, notice: Notice) -> bool:
    """Persist before delivery; remove only after send_once has a receipt."""
    pending = read_json(path(ctx), {}) or {}
    pending.setdefault(notice.kind, asdict(notice))
    write_json(path(ctx), dict(sorted(pending.items())))
    return _deliver(ctx, pending, notice.kind)


def retry(ctx) -> None:
    pending = read_json(path(ctx), {}) or {}
    for key in sorted(pending):
        _deliver(ctx, pending, key)


def _deliver(ctx, pending, key) -> bool:
    if ctx.mailer.send_once(Notice(**pending[key])) is None:
        return False
    del pending[key]
    write_json(path(ctx), dict(sorted(pending.items())))
    return True
