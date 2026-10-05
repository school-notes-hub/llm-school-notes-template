"""T-125 streaks persist per learner/role, independently of individual runs."""

from ..log import now_iso
from ..notify import incidents
from ..state.files import read_json, write_json

ROLES = ("writer", "reader", "figure-review", "figure", "reviewer")


def role_name(name):
    if name in ("reader-1", "recheck"):
        return "reader"
    return "writer" if name == "fix" else name


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "timeouts.json"


def counter(ctx, run):
    state = read_json(path(ctx), {})
    return state.get(role_name(run.role_name), {"count": 0})


def blocked(ctx, run):
    if role_name(run.role_name) == "reviewer":
        return read_json(path(ctx), {}).get("reviewer_units", {}).get(run.label, {}).get("count", 0) >= 2
    return counter(ctx, run).get("suspended", False)


def record(ctx, run):
    state = read_json(path(ctx), {})
    role = role_name(run.role_name)
    old = state.get(role, {})
    count = old.get("count", 0) + 1
    value = {"count": count, "suspended": count >= 2, "at": now_iso(),
             "run_id": run.run_id, "unit": run.label, "timeout_s": run.role.timeout_s}
    state[role] = value
    if role == "reviewer":
        units = state.setdefault("reviewer_units", {})
        key = run.label
        units[key] = {**value, "count": units.get(key, {}).get("count", 0) + 1}
        count = units[key]["count"]
        value["suspended"] = count >= 2
        units[key]["suspended"] = count >= 2
        state[role] = {**value, "suspended": any(u.get("suspended") for u in units.values())}
    write_json(path(ctx), state)
    events = read_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", [])
    events.append({"role": role, **value})
    write_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", events)
    ctx.log.event("llm.timeout", "stopped" if count >= 2 else "retry", role=role, **value)
    if count >= 2:
        stopped(ctx, run)
    return count


def stopped(ctx, run):
    """Also replayed when suspension was saved just before an interrupted notice."""
    role = role_name(run.role_name)
    incidents.record(ctx, "timeout", role, role=role, scope="timeout:" + role, run_id=run.run_id)


def success(ctx, run):
    state = read_json(path(ctx), {})
    role = role_name(run.role_name)
    state[role] = {"count": 0, "suspended": False, "at": now_iso()}
    if role == "reviewer":
        state.setdefault("reviewer_units", {})[run.label] = {"count": 0, "suspended": False}
        state[role]["suspended"] = any(u.get("suspended") for u in state["reviewer_units"].values())
    write_json(path(ctx), state)
    if role == "reviewer":
        for incident in incidents.active(ctx):
            if incident["scope"].startswith("timeout:reviewer:"):
                incidents.resolve(ctx, incident["scope"])
    if role != "reviewer" or not any(unit.get("suspended") for unit in state.get("reviewer_units", {}).values()):
        incidents.resolve(ctx, "timeout:" + role)


def clear(ctx, role):
    for incident in incidents.active(ctx):
        if incident["scope"] == "timeout:" + role or incident["scope"].startswith("timeout:" + role + ":"):
            incidents.resolve(ctx, incident["scope"])
    state = read_json(path(ctx), {})
    state.pop(role, None)
    if role == "reviewer":
        state.pop("reviewer_units", None)
    write_json(path(ctx), state)
