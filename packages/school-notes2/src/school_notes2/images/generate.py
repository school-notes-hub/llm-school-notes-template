"""`image_generate` (plan 4.6, 5.5): budget, lock, call, preview, hand back to the LLM.

Expected outcomes are returned as a `state`, never raised, so `sn gen` can explain
them: generated, accepted, waiting-unknown, budget-exhausted, exhausted, failed,
unknown, error. Retries only on a connection error and on 429.
"""

import time
from pathlib import Path

from ..log import Log
from ..state import safefs
from . import plans
from .budget import budget_left, images_lock, unknown_calls
from .executor import ExecutorError, ExecutorTimeout, call, ensure_ledger, module
from .settings import ImageSettings

MAX_REPAIR_CHARS = 2000
RETRY_DELAYS = (15, 60)
RETRYABLE = ("not-sent", "http-429")


def generate(settings: ImageSettings, plan_id: str, repair_note: str | None = None, *,
             log: Log, sleep=time.sleep, paid_disabled=False) -> dict:
    plans.check_id(plan_id)
    from ..figures import commissions, context
    try:
        brief = commissions.read(settings.worktree, plan_id)
        commissions.validate_assignments(settings.worktree, [{k: brief[k] for k in ("id", "page", "kind")}])
        context.embedding(settings.worktree, brief, {"alt": "", "caption": ""})
    except (ValueError, OSError) as exc:
        return {"state": "error", "message": f"figure commission required before generation: {exc}"}
    if repair_note is not None and len(repair_note) > MAX_REPAIR_CHARS:
        return {"state": "error", "message": f"repair_note is longer than {MAX_REPAIR_CHARS}"}
    with images_lock(settings.lock_path, settings.lock_timeout_s):
        try:
            job = plans.build_job(settings, plan_id)
        except ValueError as exc:
            return {"state": "error", "message": f"{exc}\nJavítsd a {plans.target(plan_id)} képtervet "
                    "a prompt képtervsémája szerint (kötelező: role és a felsorolt mezők). "
                    f"Az id, kind, page, purpose a .school-notes/figures/{plan_id}.json "
                    "megbízásba való, nem a képtervbe. Ezután hívd újra az image_generate-et."}
        ledger = settings.ledger()
        changed = False
        if ledger.get("jobs"):
            try:
                job, changed = module(settings.script).generation_job(ledger, job)
            except ValueError as exc:
                return {"state": "error", "message": str(exc)}
        plans.keep(settings, plan_id)
        job_path = plans.write_job(settings, plan_id, job)
        entry = settings.ledger().get("jobs", {}).get(job["id"], {"attempts": []})
        if not changed and awaiting_review(entry) and not repair_note:
            attempt = [a for a in entry["attempts"] if a["state"] != "failed"][-1]
            result = {"state": "generated", "number": attempt["number"], "sha256": attempt["sha256"],
                      "cost_usd": attempt.get("cost_usd"),
                      "attempts_left": settings.max_attempts - attempts_used(entry)}
            return {**result, **_preview(settings, job, result, plan_id)}
        if paid_disabled:
            return {"state": "disabled", "message": "Paid generation is disabled; only an existing unreviewed candidate can be reused."}
        blocked = _blocked(settings, job["id"], repairing=bool(repair_note))
        if blocked:
            log.event("image.generate", blocked["state"], target=plan_id)
            return blocked
        ensure_ledger(settings, job["target"])
        result = _attempts(settings, job, job_path, repair_note, log, sleep)
        if result["state"] == "generated":
            result.update(_preview(settings, job, result, plan_id))
        log.event("image.generate", result["state"], target=plan_id,
                  cost_usd=result.get("cost_usd"), attempt=result.get("number"))
        return result


def _blocked(settings: ImageSettings, job_id: str, *, repairing: bool = False) -> dict | None:
    ledger = settings.ledger()
    entry = ledger["jobs"].get(job_id)
    if entry and entry.get("accepted"):
        return None  # learning_image answers with the accepted image; no spending
    if unknown_calls(ledger):
        return {"state": "waiting-unknown",
                "message": "a paid image call has an unknown outcome; generation waits "
                           "(settled automatically after 24 hours)"}
    if entry and awaiting_review(entry) and not repairing:
        return None
    if entry and attempts_used(entry) >= settings.max_attempts:
        return {"state": "exhausted", "message": "all attempts used; only interactive work"}
    if not budget_left(ledger, settings.today(), settings.reservation_usd, settings.monthly_usd):
        return {"state": "budget-exhausted", "message": "the monthly image budget is used up"}
    return None


def attempts_used(entry: dict) -> int:
    """Paid attempts of the current frame: an owner grant starts a new one (fix-51)."""
    return sum(1 for a in frame(entry) if a["state"] not in ("failed", "unknown"))


def frame(entry: dict) -> list[dict]:
    """The attempts since the owner's last grant; all of them without a grant. The same rule
    as `current_frame` in tools/learning_image.py, which enforces the bound."""
    grants = entry.get("grants") or []
    if not grants:
        return list(entry["attempts"])
    return [a for a in entry["attempts"] if a["number"] >= grants[-1]["first_attempt"]]


def grant(settings: ImageSettings, plan_id: str, request_id: str) -> dict | None:
    """The owner's explicit approval opens one new frame of `max_attempts` paid attempts for an
    image; the old attempts and their costs stay in the ledger, the budgets still apply. Once
    per request (a repeated run preparation grants nothing). Returns (grant, new) or None when
    the image has no ledger entry."""
    from ..log import now_iso
    from ..state.files import write_json
    with images_lock(settings.lock_path, settings.lock_timeout_s):
        ledger = settings.ledger()
        entry = ledger.get("jobs", {}).get(plans.job_id(settings.learner, plan_id))
        if entry is None:
            return None
        known = next((g for g in entry.get("grants", []) if g.get("request") == request_id), None)
        if known is not None:
            return known, False
        value = {"request": request_id, "at": now_iso(), "attempts": settings.max_attempts,
                 "first_attempt": max((a["number"] for a in entry["attempts"]), default=0) + 1}
        entry.setdefault("grants", []).append(value)
        write_json(settings.state_dir / "ledger.json", ledger)
        return value, True


