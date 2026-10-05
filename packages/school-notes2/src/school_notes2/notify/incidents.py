"""Durable open errors: one safe mail until recovery, including failures without tasks."""

import hashlib
import re
from pathlib import PurePosixPath

from ..log import now_iso
from ..state.files import read_json, write_json
from . import Notice, pending

ROLES = {"writer": "jegyzetíró", "reader": "olvasó-lektor", "figure-review": "ábraellenőr",
         "figure": "ábrakészítő", "reviewer": "éjszakai lektor"}
STEPS = {"run": "a feldolgozás", "nightly": "az éjszakai ellenőrzés", "finish": "a lezárás",
         "check": "a gépi ellenőrzés", "build": "a kiadás előtti linkellenőrzés",
         "setup": "az előkészítés", "round": "az óránkénti kör", "publish": "a kiadás",
         "report_failed": "a jelentés készítése", "round_step": "az óránkénti lépés"}
# Free-form writer prose cannot be certified content-free by a mechanical filter.
SAFE_QUESTIONS = {"Folytathatom a feldolgozást?", "Újra elküldöd az olvashatatlan forrást?",
                  "Melyik tantárgyhoz tartozik a forrás?", "Feldolgozhatom ezt a forrást?"}


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "incidents.json"


def active(ctx):
    return [v for _, v in sorted(read_json(path(ctx), {}).items()) if not v.get("resolved_at")]


def wording(name, kind, step, *, task=None, exc=None, role=None):
    prefix = "a telepítés ellenőrzést igényel: " if step == "install" else "a futás megállt: "
    return prefix + _reason(name, kind, step, task=task, exc=exc, role=role)


def _reason(name, kind, step, *, task=None, exc=None, role=None):
    if step == "no-progress":
        return "toolhiba; a javító futás nem haladt; a munka félretéve; a kontroller ellenőrzi"
    if step == "machine-errors":
        return ("gépi ellenőrzési hiba maradt a javítókörök után; a munka megmaradt, a kiadás vár; "
                "a következő futás az íróval folytatja a javítást, nincs teendőd")
    details = getattr(exc, "details", {}) or {}
    raw = str(exc or "")
    if kind == "timeout":
        role = role if role in ROLES else "writer"
        return f"időtúllépés ({ROLES[role]}); teendőd: dönts az időkorlátról, majd school-notes status --clear {name} {role} --continue"
    questions = details.get("questions") or (task.get("question", []) if task else [])
    if questions or kind == "question":
        first = str(questions[0].get("text", "")) if questions and isinstance(questions[0], dict) else ""
        first = re.split(r"(?<=[.!?])\s", first.strip(), maxsplit=1)[0][:200]
        safe = first if first in SAFE_QUESTIONS else "a kérdés a privát munkamenetben olvasható"
        return f"a jegyzetíró kérdést tett fel: {safe}; válasz kell tőled a school-notes chat {name} munkamenetben"
    conflicts = (task.get("conflict_files", []) if task else []) or details.get("files", [])
    if (task and task.get("rebase") == "conflict") or "content conflict" in raw:
        filename = PurePosixPath(str(sorted(conflicts)[0])).name if conflicts else "érintett fájl"
        filename = re.sub(r"[^\w.\-]", "_", filename)[:100]
        return f"a futás és egy közben érkezett változás ütközött ({filename}); döntés kell tőled a school-notes chat {name} munkamenetben"
    if kind == "prerequisite":
        disk = re.search(r"only ([0-9]+(?:\.[0-9]+)?) GB free", raw)
        if disk:
            return f"kevés a szabad lemezhely a VM-en: {disk[1]} GB; teendő: helyet kell felszabadítani"
        reason = "lejárt vagy hiányzó Drive-bejelentkezés" if "token" in raw.lower() or "drive" in raw.lower() else "az előkészítés ellenőrzése"
        login = re.search(r"school-notes login " + re.escape(name) + r" (writer|reviewer|reader|figure|figure-review)\b", getattr(exc, "todo", ""))
        if login:
            return f"hiányzik egy előfeltétel (lejárt bejelentkezés); teendőd: {login[0]}"
        if "Podman" in raw:
            return "hiányzik egy előfeltétel (a konténerfuttató nem indul); teendőd: podman info"
        return f"hiányzik egy előfeltétel ({reason}); teendőd: school-notes status {name} --details"
    if kind in ("program", "report_failed", "round_step"):
        if step == "install":
            return "beragadt telepítési jelzőt törölt a tool; a kör folytatódik, a telepítés állapotát a kontroller ellenőrzi"
        reason = STEPS.get(step, "a tool ellenőrzése")
        if any(i.get("kind") in ("browser", "browser-link") for i in details.get("items", [])):
            reason = "a kiadás előtti linkellenőrzés"
        return f"programhiba a toolban ({reason}); nincs teendőd, a javítás a kontrolleré"
    if kind == "lock_held":
        return "a kör vagy a munkamenet 12 órája foglalja a zárat; a kontroller ellenőrzi"
    if kind == "bad_work":
        return "a jegyzetíró kétszer hibás kimenetet adott; a kontroller ellenőrzi a hibát és indítja újra"
    if kind == "transient":
        return "három egymás utáni sikertelen próba átmeneti működési hiba miatt; a következő óra első köre újrapróbálja"
    return "a feldolgozás döntésre vár; teendőd: school-notes status " + name + " --details"


