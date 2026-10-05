"""One local, Hungarian operational view for the CLI and the controller's snapshot."""

from datetime import datetime, timedelta
from decimal import Decimal

from ..figures import pending as figures
from ..images import budget
from ..log import TZ
from ..notify import incidents
from ..review import files
from ..state import phase
from ..state.files import read_json, write_text
from . import operational_report

PHASES = {"prepared": "előkészítés", "writing": "írás", "finishing": "lezárás",
          "downloading": "letöltés", "downloaded": "letöltve", "moved": "előkészítés",
          "figures": "ábrakészítés", "inspecting": "ellenőrzés", "correcting": "javítás",
          "rechecking": "visszaellenőrzés", "review_ready": "lezárás", "reviewing": "ellenőrzés",
          "reviewed": "lezárás", "closing": "lezárás", "committed": "kiadás", "built": "kiadás",
          "pushing": "feltöltés", "pushed": "kiadás", "done": "kész", "waiting_quota": "keretre vár"}


def clock(iso):
    return iso[11:16] if iso else "–"


def collect(ctx, now=None):
    now = now or datetime.now(TZ)
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    lock = ctx.lock()
    held = not lock.probe()
    live = read_json(ctx.cfg.state_dir / ctx.name / "active.json", {}) if held else {}
    opened = [t for t in tasks if t.open]
    current = next((t for t in reversed(opened) if t.kind == ("review" if live.get("kind") == "nightly" else "notes")),
                   None if live else opened[-1] if opened else None)
    errors = incidents.active(ctx)
    from .operation import vm_context
    errors += incidents.active(vm_context(ctx))
    known = {e["scope"] for e in errors}
    for task in opened:
        if task.data.get("needs_owner") and "task:" + task.run_id not in known:
            error = task.data["needs_owner"]
            errors.append({"at": error["at"], "message": incidents.wording(ctx.name, error["class"], "run", task=task)})
    last = read_json(ctx.cfg.state_dir / ctx.name / "last-error.json", {})
    if last and "operation:" + last["step"] not in known:
        errors.append(last)
    today = [t for t in tasks if any(stamp[:10] == now.date().isoformat() for stamp in (
        t.get("ended_at") or "", t.get("resumed_at") or t.data["created"],
        (t.data.get("needs_owner") or {}).get("at", ""))) or t == current and held]
    today.sort(key=lambda t: (t.get("resumed_at") or t.data["created"], t.run_id))
    items = files.open_items(ctx.notes_path, "interactive") if ctx.notes_path.is_dir() else []
    pending = figures.load(ctx.notes_path) if ctx.notes_path.is_dir() else []
    drive = read_json(ctx.cfg.state_dir / ctx.name / "last-run.json", {})
    return {"name": ctx.name, "now": now, "held": held, "holder": lock.holder(), "live": live,
            "current": current, "today": today, "errors": sorted(errors, key=lambda e: (e["at"], e["message"])),
            "items": sum(i["status"] == "open" for i in items),
            "owner_items": sum(i["status"] == "owner" for i in items), "figures": len(pending),
            "drive": drive_count(drive, tasks), "budget": remaining(ctx),
            "round_pending": round_pending(ctx)}


def round_pending(ctx):
    from .operation import vm_lock
    lock = vm_lock(ctx.cfg)
    state = read_json(ctx.cfg.state_dir / "round.json", {})
    if lock.probe() or lock.holder().get("kind") != "round" or state.get("status") != "running":
        return False
    if "pending_learners" in state:
        return ctx.name in state["pending_learners"]
    # A round started before this release has no explicit queue.
    names = list(ctx.cfg.students)
    if state.get("step") == "nightly" or not state.get("step"):
        return ctx.name in names
    current = state.get("learner")
    return current in names and ctx.name in names[names.index(current) + 1:]


def drive_count(drive, tasks):
    if "ready_ids" not in drive:
        return len(drive.get("ready", [])) + len(drive.get("waiting", []))
    moved = {item["package"]["id"] for task in tasks if task.data["created"] >= drive["at"]
             and task.phase not in ("downloading", "downloaded") for item in task.get("selected", [])}
    return len(set(drive["ready_ids"]) - moved) + len(drive.get("waiting", []))


