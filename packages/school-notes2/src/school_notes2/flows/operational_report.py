"""Private operational summaries; only currently available mechanical facts."""

import json
import time

from ..log import now_iso
from ..mcp.redact import redact
from ..notify import Notice, pending
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
            decision = next((v["verdict"] for v in receipt.get("review", {}).get("figures", []) if v["id"] == fid), "pending")
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
                                                        or e["run_id"].startswith(task.run_id + "-fix-a")],
            "keretállapot": read_json(ctx.cfg.state_dir / "quota.json", {}), "tokenek": _metrics(task)}


def _metrics(task):
    totals = {}
    for path in sorted(task.dir.rglob("transcript-*.log")):
        from ..llm.metrics import from_transcript
        # The role prefix is stable; labels can contain arbitrary dashes.
        from ..llm.timeouts import ROLES, role_name
        role = next((r for r in ("figure-review", "reader-1", "reader-2", "recheck", "fix", *ROLES)
                     if path.name.startswith("transcript-" + r + "-")), "unknown")
        values = totals.setdefault(role_name(role), {})
        for key, value in from_transcript(path).items():
            if type(value) in (int, float):
                values[key] = values.get(key, 0) + value
    return totals


def completed(ctx, task, report, duration):
    from . import writer
    notes = writer.merge(writer.results(task, required=False) if task.get("ranges") else [])["owner_notes"]
    notes += task.get("reader_owner_notes", []) + task.get("recheck_owner_notes", [])
    notes += task.get("correction_result", {}).get("owner_notes", []) + report.get("owner_notes", [])
    report["owner_notes"] = list(dict.fromkeys(notes))
    report.update(details(ctx, task), időtartam_s=round(duration, 3), időpont=now_iso(), fázis=task.phase)
    report = redact(report)
    write_json(task.dir / "report.json", report)
    if duration > 600:
        from .operation import TIMING
        timing = TIMING.get()
        receipt = "done" if task.phase == "done" else f"{timing[0] if timing else duration:.6f}"
        pending.send(ctx, Notice(ctx.name, f"completion:{task.run_id}:{receipt}", task.run_id, "finish", "feldolgozás",
                                 json.dumps(report, ensure_ascii=False, indent=2), "A feldolgozás összesítése."))
    return report


def ended(ctx, kind, started, before):
    """Persist active elapsed time, including interrupted/quota-limited invocations."""
    elapsed = time.monotonic() - started
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    wanted = "review" if kind == "nightly" else "notes"
    candidates = [t for t in tasks if t.kind == wanted and (t.run_id not in before or before[t.run_id] and before[t.run_id] != t.data)]
    if not candidates:
        if kind == "nightly":
            ctx.mailer.send_once(Notice(ctx.name, "nightly-empty:" + now_iso(), "", "nightly", "éjszakai review",
                                        f"{now_iso()}: nincs feldolgozott tartomány; időtartam: {elapsed:.1f} s.", "Nincs teendő."))
        return
    task = candidates[-1]
    from .operation import TIMING
    timing = TIMING.get()
    baseline = timing[1].get(task.run_id, 0) if timing else task.get("active_seconds", 0)
    task.update(active_seconds=max(task.get("active_seconds", 0), baseline + elapsed))
    if kind == "nightly":
        review = read_json(task.dir / "review.json", {})
        report = {"időpont": now_iso(), "időtartam_s": task.get("active_seconds"), "tartomány": [task.get("base"), task.get("T")],
                  "fázis": task.phase, "blokkolt": task.get("blocked_topics", []),
                  "időtúllépések": read_json(ctx.cfg.state_dir / ctx.name / "timeouts.json", {}).get("reviewer", {}),
                  "új tételek": len(review.get("findings", [])), "owner_notes": review.get("owner_notes", []),
                  "jelölő": task.get("T") if task.phase == "done" else "nem lépett: " + task.phase,
                  "keretállapot": read_json(ctx.cfg.state_dir / "quota.json", {}), "tokenek": _metrics(task)}
        pending.send(ctx, Notice(ctx.name, f"nightly:{task.run_id}:{task.phase}:{task.data['updated']}", task.run_id,
                                 "nightly", "éjszakai review", json.dumps(redact(report), ensure_ascii=False, indent=2), "Az éjszakai munka összesítése."))
    elif task.get("active_seconds", 0) > 600:
        report = read_json(task.dir / "report.json", {"mode": task.get("mode", "chat" if task.mode == "interactive" else "run")})
        completed(ctx, task, report, task.get("active_seconds", 0))


def at_finish(ctx, task, report):
    from .operation import TIMING
    timing = TIMING.get()
    if timing is None:
        return report
    started, baseline = timing
    duration = max(task.get("active_seconds", 0), baseline.get(task.run_id, 0) + time.monotonic() - started)
    task.update(active_seconds=duration)
    return completed(ctx, task, report, duration)
