"""Private operational summaries; only currently available mechanical facts."""

import time
from pathlib import Path

from ..figures.review import verdict_for
from ..log import now_iso
from ..mcp.redact import redact
from ..notify import Notice, incidents, pending
from ..reader import verdicts
from ..review import relations
from ..state import phase, safefs
from ..state.files import read_json, write_json


def details(ctx, task):
    repo = ctx.notes_path
    items = relations.inventory(repo)["items"] if repo.is_dir() else {}
    topics = []
    units = task.get("inspection_all_units", task.get("inspection_units", []))
    selected = {i["file"] + "#" + i["item_id"] for i in task.get("open_review_items", [])}
    selected.update(k for k in items if k.rsplit("#", 1)[0] == task.get("inspection_report"))
    for unit in units:
        pages = unit["pages"]
        assigned = [i for k, i in items.items() if k in selected and i.get("file") in pages]
        figures = [s for s in task.get("inspection_figures", []) if s["brief"]["page"] in pages]
        figure_counts = {"elfogadva": 0, "függő": 0, "elutasítva": 0}
        for state in figures:
            if state.get("candidate", {}).get("state") == "no-figure":
                continue
            fid = state["brief"]["id"]
            receipt = task.get("inspection_receipts", {}).get(fid, {})
            decision = verdict_for(receipt, fid).get("verdict", "pending")
            figure_counts[{"accept": "elfogadva", "reject": "elutasítva"}.get(decision, "függő")] += 1
        topics.append({"téma": unit["topic"], "leletek": len(assigned),
                       "lezárt": sum(i["status"] in ("fixed", "settled", "question") for i in assigned),
                       "vitatott": sum(i["status"] == "disagree" for i in assigned),
                       "nyitott": sum(i["status"] in ("open", "owner", "pending") for i in assigned),
                       "ábrák": figure_counts,
                       "not_checked": [p for p in pages if verdicts.valid(repo, p) is None]})
    pages = sorted({p for u in units for p in u["pages"]})
    changed = [p for p in task.get("inspection_changed", pages) if p.startswith("wiki/") and p.endswith(".md")]
    notices = sum(safefs.read_text(repo, p).count("⏳") for p in pages if safefs.is_file(repo, p))
    events = read_json(ctx.cfg.state_dir / ctx.name / "timeout-events.json", [])
    return {"csomagok": task.get("packages", []), "változott oldalak": sorted(changed), "témák": topics,
            "⏳-jelzések": notices, "időtúllépések": [e for e in events if e["run_id"] == task.run_id
                                                        or e["run_id"].startswith((task.run_id + "-fix-a", task.run_id + "-fix-r"))],
            "keretállapot": read_json(ctx.cfg.state_dir / "quota.json", {}), "tokenek": _metrics(task)}


def _metrics(task):
    totals = {}
    for path in sorted(task.dir.rglob("transcript-*.log")):
        from ..llm.metrics import from_transcript
        # The role prefix is stable; labels can contain arbitrary dashes.
        from ..llm.timeouts import ROLES, role_name
        role = next((r for r in ("figure-review", "reader-1", "recheck", "fix", *ROLES)
                     if path.name.startswith("transcript-" + r + "-")), "unknown")
        values = totals.setdefault(role_name(role), {})
        for key, value in from_transcript(path).items():
            if type(value) in (int, float):
                values[key] = values.get(key, 0) + value
    return totals


def terminal(task):
    if task.phase == "done" and task.get("no_progress"):
        return "no_progress"
    if task.get("set_aside"):
        return "set_aside"
    if task.data.get("needs_owner"):
        return "needs_owner"
    if task.data.get("closed"):
        return "retry_nightly" if task.get("closure_reason") == "retry_nightly" else "closed"
    return "done" if task.phase == "done" else None


