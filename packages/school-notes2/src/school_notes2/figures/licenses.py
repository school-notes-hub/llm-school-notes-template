"""Owner-recorded material licenses; no inference from a filename or a review."""

from ..state import safefs
from ..schemas import validate
from ..wiki.decisions import valid_date
from ..wiki.lesson_log import plain
from ..wiki.pages import sha256
from . import requests

PATH = "docs/licenses.json"


def load(repo):
    records = safefs.read_json(repo, PATH, [])
    validate("licenses", records)
    keys = set()
    for record in records:
        if not valid_date(record["on"]):
            raise ValueError("license date must be a real YYYY-MM-DD date")
        if record["scope"] == "public-with-credit" and not record["credit"].strip():
            raise ValueError("public permission requires a credit")
        if any(c in record["credit"] for c in "\r\n"):
            raise ValueError("credit must be a single public-safe line")
        key = record["sha256"], record.get("request_id", "")
        if key in keys:
            raise ValueError("duplicate material/request license")
        keys.add(key)
    records = [{k: r[k] for k in ("sha256", "granted_by", "scope", "credit", "own_work_confirmed", "on", "request_id") if k in r} for r in records]
    return sorted(records, key=lambda r: (r["sha256"], r.get("request_id", "")))


def permission(repo, request):
    if not safefs.is_file(repo, request["source"]) or sha256(repo, request["source"]) != request["content_sha256"]:
        return None
    records = [r for r in load(repo) if r["sha256"] == (request["original_sha256"] or request["content_sha256"])]
    # A request-specific owner decision takes precedence, including an explicit denial.
    specific = [r for r in records if r.get("request_id") == request["id"]]
    records = specific or [r for r in records if request["original_sha256"] and "request_id" not in r
                           and request["origin"] == "teacher-own"]
    return next((r for r in records if r["scope"] == "public-with-credit" and r["own_work_confirmed"]), None)


def request_for(repo, fid):
    return next((r for r in requests.load(repo) if r["id"] == fid), None)


def candidate(repo, brief, value, request=None):
    request = request or request_for(repo, brief["id"])
    if not request or value.get("state") != "candidate":
        return value
    grant = permission(repo, request)
    if not grant:
        raise ValueError("a requested teacher image needs public permission before becoming a wiki candidate")
    if not brief.get("source_image") or brief["source_image"]["path"] != request["source"]:
        raise ValueError("licensed figure must give the reviewer its requested source and crop")
    credit = plain(grant["credit"])
    caption = value.get("caption", "")
    if not caption.endswith(credit):
        caption = (caption + "\n\n" + credit).strip()
    return {**value, "caption": caption}


def records(repo):
    """Presence binds this asset to the revocable request route, even if now invalid."""
    found = {}
    for path in safefs.glob(repo, "docs/evidence/media", "docs/evidence/media/**/figure.json"):
        record = safefs.read_json(repo, path, {})
        asset = record.get("candidate", {}).get("asset")
        if record.get("license_request") and asset:
            found.setdefault(asset, []).append((path, record))
    return found


def rights(repo, asset, *, recorded=None):
    digest = sha256(repo, asset)
    recorded = records(repo) if recorded is None else recorded
    for path, record in recorded.get(asset, []):
        request = record.get("license_request")
        if (not request or record.get("candidate", {}).get("asset") != asset or
                record.get("output_sha256") != digest or record.get("verdict", {}).get("verdict") != "accept"):
            continue
        current = request_for(repo, request["id"])
        if current == request and permission(repo, current) == record.get("license"):
            return "licensed", path
    return None


def preflight(repo):
    """Owner data and withdrawn grants must never consume writer failure strikes."""
    from ..state.errors import NeedsOwner
    from ..wiki.pages import wiki_pages
    from ..wiki.public import linked_targets
    try:
        load(repo)
        recorded = records(repo)
        assets, _ = linked_targets(repo, sorted(wiki_pages(repo)))
        invalid = [asset for asset in sorted(assets) if safefs.is_file(repo, asset)
                   and any(record.get("output_sha256") == sha256(repo, asset)
                           for _, record in recorded.get(asset, []))
                   and rights(repo, asset, recorded=recorded) is None]
        if invalid:
            raise ValueError("permission changed or withdrawn: " + ", ".join(invalid))
    except (ValueError, OSError) as exc:
        raise NeedsOwner(f"invalid image permission: {exc}",
                         todo="correct docs/licenses.json or remove the affected image in `school-notes chat`") from exc
