"""Tool-only insertion from a current independent accept verdict, with replayable writes."""

import hashlib
from pathlib import Path

from ..state import safefs
from ..wiki import markers, rights
from ..wiki.pages import relative
from . import commissions, context, pending, licenses
from .review import verdict_for, validate_output

VERDICTS = "docs/review/verdicts.json"


def insert(repo: Path, brief: dict, receipt: dict, *, at: str) -> list[str]:
    """`receipt` must carry the reviewer's verdict (`sn close` builds it), never the writer's.

    The page is written last: a crash during evidence writes is harmless to replay.
    Recompute the key at call time, including after rebase; never trust an earlier check.
    `rights: authored` is documentary; rights.authored_candidate decides eligibility.
    """
    if receipt.get("status") != "reviewed" or not receipt.get("model"):
        raise ValueError("independent review receipt required")
    commissions.validate_assignments(repo, [{k: brief[k] for k in ("id", "page", "kind")}])
    commissions.check_identity(repo, brief)
    fid = brief["id"]
    verdict = verdict_for(receipt, fid, unique=True)
    if verdict.get("verdict") != "accept":
        raise ValueError("one independent accept verdict is required")
    validate_output({"figures": [verdict], "owner_notes": receipt["review"]["owner_notes"]},
                    {"figures": [{"id": fid, "key": verdict["key"]}]}, repo, [brief])
    candidate = commissions.candidate(repo, brief)
    page = brief["page"]
    text = safefs.read_text(repo, page)
    directory = f"docs/evidence/media/{fid}"
    record = {"commission": brief, "candidate": candidate, "verdict": verdict,
              "verifier": receipt["model"], "at": at}
    if candidate.get("asset"):
        record["output_sha256"] = hashlib.sha256(safefs.read_bytes(repo, candidate["asset"])).hexdigest()
    request = licenses.request_for(repo, fid)
    if request:
        grant = licenses.permission(repo, request)
        if not grant:
            raise ValueError("licensed insertion needs current public permission")
        record.update(license_request=request, license=grant, rights="licensed")
    elif candidate.get("asset"):
        known = rights.generated(repo, candidate["asset"])
        if known and known[0] == "generated":
            record["rights"] = "generated"
        elif rights.authored_candidate(repo, candidate):
            record["rights"] = "authored"
    new_text = text if "mermaid" in candidate else _insert(text, page, brief, candidate, verdict, directory, repo)
    new_text = context.follow_replacement(new_text, brief, candidate)
    files = [f"{directory}/figure.json", VERDICTS]
    safefs.write_json(repo, files[0], record)
    _record_verdict(repo, brief, candidate, verdict, receipt["model"], at)
    if new_text != text:
        safefs.write_text(repo, page, new_text)
    files.append(page)
    if candidate.get("asset"):
        files.append(candidate["asset"])
    pending.clear(repo, fid)
    return sorted(files + ([pending.PATH] if safefs.is_file(repo, pending.PATH) else []))


def _insert(text, page, brief, candidate, verdict, directory, repo):
    fid = brief["id"]
    existing = markers.read(text, f"figure-{fid}")
    if existing is not None:
        return text  # validate_output already checked the actual embedded version
    matches = commissions.markers(repo).get(fid, [])
    if len(matches) != 1 or matches[0][0] != page:
        raise ValueError("insertion needs exactly one marker on the commission's page")
    alt = candidate["alt"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    if "\n" in alt:
        raise ValueError("alt must fit on one line")
    asset = relative(page, candidate["asset"])
    sha = hashlib.sha256(safefs.read_bytes(repo, candidate["asset"])).hexdigest()
    body = f"![{alt}](<{asset}>)\n\n"
    if candidate["caption"]:
        body += candidate["caption"] + "\n\n"
    body += (f"<!-- image-description\nasset: {asset}\nsha256: {sha}\n"
             f"observed: {comment_safe(' '.join(verdict['observed'].split()))}\n"
             f"evidence: {relative(page, directory + '/figure.json')}\n-->")
    block = markers.wrap(f"figure-{fid}", body).rstrip("\n")
    # A reviewed image stays in place until this single atomic page replacement.
    start = matches[0][1]
    match = commissions.MARKER.match(text, start)
    text = text[:start] + block + text[match.end():]
    return context.without_replaced(text, page, brief.get("replaces"))


def _record_verdict(repo, brief, candidate, verdict, model, at):
    records = safefs.read_json(repo, VERDICTS, [])
    record = {"role": "figure-review", "file": brief["page"], "id": brief["id"],
              "key": verdict["key"], "verdict": "accept", "model": model, "at": at,
              "commission": brief, "candidate": candidate}
    records = [r for r in records if not (r.get("role") == "figure-review" and
                                          r.get("file") == brief["page"] and r.get("id") == brief["id"])]
    if brief.get("replaces"):
        records = [r for r in records if not (r.get("role") == "figure-review" and
                    r.get("file") == brief["page"] and r.get("candidate", {}).get("asset") == brief["replaces"])]
    records.append(record)
    safefs.write_json(repo, VERDICTS, sorted(records, key=lambda r: (r["file"], r["key"], r["role"])))


def without_record(repo: Path) -> list[dict]:
    """Inserted figure blocks whose accepted verdict lives only in the evidence record – no
    `docs/review/verdicts.json` figure-review record (sn 0.3.10): as records for `invalidated`."""
    from ..wiki.pages import wiki_pages
    recorded = {(r.get("file"), r.get("id")) for r in safefs.read_json(repo, VERDICTS, [])
                if r.get("role") == "figure-review" and not r.get("night_spec")}
    out = []
    for page in sorted(wiki_pages(repo)):
        for name in markers.names(safefs.read_text(repo, page)):
            fid = name[7:] if name.startswith("figure-") else None
            rel = f"docs/evidence/media/{fid}/figure.json"
            if not fid or (page, fid) in recorded or not safefs.is_file(repo, rel):
                continue
            evidence = safefs.read_json(repo, rel, {})
            verdict = evidence.get("verdict", {})
            if verdict.get("verdict") == "accept" and evidence.get("commission") and evidence.get("candidate"):
                out.append({"role": "figure-review", "file": page, "id": fid, "key": verdict.get("key", ""),
                            "commission": evidence["commission"], "candidate": evidence["candidate"]})
    return out


def invalidated(repo: Path) -> list[dict]:
    """T-154: report stale accepts after rebase; no LLM, retry or publication hold. Over the
    `verdicts.json` records and the inserted figures whose verdict only the evidence holds."""
    stale = []
    for record in safefs.read_json(repo, VERDICTS, []) + without_record(repo):
        if record.get("role") != "figure-review":
            continue
        if removed(repo, record):
            continue
        if record.get("night_spec"):
            continue  # Historical nightly figure verdicts are kept as records only.
        if not context.key_matches(repo, record["commission"], record["candidate"], record.get("key", "")):
            stale.append(record)
    return sorted(stale, key=lambda r: (r["file"], r.get("key", "")))


def removed(repo: Path, record: dict) -> bool:
    if not safefs.is_file(repo, record["file"]):
        return True
    if record.get("night_spec"):
        return False  # Historical nightly figure verdicts are kept as records only.
    text = safefs.read_text(repo, record["file"])
    return (markers.read(text, f"figure-{record['id']}") is None and
            not any(page == record["file"] for page, _ in commissions.markers(repo).get(record["id"], [])))


def comment_safe(text: str) -> str:
    """No `--` inside an HTML comment: `-->` would expose its private contents."""
    while "--" in text:
        text = text.replace("--", "- -")
    return text