def completed(ctx, task, report, duration, *, finishing=False):
    from . import writer, image_notices
    receipt = terminal(task)
    notes = []
    if receipt != "set_aside":
        image_notices.summary(ctx, task)
        notes = writer.merge(writer.results(task, required=False) if task.get("ranges") else [])["owner_notes"]
    notes += task.get("reader_owner_notes", []) + task.get("recheck_owner_notes", [])
    notes += task.get("correction_result", {}).get("owner_notes", []) + report.get("owner_notes", [])
    report["owner_notes"] = list(dict.fromkeys(notes))
    is_terminal = bool(receipt)
    if receipt == "needs_owner":
        incidents.task_error(ctx, task)
        receipt = None
    elif receipt == "done":
        incidents.completed(ctx, task)
    # A resumed owner stop is a new closure; retries keep the same receipt.
    notice_key = completion_key(task, receipt) if receipt else None
    notices = task.get("completion_notices", {})
    choice = "completion" if receipt else None
    if choice and notices.get(notice_key) != choice:
        task.update(completion_notices={**notices, notice_key: choice})
    if is_terminal:
        try:
            report.update(details(ctx, task))
        except Exception:
            report = {k: report[k] for k in ("run_id", "phase", "mode", "owner_notes", "reader_coverage", "branch")
                      if k in report}
            ctx.log.event("report.details_failed", run_id=task.run_id)
    report.update(időtartam_s=round(duration, 3), időpont=now_iso(), fázis=task.phase)
    report = redact(report)
    write_json(task.dir / "report.json", report)
    if choice == "completion":
        mode = MODES.get(task.get("mode") or ("chat" if task.mode == "interactive" else "run"), MODES["run"])
        pending.send(ctx, Notice(ctx.name, f"completion:{task.run_id}:{notice_key}", task.run_id, "finish",
                                 subject(ctx.name, mode, receipt, task), sentence(ctx.name, mode, task, receipt), ""))
    return report


# label and possessive form for the one-sentence mail
MODES = {"publish": ("kiadási futás", "kiadási futása"), "run": ("jegyzetfutás", "jegyzetfutása"), "fix": ("javító futás", "javító futása"),
         "repair": ("javítási futás", "javítási futása"), "chat": ("interaktív munkamenet", "interaktív munkamenete"),
         "nightly": ("éjszakai review", "éjszakai review-ja")}
STATES = {"no_progress": "a javító futás nem haladt; a munka félretéve; a kontroller ellenőrzi", "set_aside": "toolhiba; a futás félretéve, archívumban; a kontroller javítja; a többi munka megy", "done": "kész", "closed": "elvetve", "retry_nightly": "éjszaka újrapróbálja", "needs_owner": "elakadt, rád vár"}


def state_text(receipt, task=None):
    if receipt == "set_aside" and task and task.get("set_aside_reason") == "bad_work":
        return "a jegyzetíró kétszer hibás kimenetet adott; a futás félretéve; a kontroller ellenőrzi; a többi munka megy"
    if receipt == "done" and task is not None:
        failed, calls = task.get("failed_fix_calls", []), task.get("calls") or []
        if task.get("no_change") and calls and len(failed) >= len(calls):
            return "a javító hívások nem jártak sikerrel; nem változott semmi, a tételek nyitva maradtak"
        if (task.get("build") or {}).get("held"):
            return "kész, kiadás visszatartva"
    return STATES.get(receipt, receipt)


def subject(name, mode, receipt, task=None):
    return f"{name.capitalize()}: {mode[0]} – {state_text(receipt, task)}"


