"""Legacy internal generated-image receipt writer; never an MCP tool.

The LLM gives only the judgement fields. The tool fills the machine fields, runs
`learning_image.py review` (it writes the asset and the receipt), replaces the marker
with the image link and its `image-description` comment, and hands the evidence entry
to the evidence module.
"""

import hashlib
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from ..log import Log
from ..schemas import SchemaError, validate
from ..state import safefs
from . import plans
from .budget import images_lock
from .executor import ExecutorError, call, module
from .generate import attempts_used
from .settings import ImageSettings


def accept(settings: ImageSettings, plan_id: str, review: dict, *, verifier: str,
           append_evidence: Callable[[str, dict], None], log: Log) -> dict:
    """Returns {state, ...}; on acceptance `tool_writes` lists [{path, sha256}]."""
    plans.check_id(plan_id)
    try:
        validate("image-accept", review)
    except SchemaError as exc:
        return {"state": "error", "message": str(exc)}
    with images_lock(settings.lock_path, settings.lock_timeout_s):
        plans.restore(settings, [plan_id])
        job = plans.kept_job(settings, plan_id)
        entry = settings.ledger()["jobs"].get(job["id"]) if job else None
        if job is None or entry is None:
            return {"state": "error", "message": "no generated image for this plan"}
        attempt = _attempt(entry, review.get("attempt"))
        if attempt is None:
            return {"state": "error", "message": "no generated attempt to review"}
        report = _report(settings, job, attempt, review, verifier)
        try:
            answer = call(settings, "review", ["--job", str(plans.job_path(settings, plan_id)),
                                               "--report", "{tmp}/report.json"], job["target"],
                          files={"report.json": json.dumps(report, ensure_ascii=False)})
        except ExecutorError as exc:
            return {"state": "error", "message": str(exc)}
        if answer["state"] != "accepted":
            left = settings.max_attempts - attempts_used(settings.ledger()["jobs"][job["id"]])
            log.event("image.accept", "rejected", target=plan_id, attempt=attempt["number"])
            return {"state": "rejected", "attempts_left": left}
        result = _insert(settings, plan_id, job, attempt, answer, review, append_evidence)
        log.event("image.accept", "accepted", target=plan_id, attempt=attempt["number"])
        return result


def _attempt(entry: dict, number: int | None) -> dict | None:
    """The attempt under review: the given number, else the latest generated one."""
    if entry.get("accepted"):
        return next(a for a in entry["attempts"] if a["number"] == entry["accepted"]["attempt"])
    candidates = [a for a in entry["attempts"] if a["state"] == "generated"]
    if number is not None:
        candidates = [a for a in entry["attempts"] if a["number"] == number and a.get("sha256")]
    return candidates[-1] if candidates else None


def _report(settings: ImageSettings, job: dict, attempt: dict, review: dict, verifier: str) -> dict:
    """learning_image.py's review report: LLM verdict + tool-computed machine fields."""
    image = settings.state_dir / attempt["folder"] / "image.png"
    encoder = module(settings.script)
    banner = job["role"] == "banner"
    data = encoder.banner_webp(image) if banner else encoder.infographic_webp(image)
    publication = {"format": "webp", **({"quality": 85} if banner else {"lossless": True}),
                   "sha256": hashlib.sha256(data).hexdigest(),
                   "observed": review["publication"]["observed"],
                   "checked": review["publication"]["checked"]}
    report = {"verifier": verifier, "checked_at": datetime.now(timezone.utc).isoformat(),
              "sha256": attempt["sha256"], "observed": review["observed"],
              "decision": review["decision"], "checks": review["checks"],
              "material_defects": review["material_defects"],
              "description": review["description"], "publication": publication}
    if review.get("placement"):
        report["placement"] = review["placement"]
    return report


def _insert(settings, plan_id, job, attempt, answer, review, append_evidence) -> dict:
    asset = answer["path"]
    receipt_dir = f"docs/evidence/media/{job['id']}"
    page = _page_with_marker(settings, plan_id)
    if page is not None:
        text = safefs.read_text(settings.worktree, page)
        block = description_block(page, asset, answer["published_sha256"], job, review,
                                  f"{receipt_dir}/review-{attempt['number']}.json")
        safefs.write_text(settings.worktree, page, text.replace(plans.marker(plan_id), block, 1))
        append_evidence(page, evidence_entry(job, attempt, answer, review, receipt_dir))
    writes = [asset, *([page] if page else []), *_receipt_files(settings.worktree, receipt_dir)]
    return {"state": "accepted", "path": asset, "page": page,
            "tool_writes": [{"path": p, "sha256": _sha(settings.worktree, p)} for p in writes]}


def _page_with_marker(settings: ImageSettings, plan_id: str) -> str | None:
    """The single page holding the marker; None when it was already replaced."""
    pages = plans.find_markers(settings.worktree).get(plan_id, [])
    if len(pages) > 1:
        raise ValueError(f"marker of {plan_id} appears on more than one page: {', '.join(pages)}")
    return pages[0] if pages else None


def description_block(page: str, asset: str, sha256: str, job: dict, review: dict,
                      receipt: str) -> str:
    """The image link and the `image-description` comment, in the wiki's current format."""
    base = os.path.dirname(page)
    rel_asset = os.path.relpath(asset, base)
    alt = job["plan"]["visible_text"][0].replace("]", "")
    observed = comment_safe(" ".join(review["description"].split()))
    return (f"![{alt}]({rel_asset})\n\n<!-- image-description\nasset: {rel_asset}\n"
            f"sha256: {sha256}\nobserved: {observed}\n"
            f"evidence: {os.path.relpath(receipt, base)}\n-->")


def comment_safe(text: str) -> str:
    """No `--` inside an HTML comment: `-->` would end it and show the rest on the site."""
    while "--" in text:
        text = text.replace("--", "- -")
    return text


def evidence_entry(job, attempt, answer, review, receipt_dir) -> dict:
    """What the evidence module appends to the page's record (plan 4.8)."""
    return {"entry_id": f"image:{job['id']}:{attempt['number']}", "kind": "image",
            "image": answer["path"], "sha256": answer["published_sha256"],
            "original_sha256": attempt["sha256"], "observed": review["observed"],
            "decision": review["decision"], "description": review["description"],
            "checks": review["checks"], "receipt": f"{receipt_dir}/receipt-{attempt['number']}.json"}


def _receipt_files(worktree: Path, receipt_dir: str) -> list[str]:
    return safefs.walk_files(worktree, receipt_dir)


def _sha(worktree: Path, rel: str) -> str:
    return hashlib.sha256(safefs.read_bytes(worktree, rel)).hexdigest()
