"""The independent figure reviewer's verdicts, checked against the current content (no LLM here:
the reviewer runs in the owner's session and hands its verdicts over)."""

from pathlib import Path

from ..schemas import validate
from . import commissions, context


def is_error(finding):
    """A finding blocks only as `hiba`; receipts written before severity was required count as one."""
    return finding.get("severity", "hiba") == "hiba"



def validate_output(value: dict, assigned: dict, repo: Path, briefs: list[dict]) -> None:
    validate("figure-review", value)
    wanted = {i["id"]: i["key"] for i in assigned["figures"]}
    got = [i["id"] for i in value["figures"]]
    if len(got) != len(set(got)) or set(got) != set(wanted):
        raise ValueError("every assigned figure needs exactly one verdict, no extras")
    by_id = {b["id"]: b for b in briefs}
    for verdict in value["figures"]:
        brief = by_id[verdict["id"]]
        current = context.verdict_key(repo, brief, commissions.candidate(repo, brief))
        if verdict["key"] != wanted[verdict["id"]] or current != verdict["key"]:
            raise ValueError(f"{verdict['id']}: stale verdict key")
        if verdict["verdict"] == "accept" and any(is_error(d) for d in verdict["defects"] + verdict["text_mismatch"]):
            raise ValueError("accept cannot contain outstanding defects or text mismatches")
        if verdict["verdict"] != "accept" and not any(is_error(d) for d in verdict["defects"] + verdict["text_mismatch"]):
            raise ValueError("repair/reject requires a hiba defect; suggestions do not block acceptance")
        uses = [context.page_context(repo, brief["page"])] + context.other_uses(
            repo, brief, commissions.candidate(repo, brief))
        decisions = {d["id"] for use in uses for d in use["decisions"]}
        if verdict["relates_to"] in decisions and not verdict.get("new_evidence", "").strip():
            raise ValueError("decision-related finding requires new_evidence")


def verdict_for(receipt: dict, fid: str, *, unique=False) -> dict:
    found = [v for v in receipt.get("review", {}).get("figures", []) if v["id"] == fid]
    if not found or (unique and len(found) != 1):
        return {}
    return {**found[0], **{k: [d for d in found[0][k] if is_error(d)]
                          for k in ("defects", "text_mismatch") if k in found[0]}}