def awaiting_review(entry: dict) -> bool:
    real = [a for a in entry["attempts"] if a["state"] != "failed"]
    return bool(real) and real[-1]["state"] == "generated"


def _attempts(settings, job, job_path, repair_note, log, sleep) -> dict:
    files = {"repair.txt": repair_note} if repair_note else None
    args = ["--job", str(job_path)] + (["--repair", "{tmp}/repair.txt"] if repair_note else [])
    def attempt_line(outcome: str, started: float) -> None:
        log.event("image.attempt", outcome, target=job["id"], duration_s=time.monotonic() - started)

    for delay in (*RETRY_DELAYS, None):
        before = _attempt_count(settings, job["id"])
        started = time.monotonic()
        try:
            answer = call(settings, "generate", args, job["target"], with_key=True, files=files)
            result = _success(settings, job["id"], answer)
            attempt_line(result["state"], started)
            return result
        except ExecutorTimeout:
            attempt_line("unknown", started)
            return {"state": "unknown", "message": "the call timed out after sending; "
                                                   "generation waits until it is settled"}
        except ExecutorError as exc:
            if _attempt_count(settings, job["id"]) == before:
                # Refused before any request (cap, missing repair base, …): not an attempt,
                # so neither an earlier attempt's failure nor a retry applies.
                return {"state": "error", "message": str(exc)}
            last = _last_attempt(settings, job["id"])
            failure = last.get("failure") if last and last["state"] == "failed" else None
            attempt_line(failure or (last or {}).get("state") or "error", started)
            if failure in RETRYABLE and delay is not None and _blocked(settings, job["id"], repairing=bool(repair_note)) is None:
                log.event("image.generate", f"retry ({failure})", target=job["id"])
                sleep(delay)
                continue
            if last and last["state"] == "unknown":
                return {"state": "unknown", "message": str(exc)}
            if failure:
                return {"state": "failed", "failure": failure, "cost_usd": "0", "message": str(exc)}
            return {"state": "error", "message": str(exc)}
    raise AssertionError("unreachable")


def _success(settings: ImageSettings, job_id: str, answer: dict) -> dict:
    if answer.get("state") == "accepted":
        return {"state": "accepted", "path": answer.get("path"),
                "message": "already accepted; insertion requires the independent figure review"}
    entry = settings.ledger()["jobs"][job_id]
    return {"state": "generated", "number": answer["number"], "sha256": answer["sha256"],
            "cost_usd": answer.get("cost_usd"),
            "attempts_left": settings.max_attempts - attempts_used(entry)}


def _attempt_count(settings: ImageSettings, job_id: str) -> int:
    entry = settings.ledger()["jobs"].get(job_id)
    return len(entry["attempts"]) if entry else 0


def _last_attempt(settings: ImageSettings, job_id: str) -> dict | None:
    entry = settings.ledger()["jobs"].get(job_id)
    return entry["attempts"][-1] if entry and entry["attempts"] else None


def _preview(settings: ImageSettings, job: dict, result: dict, plan_id: str | None = None) -> dict:
    """Publication preview + both files under .school-notes/images/ for the LLM to view."""
    command = "preview-banner" if job["role"] == "banner" else "preview-infographic"
    plan_id = plan_id or job["id"].removeprefix(f"{settings.learner}-")
    preview = call(settings, command, ["--job", str(plans.job_path(settings, plan_id))],
                   job["target"])
    from ..state.files import write_json
    ledger = settings.ledger()
    attempt = next(a for a in ledger["jobs"][job["id"]]["attempts"] if a["number"] == result["number"])
    attempt["preview_sha256"] = preview["sha256"]
    write_json(settings.state_dir / "ledger.json", ledger)
    folder = Path(preview["path"]).parent
    stem = f"{plan_id}-{result['number']}"
    image = f".school-notes/images/{stem}.png"
    publication = f".school-notes/images/{stem}-publication.webp"
    # Into the container-controlled tree: never through a planted symlink (7.6).
    safefs.copy_in(folder / "image.png", settings.worktree, image)
    safefs.copy_in(Path(preview["path"]), settings.worktree, publication)
    return {"image": image, "preview": publication,
            "preview_sha256": preview["sha256"]}


def settle_unknown(settings: ImageSettings, *, log: Log, max_age_hours: float = 24) -> list[dict]:
    """Settle unknown-outcome calls older than 24 hours, in this and the previous school
    year's ledger (a call left open over the summer must not block forever); the caller
    e-mails the result."""
    settled = []
    for ledger_settings in (settings.previous_year(), settings):
        settled += _settle_one(ledger_settings, log=log, max_age_hours=max_age_hours)
    return settled


def _settle_one(settings: ImageSettings, *, log: Log, max_age_hours: float) -> list[dict]:
    if not (settings.state_dir / "ledger.json").is_file():
        return []
    with images_lock(settings.lock_path, settings.lock_timeout_s):
        if not unknown_calls(settings.ledger()):
            return []
        settled = call(settings, "settle", ["--max-age-hours", str(max_age_hours)],
                       plans.target("settle"))["settled"]
    for item in settled:
        log.event("image.settle", item["state"], target=item["job"], cost_usd=item["cost_usd"])
    return settled
