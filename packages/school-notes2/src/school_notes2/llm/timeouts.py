"""T-125 streaks persist per learner/role, independently of individual runs."""

from ..log import now_iso
from ..notify import Notice, pending
from ..state.files import read_json, write_json

ROLES = ("writer", "reader", "figure-review", "figure", "reviewer")


def role_name(name):
    if name in ("reader-1", "reader-2", "recheck"):
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
    write_json(path(ctx), state)
    events = read_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", [])
    events.append({"role": role, **value})
    write_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", events)
    ctx.log.event("llm.timeout", "stopped" if count >= 2 else "retry", role=role, **value)
    message = ("A munka megállt; dönts az időkorlátról." if count >= 2 else
               "A munka a következő alkalommal újra próbálkozik.")
    pending.send(ctx, Notice(ctx.name, f"timeout:{role}:{value['at']}:{run.run_id}:{run.label}:{count}",
                                run.run_id, role, "időtúllépés",
                                f"{value['at']}: {run.label}, {run.role.timeout_s} s. {message}",
                                f"Állítsd be az időkorlátot; school-notes status --clear {ctx.name} {role} --continue"))
    return count


def success(ctx, run):
    state = read_json(path(ctx), {})
    role = role_name(run.role_name)
    state[role] = {"count": 0, "suspended": False, "at": now_iso()}
    if role == "reviewer":
        state.setdefault("reviewer_units", {})[run.label] = {"count": 0, "suspended": False}
    write_json(path(ctx), state)


def clear(ctx, role):
    state = read_json(path(ctx), {})
    state.pop(role, None)
    if role == "reviewer":
        state.pop("reviewer_units", None)
    write_json(path(ctx), state)
