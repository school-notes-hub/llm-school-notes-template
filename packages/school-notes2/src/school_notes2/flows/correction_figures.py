"""Figure assignments live outside review-item capacity, with no empty paid retries."""

from datetime import datetime

from ..figures import pending, migration_gate, rechecks
from ..figures.review import verdict_for
from ..images import budget, plans
from ..images.generate import awaiting_review, exhausted
from ..notify import Notice, pending as owner_notices
from ..state import safefs


def assignable(ctx, entries, *, paid_disabled=False):
    if migration_gate.notify(ctx, ctx.notes_path):
        return []
    entries = sorted((e for e in entries if (e.get("runs", 0) < 3 or e.get("review_pending")) and not e.get("owner_required")),
                     key=pending.assignment_order)
    slots, free = 0, set()
    if any(pending.generated(ctx.notes_path, e["commission"]) for e in entries):
        settings = ctx.image_settings()
        ledger, day = settings.ledger(), settings.today()
        for entry in entries:
            mark_exhausted(ctx, entry, settings, ledger)
            job = ledger.get("jobs", {}).get(plans.job_id(settings.learner, entry["commission"]["id"]), {"attempts": []})
            if awaiting_review(job):
                free.add(entry["commission"]["id"])
        if not paid_disabled and not budget.unknown_calls(ledger):
            remaining = settings.daily_usd - budget.spent_on(ledger, day)
            if settings.monthly_usd is not None:
                remaining = min(remaining, settings.monthly_usd - budget.spent_in_month(ledger, day))
            slots = max(0, int(remaining // (settings.max_attempts * settings.reservation_usd)))
    result = []
    for entry in entries:
        if entry.get("owner_required"):
            continue
        if pending.generated(ctx.notes_path, entry["commission"]) and entry["commission"]["id"] not in free:
            if not slots:
                continue
            slots -= 1
        result.append(entry)
    return result


def awaiting(ctx, brief):
    if not pending.generated(ctx.notes_path, brief):
        return False
    settings = ctx.image_settings()
    job = settings.ledger().get("jobs", {}).get(plans.job_id(settings.learner, brief["id"]), {"attempts": []})
    return awaiting_review(job)


def mark_exhausted(ctx, entry, settings=None, ledger=None):
    brief = entry["commission"]
    if migration_gate.blocked(ctx.notes_path):
        return False
    if not pending.generated(ctx.notes_path, brief):
        return False
    settings = settings or ctx.image_settings()
    ledger = settings.ledger() if ledger is None else ledger
    job = ledger.get("jobs", {}).get(plans.job_id(settings.learner, brief["id"]), {"attempts": []})
    review_limit = awaiting_review(job) and rechecks.exhausted(ctx, brief["id"])
    if not exhausted(job, settings.max_attempts) and not review_limit:
        return False
    entry["owner_required"] = True
    reason = "Az ábra ingyenes újraellenőrzési kiosztásai elfogytak" if review_limit else "Az ábra fizetős próbái elfogytak"
    owner_notices.send(ctx, Notice(ctx.name, f"image_exhausted:{brief['id']}", "", "images", "owner",
        f"{reason}: {brief['id']} ({brief['page']}).",
        f"Dönts a függő ábráról a school-notes chat {ctx.name} munkamenetben."))
    return True


def persist_owners(ctx, entries):
    if migration_gate.blocked(ctx.notes_path):
        return []
    owners = {e["commission"]["id"] for e in entries if e.get("owner_required")}
    waiting = pending.load(ctx.notes_path)
    changed = False
    for entry in waiting:
        if entry["commission"]["id"] in owners and not entry["owner_required"]:
            entry["owner_required"], changed = True, True
    if changed:
        safefs.write_json(ctx.notes_path, pending.PATH, waiting)
    return [pending.PATH] if owners and waiting else []


def attempted(ctx, task, brief):
    paid = False
    if pending.generated(ctx.notes_path, brief):
        settings = ctx.image_settings()
        entry = settings.ledger().get("jobs", {}).get(plans.job_id(settings.learner, brief["id"]), {})
        start = datetime.fromisoformat(task.data["created"])
        paid = any(datetime.fromisoformat(a["started_at"]) >= start and
                   (a["state"] != "failed" or budget.attempt_cost(a) > 0)
                   for a in entry.get("attempts", []))
    return pending.has_attempt(ctx.notes_path, brief, paid=paid)


def defects(state, receipt, previous=()):
    brief = state["brief"]
    verdict = verdict_for(receipt, brief["id"])
    current = verdict.get("defects", []) + verdict.get("text_mismatch", [])
    result = list(current or previous)
    reason = receipt.get("reason") or state["candidate"].get("reason")
    if reason:
        extra = {"location": brief["id"], "observed": reason, "expected": "valid reviewed candidate"}
        if extra not in result:
            result.append(extra)
    return result


def waiting(ctx, task):
    old = {e["commission"]["id"]: e for e in task.get("pending_figures", [])}
    entries = []
    for state in task.get("inspection_figures", []):
        brief = state["brief"]
        receipt = task.get("inspection_receipts", {}).get(brief["id"], {})
        verdict = verdict_for(receipt, brief["id"])
        if verdict.get("verdict") == "accept" or state["candidate"]["state"] == "no-figure":
            continue
        previous = old.get(brief["id"], {})
        entries.append({"commission": brief, "status": "pending", "runs": previous.get("runs", 0),
                        "run_ids": previous.get("run_ids", []), "owner_required": False,
                        "defects": defects(state, receipt, previous.get("defects", []))})
    return assignable(ctx, entries, paid_disabled=task.get("mode") == "repair")


def start(repo, entries):
    # Called before the child checkpoint; repeats before it are harmless. Resumes
    # after that checkpoint preserve the child's newly written candidates.
    for entry in entries:
        brief = entry["commission"]
        safefs.write_json(repo, f".school-notes/figures/{brief['id']}.json", brief)
        path = f".school-notes/figures/{brief['id']}/figure.json"
        if safefs.is_file(repo, path):
            safefs.unlink(repo, path)


def changed_figures(ctx, task):
    from ..figures import commissions, context
    changed = []
    for state in task.get("inspection_figures", []):
        brief = state["brief"]
        candidate = commissions.candidate(ctx.notes_path, brief)
        if candidate["state"] != "candidate":
            continue
        receipt = task.get("inspection_receipts", {}).get(brief["id"], {})
        previous = verdict_for(receipt, brief["id"]).get("key")
        if context.verdict_key(ctx.notes_path, brief, candidate) != previous:
            changed.append(brief)
    return changed
