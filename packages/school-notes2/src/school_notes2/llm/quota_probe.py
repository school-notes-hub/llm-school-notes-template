"""Quota-only container helper. Never prints credentials or provider error bodies."""

import json
import os
import selectors
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def claude():
    data = json.loads((Path.home() / ".claude/.credentials.json").read_text())
    token = data["claudeAiOauth"]["accessToken"]
    version = os.environ.get("CLAUDE_CODE_VERSION") or "unknown"
    request = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/" + version})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
        return json.load(response)


def codex():
    proc = subprocess.Popen(["codex", "app-server", "--stdio"], cwd="/tmp",
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    pending = b""

    def send(value):
        proc.stdin.write((json.dumps(value) + "\n").encode())
        proc.stdin.flush()

    def receive(identifier):
        nonlocal pending
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                value = json.loads(line)
                if value.get("id") == identifier:
                    return value["result"]
            if sel.select(max(0, deadline - time.monotonic())):
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError("closed")
                pending += chunk
        raise TimeoutError()

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "school_notes", "version": "2"}}})
        receive(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read", "params": {"excludeResetCreditDetails": True}})
        return receive(2)
    finally:
        sel.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def weekly(provider, data):
    if provider == "codex":
        groups = data.get("rateLimitsByLimitId") or {"codex": data.get("rateLimits")}
        limit = groups.get("codex") or data.get("rateLimits") or {}
        windows = [limit.get(k) or {} for k in ("primary", "secondary")]
        values = [(w.get("usedPercent", w.get("used_percent")), w.get("resetsAt", w.get("resets_at")))
                  for w in windows if w.get("windowDurationMins", w.get("window_minutes")) == 10080]
    else:
        windows = data.get("limits") or [{"kind": k, **v} for k, v in data.items() if isinstance(v, dict)]
        values = [(w.get("percent", w.get("utilization")), w.get("resets_at"))
                  for w in windows if w.get("kind") in ("weekly_all", "seven_day")]
    valid = [(u, r) for u, r in values if type(u) in (int, float) and 0 <= u <= 100 and r is not None]
    if len(valid) != 1:
        return {"remaining": None, "reset": None}
    used, reset = valid[0]
    return {"remaining": 100 - used, "reset": str(reset)}


if __name__ == "__main__":
    try:
        provider = sys.argv[1]
        result = weekly(provider, codex() if provider == "codex" else claude())
    except Exception:
        result = {"remaining": None, "reset": None}
    print(json.dumps(result))
