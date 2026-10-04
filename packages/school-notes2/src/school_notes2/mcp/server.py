"""MCP server on a unix socket, bound to one learner and one mode (plan 7.5).

A hand-written JSON-RPC 2.0 server: the MCP surface needed is four methods (initialize,
tools/list, tools/call, ping), which is less code than adapting an SDK transport to a
socat-bridged unix socket. Inside the container the harness runs
`socat STDIO UNIX-CONNECT:/run/sn/mcp.sock` as a stdio MCP server.
"""

import json
import socket
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import jsonschema

from .. import VERSION
from ..images.plans import PLAN_ID as PLAN_ID_RE
from ..log import Log, Timer
from ..schemas import errors as schema_errors
from ..state.errors import SnError
from . import transport
from .jobs import JobStore
from .redact import redact

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PLAN_ID = {"type": "string", "pattern": PLAN_ID_RE.pattern}
NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}
STATE_CHANGING = ("fetch", "finish")
# While a fetch or finish job runs, nothing else may touch the worktree or phase.json.
WORKTREE_WRITERS = ("check", "image_generate", "image_accept")


@dataclass(frozen=True)
class Tool:
    description: str
    schema: dict
    background: bool
    interactive_only: bool = False


TOOLS = {
    "check": Tool("Run the full check now (background job; follow it with `wait`). Problems "
                  "include errors and warning ids. At most three calls per invocation; decide warnings "
                  "in result.json. If truncated, read .school-notes/check.json.",
                  NO_ARGS, True),
    "image_generate": Tool(
        "Generate the image of a plan in .school-notes/images/<plan_id>.json (background job). "
        "With repair_note, regenerate with that correction.",
        {"type": "object", "additionalProperties": False, "required": ["plan_id"],
         "properties": {"plan_id": PLAN_ID,
                        "repair_note": {"type": "string", "minLength": 1, "maxLength": 2000}}},
        True),
    "image_accept": Tool(
        "Accept a generated image after looking at it and its publication preview; `review` "
        "holds your verdict fields (observed, decision, checks, material_defects, description, "
        "publication).",
        {"type": "object", "additionalProperties": False, "required": ["plan_id", "review"],
         "properties": {"plan_id": PLAN_ID, "review": {"type": "object"}}},
        False),
    "status": Tool("The learner's current state (run, phase, open items, images, budget).",
                   NO_ARGS, False),
    "wait": Tool("Wait up to ~50 seconds for a background job; call again while it is running.",
                 {"type": "object", "additionalProperties": False, "required": ["job_id"],
                  "properties": {"job_id": {"type": "string", "pattern": "^[a-z0-9-]{1,64}$"}}},
                 False),
    "fetch": Tool("Start a new run: download ready Drive packages (or none) and prepare the "
                  "work branch (background job).", NO_ARGS, True, interactive_only=True),
    "finish": Tool("Finish the run: check, generate, commit, rebase, build, push, publish "
                   "(background job; it keeps running after the session ends).",
                   NO_ARGS, True, interactive_only=True),
}


@dataclass
class Handlers:
    """The tool functions the orchestrator supplies; each returns a JSON-able dict."""

    check: Callable[[], dict]
    image_generate: Callable[[str, str | None], dict]
    image_accept: Callable[[str, dict], dict]
    status: Callable[[], dict]
    fetch: Callable[[], dict] | None = None
    finish: Callable[[], dict] | None = None


class ToolError(Exception):
    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


