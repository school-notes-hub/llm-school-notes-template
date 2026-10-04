"""The unix-socket transport of the MCP server: newline-delimited JSON-RPC (plan 7.5).

One bad client never stops the server: every connection is handled on its own, with a
size limit, and any error closes only that connection."""

import json
import os
import selectors
import socket
import stat
from pathlib import Path
from typing import Callable

MAX_BUFFER = 1024 * 1024      # one message may not exceed 1 MiB


def serve(sock_path: Path, handle: Callable[[object], dict | None], sockets: list,
          stop: Callable[[], bool]) -> None:
    folder = sock_path.parent
    info = folder.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise PermissionError(f"{folder} must be a private directory (0700) of this user")
    sock_path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sockets[:] = [listener]
    sel = selectors.DefaultSelector()
    buffers: dict[socket.socket, bytes] = {}
    try:
        _listen(sock_path, listener)
        sel.register(listener, selectors.EVENT_READ, None)
        while not stop():
            for key, _ in sel.select(timeout=0.5):
                if key.fileobj is listener:
                    _accept(listener, sel, buffers, sockets)
                    continue
                try:
                    _read(key.fileobj, handle, buffers)
                except Exception:  # noqa: BLE001 - drop this client only
                    _close(key.fileobj, sel, buffers, sockets)
    finally:
        sel.close()
        for s in list(sockets):
            s.close()
        sock_path.unlink(missing_ok=True)


def _listen(sock_path: Path, listener: socket.socket) -> None:
    """Publish the socket name atomically, only once permissions and listen are ready."""
    temporary = sock_path.with_name(".mcp.tmp")
    temporary.unlink(missing_ok=True)
    try:
        listener.bind(str(temporary))
        os.chmod(temporary, 0o600)
        listener.listen(4)
        listener.setblocking(False)
        os.replace(temporary, sock_path)
    finally:
        temporary.unlink(missing_ok=True)


def _accept(listener, sel, buffers, sockets) -> None:
    try:
        conn, _ = listener.accept()
    except OSError:
        return
    conn.setblocking(True)
    sel.register(conn, selectors.EVENT_READ, None)
    buffers[conn] = b""
    sockets.append(conn)


def _close(conn, sel, buffers, sockets) -> None:
    try:
        sel.unregister(conn)
    except (KeyError, ValueError):
        pass
    conn.close()
    buffers.pop(conn, None)
    if conn in sockets:
        sockets.remove(conn)


class _Closed(Exception):
    pass


def _read(conn: socket.socket, handle, buffers: dict) -> None:
    data = conn.recv(65536)
    if not data:
        raise _Closed
    buffers[conn] += data
    if b"\n" not in buffers[conn] and len(buffers[conn]) > MAX_BUFFER:
        raise _Closed            # a line without end: not a client we serve
    while b"\n" in buffers[conn]:
        line, buffers[conn] = buffers[conn].split(b"\n", 1)
        if not line.strip():
            continue
        reply = _answer(line, handle)
        if reply is not None:          # notifications get no answer
            conn.sendall(json.dumps(reply, ensure_ascii=False).encode() + b"\n")


def _answer(line: bytes, handle) -> dict | None:
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        return _error(None, -32700, "parse error")
    try:
        return handle(message)
    except Exception:  # noqa: BLE001 - a malformed message is answered, never fatal
        mid = message.get("id") if isinstance(message, dict) else None
        return _error(mid, -32603, "internal error")


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