def record(ctx, kind, step, *, task=None, exc=None, scope=None, role=None, run_id=""):
    if kind in ("waiting_quota", "race"):
        return None
    scope = scope or ("task:" + task.run_id if task else "operation:" + step)
    message = wording(ctx.name, kind, step, task=task, exc=exc, role=role)
    # Measurements change between attempts; the safe sentence defines the situation.
    identity = meaning(message)
    fingerprint = hashlib.sha256(f"{scope}\n{kind}\n{identity}".encode()).hexdigest()
    state = read_json(path(ctx), {})
    for value in state.values():
        if value["scope"] == scope and value["class"] != kind and not value.get("resolved_at"):
            value["resolved_at"] = now_iso()
    old = state.get(fingerprint, {})
    generation = old.get("generation", 0) + int(bool(old.get("resolved_at")))
    if not old or old.get("resolved_at"):
        old = {"at": now_iso(), "scope": scope, "class": kind, "message": message,
               "generation": generation, "run_id": task.run_id if task else run_id, "step": step}
        state[fingerprint] = old
        write_json(path(ctx), state)
    pending.send(ctx, notice(ctx, fingerprint, old))
    return old


def meaning(message):
    return re.sub(r"\b\d+(?:[.,]\d+)?\s*(?=GB\b|mp\b|s\b)", "<n> ", message)


def notice(ctx, fingerprint, value):
    return Notice(ctx.name, f"error:{fingerprint}:{value['generation']}", value["run_id"], value["step"],
                  f"{ctx.name.capitalize()}: működési hiba",
                  f"{ctx.name.capitalize()}, {value['at'][:16].replace('T', ' ')}: {value['message'].rstrip('.')}.", "")


def restore_pending(ctx):
    """Recover a crash between the incident write and the outbox write."""
    from dataclasses import asdict
    state = read_json(path(ctx), {})
    queued = read_json(pending.path(ctx), {})
    done = set(read_json(ctx.mailer.state.with_name("notify-once.json"), []))
    for key, value in sorted(state.items()):
        item = notice(ctx, key, value)
        if not value.get("resolved_at") and f"{ctx.name}:{item.kind}" not in done:
            queued.setdefault(item.kind, asdict(item))
    if queued:
        write_json(pending.path(ctx), dict(sorted(queued.items())))


def resolve(ctx, scope):
    state = read_json(path(ctx), {})
    changed = False
    for value in state.values():
        if value["scope"] == scope and not value.get("resolved_at"):
            value["resolved_at"] = now_iso()
            changed = True
    if changed:
        write_json(path(ctx), state)


def task_error(ctx, task, step="run", exc=None):
    error = task.data.get("needs_owner") or {}
    if not error:
        return None
    if error.get("class") == "timeout":
        return _task_timeout(ctx, task)
    existing = [i for i in active(ctx) if i["scope"] == "task:" + task.run_id
                and i["class"] == error.get("class") and i["message"].startswith("a futás megállt:")
                and (exc is None or meaning(i["message"]) == meaning(wording(
                    ctx.name, error["class"], step, task=task, exc=exc)))]
    if existing:
        return existing[0]
    # Retire pre-upgrade intermediate incidents before recording the owner stop.
    resolve(ctx, "task:" + task.run_id)
    return record(ctx, error.get("class", "program"), step, task=task, exc=exc)


def _task_timeout(ctx, task):
    from ..llm import timeouts
    resolve(ctx, "task:" + task.run_id)
    for value in active(ctx):
        if value["scope"].startswith("timeout:") and (
                value["run_id"] == task.run_id or value["run_id"].startswith(task.run_id + "-fix-a")):
            return value
    state = read_json(timeouts.path(ctx), {})
    suspended = [role for role in timeouts.ROLES if state.get(role, {}).get("suspended")]
    matching = [role for role in suspended if state[role].get("run_id") == task.run_id]
    role = next(iter(matching or suspended), "reviewer" if task.kind == "review" else "writer")
    return record(ctx, "timeout", role, role=role, scope="timeout:" + role, run_id=task.run_id)


def completed(ctx, task):
    """A completed run is recovery, including its correction run's timeout incidents."""
    resolve(ctx, "task:" + task.run_id)
    for value in active(ctx):
        if value["scope"].startswith("no-progress:"):
            continue
        if value["run_id"] == task.run_id or value["run_id"].startswith(task.run_id + "-fix-a"):
            resolve(ctx, value["scope"])
