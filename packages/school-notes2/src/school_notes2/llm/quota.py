"""Weekly subscription quota: bounded probe, round cache, durable last observation."""

import json
import subprocess
from pathlib import Path

from ..log import now_iso
from ..notify import Notice, pending
from ..state.errors import WaitingQuota
from ..state.files import read_json, write_json
from . import argv
from .leases import acquire


def probe(ctx, run):
    from .launch import _volume_role, remove_stale
    family = argv.family(run.harness)
    name = argv.container_name(ctx.name, run_id=run.run_id, role="quota-" + family)
    command = argv.podman_argv(learner=ctx.name, image=run.image, run_id=run.run_id,
                              mounts=argv.Mounts(), name=name, role=_volume_role(run.role_name),
                              allowed_domains=run.allowed_domains,
                              probe_domain=argv.api_domain(run.harness, run.allowed_domains))
    script = Path(__file__).with_name("quota_probe.py").read_text()
    try:
        with acquire(ctx.cfg.state_dir / "agent-leases", ctx.name, _volume_role(run.role_name), run.max_agents):
            remove_stale(name)
            try:
                result = subprocess.run(command + ["python3", "-c", script, family],
                                        capture_output=True, timeout=70)
            finally:
                remove_stale(name)
        value = json.loads(result.stdout) if result.returncode == 0 else {}
        remaining = value.get("remaining")
        if type(remaining) not in (int, float) or not 0 <= remaining <= 100 or not value.get("reset"):
            return {"remaining": None, "reset": None}
        return {"remaining": remaining, "reset": value["reset"]}
    except Exception:  # a probe failure never means zero remaining quota
        return {"remaining": None, "reset": None}


def check(ctx, run, manual, cache):
    if manual:
        return
    family = argv.family(run.harness)
    if family not in cache:
        value = {**probe(ctx, run), "at": now_iso()}
        cache[family] = value
        path = ctx.cfg.state_dir / "quota.json"
        state = read_json(path, {})
        previous = state.get(family, {})
        state[family] = {**value, "last_known": value if value["remaining"] is not None else previous.get("last_known")}
        write_json(path, state)
        ctx.log.event("quota.read", "unknown" if value["remaining"] is None else "ok", harness=family, **value)
        if value["remaining"] is None:
            ctx.mailer.send(Notice("VM", f"quota_unknown:{family}", run.run_id, run.role_name,
                                   "keret", f"{ctx.name}: a {family} heti kerete nem kérdezhető le ({value['at']}).",
                                   "A hívás indulhat; ellenőrizd a harness bejelentkezését."))
    value = cache[family]
    if value["remaining"] is not None and value["remaining"] <= 2:
        wait(ctx, run, cache)


def wait(ctx, run, cache):
    family = argv.family(run.harness)
    value = cache.get(family, {})
    # A mid-call exhaustion also prevents later automatic calls in this round.
    cache[family] = {**value, "remaining": 0, "reset": value.get("reset")}
    window = value.get("reset") or "unknown-" + now_iso()[:10]
    remaining = value.get("remaining")
    shown = "ismeretlen" if remaining is None else f"{remaining}%"
    pending.send(ctx, Notice("VM", f"quota:{family}:{window}", run.run_id, run.role_name,
                                "keret", f"{ctx.name}: {family}, maradék: {shown}. "
                                "A munka vár; visszatöltődés után onnan folytatódik.",
                                f"Kézi indítás: school-notes {'nightly' if run.role_name == 'reviewer' else 'run'} {ctx.name} --manual"))
    raise WaitingQuota(f"{family}: visszatöltődés után onnan folytatódik")


def exhausted(transcript):
    """Only harness error events, never arbitrary quoted teaching text."""
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") not in ("error", "turn.failed", "result") and not (
                event.get("type") == "assistant" and event.get("error") in ("rate_limit", "billing_error")):
            continue
        if event.get("type") == "result" and not event.get("is_error"):
            continue
        text = json.dumps({k: event[k] for k in ("error", "errors", "result", "message") if k in event}).lower()
        if any(marker in text for marker in ("usage_limit_reached", "insufficient_quota", "quota_exceeded", "hit your usage limit", "hit your limit", "weekly limit")):
            return True
    return False