def remaining(ctx):
    try:
        settings = ctx.image_settings()
        ledger, day = settings.ledger(), settings.today()
        daily = max(Decimal(0), settings.daily_usd - budget.spent_on(ledger, day))
        monthly = max(Decimal(0), settings.monthly_usd - budget.spent_in_month(ledger, day))
        return f"napi {daily:.2f} USD, havi {monthly:.2f} USD"
    except (AttributeError, OSError, ValueError):
        return "nem elérhető"


def minutes(task, live=None, now=None):
    seconds = task.get("active_seconds", 0) - task.get("active_at_resume", 0)
    if live and live.get("started"):
        baseline = live.get("baseline", {}).get(task.run_id, 0)
        elapsed = (now - datetime.fromisoformat(live["started"])).total_seconds()
        seconds = max(seconds, baseline + elapsed - task.get("active_at_resume", 0))
    return round(max(0, seconds) / 60)


def render(data):
    name, task, now = data["name"].capitalize(), data["current"], data["now"]
    if task:
        mode = "nightly" if task.kind == "review" else "publish" if task.kind == "publish" else task.get("mode", "run")
        label = operational_report.MODES.get(mode, operational_report.MODES["run"])[0]
        stage = PHASES.get(task.phase, "folyamatban")
        if task.data.get("needs_owner"):
            state = f"{label} elakadt, {stage} fázis"
        elif task.phase == "waiting_quota":
            state = f"{label} keretre vár"
        elif data["held"]:
            started = data["live"].get("started") or data["holder"].get("since")
            elapsed = max(0, round((now - datetime.fromisoformat(started)).total_seconds() / 60)) if started else 0
            state = f"{label} fut {clock(started)} óta, {stage} fázis, {elapsed}. perc"
        else:
            state = f"{label} folytatásra vár, {stage} fázis"
    elif data["held"]:
        state = f"előkészítés fut {clock(data['holder'].get('since'))} óta"
    elif data.get("round_pending"):
        state = "szabad, a most futó körben következik"
    else:
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0)
        state = f"szabad, következő kör {next_hour:%H:%M}"
    lines = [f"{name}: {state}."]
    runs = []
    for t in data["today"]:
        started = t.get("resumed_at") or t.data["created"]
        end = t.get("ended_at") or (t.data.get("needs_owner") or {}).get("at") or (t.data["updated"] if t.phase == "done" or t.data.get("closed") else "")
        result = "elakadt" if t.data.get("needs_owner") else operational_report.STATES[operational_report.terminal(t)] if t.data.get("closed") else "kész" if t.phase == "done" else "vár" if not data["held"] or t != task else "fut"
        work = minutes(t, data["live"] if t == task and data["held"] else None, now)
        runs.append(f"{clock(started)}–{clock(end)} {work} p {result}")
    lines.append("  Mai futások: " + ("; ".join(runs) or "nincs") + ".")
    for error in data["errors"]:
        lines.append(f"  Hiba {error['at'][:16].replace('T', ' ')} óta: {error['message'].rstrip('.')}.")
    if not data["errors"]:
        lines.append("  Nyitott hiba: nincs.")
    lines.append(f"  Sorok: {data['items']} nyitott tétel, {data['figures']} függő ábra, {data['drive']} Drive-csomag.")
    lines.append(f"  Tulajdonosi döntésre vár: {data.get('owner_items', 0)} review-tétel.")
    lines.append(f"  Képkeret: {data['budget']}.")
    return "\n".join(lines)


def overview(ctx, now=None):
    try:
        return render(collect(ctx, now))
    except Exception:
        # A broken task or queue must not hide the other learner or break a round.
        errors = incidents.active(ctx)
        text = f"{ctx.name.capitalize()}: az állapot egy része nem olvasható; a kontroller ellenőrzi."
        return text + "".join(f"\n  Hiba {e['at'][:16]} óta: {e['message']}." for e in errors)


def snapshot(cfg):
    from . import context
    sections = [f"Készült: {datetime.now(TZ):%Y-%m-%d %H:%M}"]
    for name in cfg.students:
        try:
            sections.append(overview(context.make(cfg, name, console=False)))
        except Exception:
            sections.append(f"{name.capitalize()}: az állapot nem olvasható; a kontroller ellenőrzi.")
    text = "\n\n".join(sections) + "\n"
    write_text(cfg.state_dir / "allapot.txt", text)
    return text