def sentence(name, mode, task, receipt, *, ended=None):
    """One sentence: who, what, when it started and ended, and how it ended."""
    resumed = task.get("resumed_at")
    started = (resumed or task.data.get("created", ""))[:16].replace("T", " ")
    ended = (ended or task.get("ended_at") or now_iso())[:16].replace("T", " ")
    worked = round(max(0, (task.get("active_seconds") or 0) - (task.get("active_at_resume") or 0)) / 60)
    verb = "folytatódott" if resumed else "indult"
    text = (f"{name.capitalize()} {mode[1]} {started}-kor {verb}, {ended}-kor ért véget "
            f"({worked} perc munka), állapota: {state_text(receipt, task)}")
    if receipt == "closed":
        text = f"{name.capitalize()} {mode[1]} {started}-kor {verb}, {ended}-kor elvetve; a munkája nem került ki"
        if task.get("bundle"):
            text += f", archívumban van ({Path(task.get('bundle')).name})"
    owner = task.data.get("needs_owner") or {}
    if receipt == "needs_owner":
        # Raw exception messages may contain source content, JSON or paths.
        reasons = {"timeout": "időtúllépés", "program": "programhiba",
                   "bad_work": "hibás munkakimenet", "transient": "ismétlődő átmeneti hiba",
                   "prerequisite": "hiányzó előfeltétel"}
        text += f" ({reasons.get(owner.get('class'), 'tulajdonosi döntés szükséges')})"
    if task.get("image_budget_note"):
        text += "; " + task.get("image_budget_note")
    return text + "."


def completion_key(task, receipt):
    generation = task.get("completion_generation", 0)
    return f"{receipt}:{generation}" if generation else receipt


def ended(ctx, kind, started, before, *, successful=True):
    """Persist active elapsed time, including interrupted/quota-limited invocations."""
    elapsed = time.monotonic() - started
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    wanted = ("notes", "review") if kind == "clear" else ("review",) if kind == "nightly" else ("notes",)
    candidates = [t for t in tasks if t.kind in wanted and (t.run_id not in before or before[t.run_id] and before[t.run_id] != t.data)]
    if not candidates:
        return
    task = candidates[-1]
    from .operation import TIMING
    timing = TIMING.get()
    baseline = timing[1].get(task.run_id, 0) if timing else task.get("active_seconds", 0)
    task.update(active_seconds=max(task.get("active_seconds", 0), baseline + elapsed))
    if not terminal(task):
        return
    if task.phase == "done" and not task.get("ended_at"):
        task.update(ended_at=now_iso())
    if task.data.get("needs_owner"):
        incidents.task_error(ctx, task)
    elif task.phase == "done":
        incidents.completed(ctx, task)
    if task.kind == "review":
        review = read_json(task.dir / "review.json", {})
        report = {"időpont": now_iso(), "időtartam_s": task.get("active_seconds"), "tartomány": [task.get("base"), task.get("T")],
                  "fázis": task.phase, "blokkolt": task.get("blocked_topics", []),
                  "időtúllépések": read_json(ctx.cfg.state_dir / ctx.name / "timeouts.json", {}).get("reviewer", {}),
                  "új tételek": len(review.get("findings", [])), "owner_notes": review.get("owner_notes", []),
                  "jelölő": task.get("M", task.get("base")),
                  "jelölő oka": "minden témakör kész" if task.get("all_topics_done") else "hiányzó vagy blokkolt témakör",
                  "témakörök": review.get("topics", []), "kihagyott": task.get("skipped_topics", []),
                  "keretállapot": read_json(ctx.cfg.state_dir / "quota.json", {}), "tokenek": _metrics(task)}
        write_json(task.dir / "report.json", redact(report))
        receipt = terminal(task)
        if receipt not in ("done", "closed", "retry_nightly"):
            return
        pending.send(ctx, Notice(ctx.name, f"nightly:{task.run_id}:{completion_key(task, receipt)}", task.run_id, "nightly",
                                 subject(ctx.name, MODES["nightly"], receipt),
                                 sentence(ctx.name, MODES["nightly"], task, receipt), ""))
    else:
        report = read_json(task.dir / "report.json", {"mode": task.get("mode", "chat" if task.mode == "interactive" else "run")})
        completed(ctx, task, report, task.get("active_seconds", 0))


def at_finish(ctx, task, report):
    from .operation import TIMING
    timing = TIMING.get()
    if timing is None:
        return completed(ctx, task, report, task.get("active_seconds", 0), finishing=True)
    started, baseline = timing
    duration = max(task.get("active_seconds", 0), baseline.get(task.run_id, 0) + time.monotonic() - started)
    task.update(active_seconds=duration)
    return completed(ctx, task, report, duration, finishing=True)
