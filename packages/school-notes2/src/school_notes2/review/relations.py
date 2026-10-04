"""Review identities, reference-aware closures and one-round disagreement replies."""

import re
from pathlib import Path

from ..state import safefs
from ..wiki import decisions, frontmatter
from ..wiki.pages import CODE_FENCE, wiki_pages


def details(text: str, item_id: str) -> dict:
    page = frontmatter.split(text)
    result = dict(page.meta.get("item_details", {}).get(item_id, {}))
    if "file" not in result:  # Existing reports have only a location in their heading.
        match = re.search(r"^### " + re.escape(item_id) + r" [–-] (wiki/[^\s:]+)(?::\d+)?\s*$", page.body, re.M)
        if match:
            result["file"] = match[1]
    return {"round": 1, "chain": 0, **result}


def page_ids(repo: Path, rel: str) -> tuple[set[str], set[str]]:
    if not rel.startswith("wiki/") or not rel.endswith(".md") or not safefs.is_file(repo, rel):
        return set(), set()
    page = frontmatter.split(safefs.read_text(repo, rel))
    body = CODE_FENCE.sub("", page.body)
    # Only anchors attached to actual open-question items count.
    lines = body.splitlines()
    questions = {decisions.ANCHOR.match(lines[anchor - 1])[1]
                 for section in decisions._question_sections(lines)
                 for _, _, anchor in decisions._question_items(section) if anchor is not None}
    confirmed = {d["id"] for d in page.meta.get("decisions", []) if isinstance(d, dict) and "id" in d}
    return questions, confirmed


def closure_problems(repo: Path, closure: dict) -> list[str]:
    rel, key, status = closure["file"], closure["item_id"], closure["status"]
    if status == "disagree" and not closure.get("note", "").strip():
        return ["disagree requires a nonempty note"]
    if not safefs.is_file(repo, rel):
        return []  # check_result reports missing files.
    record = details(safefs.read_text(repo, rel), key)
    if record["round"] == 2 and status not in ("fixed", "question", "open"):
        return ["round: 2 can close only as fixed or question"]
    if status not in ("question", "settled"):
        return []
    q, d = page_ids(repo, record.get("file", ""))
    if status == "question":
        return [] if closure.get("question_id") in q else ["question_id must name an open question on the item's page"]
    if (closure.get("question_id") in q) ^ (closure.get("decision_id") in d):
        return []
    return ["settled needs an existing question_id or decision_id on the item's page"]


def inventory(repo: Path) -> dict:
    from . import files
    pages = {}
    for rel in sorted(wiki_pages(repo)):
        q, d = page_ids(repo, rel)
        if q or d:
            pages[rel] = {"questions": sorted(q), "decisions": sorted(d)}
    items = {}
    for path in files.review_files(repo):
        text = safefs.read_text(repo, path.relative_to(repo).as_posix())
        for key, status in (files.read_items(repo, path) or {}).items():
            full = f"{path.relative_to(repo).as_posix()}#{key}"
            items[full] = {**details(text, key), "status": status}
    return {"pages": pages, "items": dict(sorted(items.items()))}


def route(finding: dict, known: dict) -> tuple[str, bool]:
    """Return (open/owner/pending, unlocated), never silently drop unknown references."""
    ref = finding.get("relates_to")
    if ref is None:
        return "open", finding.get("unlocated", False)
    page = known["pages"].get(finding["file"], {})
    if ref in page.get("questions", []):
        return "pending", False
    if ref in page.get("decisions", []):
        return "owner", not bool(finding.get("new_evidence", "").strip())
    other = known["items"].get(ref)
    if other:
        return ("pending" if other["status"] in ("open", "owner", "question") else "open"), False
    return "open", True


def reply(repo: Path, key: str, verdict: str, answer: str) -> str:
    """An idempotent reviewer response; a kept disagreement reopens exactly once."""
    from .files import ClosureError, compute_status
    if verdict not in ("accept", "keep") or not answer.strip():
        raise ClosureError("reviewer response needs accept/keep and a nonempty answer")
    rel, sep, item_id = key.partition("#")
    if not sep or not rel.startswith("docs/review/") or not re.fullmatch(r"R\d+", item_id):
        raise ClosureError("reviewer response needs the full review-file#R<n> key")
    text = safefs.read_text(repo, rel)
    page = frontmatter.split(text)
    records = dict(page.meta.get("item_details", {}))
    record = details(text, item_id)
    response = {"verdict": verdict, "answer": answer}
    if record.get("response") == response:
        return rel
    if page.meta.get("items", {}).get(item_id) != "disagree" or record["round"] != 1 or record.get("response"):
        raise ClosureError("only an unanswered round-1 disagreement accepts a response")
    record["response"] = response
    items = dict(page.meta["items"])
    if verdict == "keep":
        items[item_id], record["round"] = "open", 2
    records[item_id] = record
    body = text.rstrip() + f"\n\n## Válasz ({item_id})\n\n{verdict}: {' '.join(answer.split())}\n"
    safefs.write_text(repo, rel, frontmatter.set_keys(body, {
        "items": items, "item_details": records, "status": compute_status(items)}))
    return rel