class McpServer:
    def __init__(self, *, student: str, mode: str, handlers: Handlers, log: Log, jobs_dir: Path,
                 run_id: Callable[[], str], log_path: str, secrets: tuple[str, ...] = (),
                 wait_s: float = 50):
        if mode not in ("cron", "interactive"):
            raise ValueError("mode must be cron or interactive")
        self.student, self.mode, self.handlers = student, mode, handlers
        self.log, self.run_id, self.log_path = log, run_id, log_path
        self.secrets, self.wait_s = secrets, wait_s
        self.jobs = JobStore(jobs_dir, log, self._close_sockets)
        self._sockets: list[socket.socket] = []

    # --- MCP surface -------------------------------------------------------------------
    def tools(self) -> dict:
        return {n: t for n, t in TOOLS.items() if self.mode == "interactive" or not t.interactive_only}

    def handle(self, message) -> dict | None:
        """One JSON-RPC message in, one response out (None for notifications)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _rpc_error(None, -32600, "invalid request")
        if "id" not in message:
            return None
        mid, method = message["id"], message.get("method")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _rpc_error(mid, -32602, "params must be an object")
        if method == "initialize":
            asked = params.get("protocolVersion")
            return _rpc_result(mid, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"school-notes-{self.student}", "version": VERSION}})
        if method == "ping":
            return _rpc_result(mid, {})
        if method == "tools/list":
            return _rpc_result(mid, {"tools": [
                {"name": n, "description": t.description, "inputSchema": t.schema}
                for n, t in self.tools().items()]})
        if method == "tools/call":
            arguments = params.get("arguments")
            response = self.call_tool(params.get("name"), {} if arguments is None else arguments)
            return _rpc_result(mid, {
                "content": [{"type": "text", "text": json.dumps(response, ensure_ascii=False)}],
                "structuredContent": response, "isError": not response["ok"]})
        return _rpc_error(mid, -32601, f"method not found: {method}")

    def call_tool(self, name, args) -> dict:
        """Validate, dispatch, and wrap the answer in the fixed response schema; never raises."""
        run_id = self._current_run_id()
        with Timer() as t:
            try:
                result = self._dispatch(name, args)
                response = {"ok": True, "result": result}
            except ToolError as exc:
                response = {"ok": False, "error": {"code": exc.code, "message": exc.message,
                                                   **exc.extra}}
            except SnError as exc:
                response = {"ok": False, "error": {"code": exc.kind, "message": exc.message,
                                                   "todo": exc.todo, **exc.details}}
            except Exception as exc:  # noqa: BLE001 - tracebacks stay in the host log
                self.log.bind(run_id=run_id).event(
                    f"mcp.{name}", "error", level="error", error_class="program",
                    message=str(exc)[:300], traceback=traceback.format_exc()[-4000:])
                response = {"ok": False, "error": {"code": "internal_error",
                                                   "message": "internal error; see the host log"}}
        response.update(run_id=run_id, log=self.log_path)
        response = redact(response, self.secrets)
        self.log.bind(run_id=run_id).event(
            f"mcp.{name}" if isinstance(name, str) else "mcp.call",
            "ok" if response["ok"] else "error", duration_s=t.s,
            error_code=response.get("error", {}).get("code", ""),
            job_id=response.get("result", {}).get("job_id", ""))
        return response

    # --- dispatch ----------------------------------------------------------------------
    def _dispatch(self, name, args) -> dict:
        tool = TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            raise ToolError("unknown_tool", f"unknown tool: {name!r}")
        if tool.interactive_only and self.mode != "interactive":
            raise ToolError("not_allowed", f"{name} is only available in an interactive session")
        problems = [e.message for e in jsonschema.Draft202012Validator(tool.schema).iter_errors(args)]
        if problems:
            raise ToolError("invalid_params", "; ".join(problems[:5]))
        if name == "wait":
            return self._wait(args["job_id"])
        if name == "status":
            return self.handlers.status()
        self._refuse_while_busy(name)
        if name == "image_accept":
            problems = schema_errors("image-accept", args["review"])
            if problems:
                raise ToolError("invalid_params", "review: " + "; ".join(problems[:10]))
            return self.handlers.image_accept(args["plan_id"], args["review"])
        return self._start(name, args)

    def _refuse_while_busy(self, name: str) -> None:
        """A running fetch/finish owns the worktree and phase.json: anything else is told to
        wait (a repeated fetch/finish gets the running job id, 7.5). The other way round
        too: while a check or image job still writes in the worktree, fetch/finish wait."""
        checking = self.jobs.running(("check",)) if name == "image_accept" else None
        if checking:
            raise ToolError("busy", "check is running; wait for it first",
                            job_id=checking["id"], tool="check")
        busy = self.jobs.running(STATE_CHANGING)
        if busy and name in WORKTREE_WRITERS:
            raise ToolError("busy", f"{busy['tool']} is running; wait for it first",
                            job_id=busy["id"], tool=busy["tool"])
        writer = self.jobs.running(WORKTREE_WRITERS)
        if writer and name in STATE_CHANGING:
            raise ToolError("busy", f"{writer['tool']} is running; wait for it first",
                            job_id=writer["id"], tool=writer["tool"])

    def _start(self, name: str, args: dict) -> dict:
        watch = STATE_CHANGING if name in STATE_CHANGING else (name,) if name == "check" else ()
        running = self.jobs.running(watch) if watch else None
        if running:
            return {"job_id": running["id"], "tool": running["tool"], "state": "running",
                    "already_running": True}
        fn = self._job_function(name, args)
        job_id = self.jobs.start(name, self._current_run_id(), fn)
        return {"job_id": job_id, "tool": name, "state": "running"}

    def _job_function(self, name: str, args: dict) -> Callable[[], dict]:
        h = self.handlers
        if name == "image_generate":
            return lambda: h.image_generate(args["plan_id"], args.get("repair_note"))
        fn = getattr(h, name)
        if fn is None:
            raise ToolError("not_allowed", f"{name} is not available")
        return fn

    def _wait(self, job_id: str) -> dict:
        job = self.jobs.wait(job_id, self.wait_s)
        if job is None:
            raise ToolError("job_unknown", f"no such job: {job_id}")
        if job["state"] == "running":
            return {"job_id": job_id, "tool": job["tool"], "state": "running"}
        if job["state"] == "error":
            raise ToolError(job["error"].get("code", "error"), job["error"].get("message", ""),
                            job_id=job_id, tool=job["tool"],
                            **{k: v for k, v in job["error"].items() if k not in ("code", "message")})
        return {"job_id": job_id, "tool": job["tool"], "state": "done",
                "result": job.get("result", {})}

    def _current_run_id(self) -> str:
        try:
            return self.run_id() or ""
        except Exception:  # noqa: BLE001 - a missing run is not an error here
            return ""

    # --- socket ------------------------------------------------------------------------
    def serve(self, sock_path: Path, stop: Callable[[], bool] = lambda: False) -> None:
        """Serve until `stop()` is true. The session folder must be a private (0700) dir."""
        transport.serve(sock_path, self.handle, self._sockets, stop)

    def _close_sockets(self) -> None:
        for s in self._sockets:
            try:
                s.close()
            except OSError:
                pass


def _rpc_result(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
