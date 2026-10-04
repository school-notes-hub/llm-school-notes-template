"""The MCP server for the duration of one container (plan 7.5): a private session folder
with mcp.sock, served from a thread of the launching process."""

import contextlib
from contextvars import copy_context
import json
import os
import shutil
import threading
from pathlib import Path

from ..mcp.server import Handlers, McpServer
from .context import Ctx


def secret_values(ctx: Ctx) -> tuple[str, ...]:
    """Values redact() must never let out: whole files, lines, `key value`/`key=value`
    values and JSON string leaves of every file in the secrets folder."""
    values: set[str] = set()
    folder = ctx.cfg.secrets_dir
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.is_file():
            values |= _values(path.read_text(encoding="utf-8", errors="replace"))
    return tuple(sorted((v for v in values if len(v) >= 8), key=len, reverse=True))


def _values(text: str) -> set[str]:
    found = {text.strip()}
    for line in text.splitlines():
        line = line.strip()
        found.add(line)
        for sep in ("=", " ", "\t", ":"):
            if sep in line:
                found.add(line.split(sep, 1)[1].strip().strip('"'))
    try:
        found |= set(_json_leaves(json.loads(text)))
    except ValueError:
        pass
    return found


def _json_leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _json_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_leaves(item)


def session_dir(ctx: Ctx) -> Path:
    """A short private folder: a unix socket path may not exceed 108 bytes, so it lives in
    the user's runtime directory (tmpfs, 0700) rather than below the task folder."""
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / f"school-notes-{ctx.name}"


@contextlib.contextmanager
def mcp(ctx: Ctx, task_dir: Path, mode: str, handlers: Handlers, run_id):
    """Yield the session folder while the server answers on <folder>/mcp.sock."""
    sessdir = session_dir(ctx)
    shutil.rmtree(sessdir, ignore_errors=True)
    sessdir.mkdir(mode=0o700)
    os.chmod(sessdir, 0o700)
    server = McpServer(student=ctx.name, mode=mode, handlers=handlers, log=ctx.log,
                       jobs_dir=task_dir / "jobs", run_id=run_id,
                       log_path=str(ctx.cfg.log_path), secrets=secret_values(ctx),
                       wait_s=ctx.cfg.limits.mcp_wait_s)
    stop = threading.Event()
    thread = threading.Thread(target=copy_context().run, args=(server.serve, sessdir / "mcp.sock", stop.is_set),
                              daemon=True)
    thread.start()
    try:
        yield sessdir
    finally:
        stop.set()
        thread.join(timeout=5)
