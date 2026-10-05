"""Review identities, reference-aware closures and one-round disagreement replies."""

import re
from collections import Counter
from pathlib import Path

import yaml

from ..state import safefs
from ..wiki import decisions, frontmatter
from ..wiki.pages import CODE_FENCE, links, resolve, wiki_pages


def details(text: str | frontmatter.Page, item_id: str) -> dict:
    from .files import parse_report
    page = parse_report(text) if isinstance(text, str) else text
    result = dict(page.meta.get("item_details", {}).get(item_id, {}))
    if "file" not in result:  # Existing reports have only a location in their heading.
        match = re.search(r"^### " + re.escape(item_id) + r" [–-] (wiki/[^\s:]+)(?::\d+)?\s*$", page.body, re.M)
        if match:
            result["file"] = match[1]
    return {"round": 1, "chain": 0, **result}


def page_ids(repo: Path, rel: str) -> tuple[set[str], set[str]]:
    if not rel.startswith("wiki/") or not rel.endswith(".md") or not safefs.is_file(repo, rel):
        return set(), set()
    try:
        page = frontmatter.split(safefs.read_text(repo, rel))
    except (ValueError, yaml.YAMLError):
        return set(), set()  # The metadata check owns these errors.
    body = CODE_FENCE.sub("", page.body)
    # Only anchors attached to actual open-question items count.
    lines = body.splitlines()
    questions = {decisions.ANCHOR.match(lines[anchor - 1])[1]
                 for section in decisions._question_sections(lines)
                 for _, _, anchor in decisions._question_items(section) if anchor is not None}
    confirmed = {d["id"] for d in page.meta.get("decisions", []) if isinstance(d, dict) and "id" in d}
    return questions, confirmed


def closure_problems(repo: Path, closure: dict, *, page=None) -> list[str]:
    rel, key, status = closure["file"], closure["item_id"], closure["status"]
    if status == "disagree" and not closure.get("note", "").strip():
        return ["disagree requires a nonempty note"]
    if not safefs.is_file(repo, rel):
        return []  # check_result reports missing files.
    record = details(page if page is not None else safefs.read_text(repo, rel), key)
    if record["round"] == 2 and status not in ("fixed", "question", "open"):
        return ["round: 2 can close only as fixed or question"]
    if status not in ("question", "settled"):
        return []
    q, d = related_ids(repo, record.get("file", ""))
    if status == "question":
        return [] if closure.get("question_id") in q else ["question_id must name an open question on the item's page (for an asset, an embedding page)"]
    if (closure.get("question_id") in q) ^ (closure.get("decision_id") in d):
        return []
    return ["settled needs an existing question_id or decision_id on the item's page (for an asset, an embedding page)"]


def related_ids(repo: Path, rel: str) -> tuple[set[str], set[str]]:
    """An asset's question may live on any page that embeds it."""
    if rel.endswith(".md"):
        return page_ids(repo, rel)
    questions, confirmed = set(), set()
    for page in sorted(related_pages(repo).get(rel, [])):
        q, d = page_ids(repo, page)
        questions.update(q)
        confirmed.update(d)
    return questions, confirmed


def related_pages(repo: Path) -> dict[str, set[str]]:
    """Use the same embedding-page relation for closures, routing and reviewer input."""
    pages = {}
    for rel in sorted(wiki_pages(repo)):
        try:
            text = frontmatter.split(safefs.read_text(repo, rel)).body
        except (ValueError, yaml.YAMLError):
            continue  # Keep preparation/check routing usable for metadata repair.
        pages[rel] = {rel}
        for link in links(text):
            asset = resolve(rel, link.target)
            if link.image and asset and not asset.endswith(".md"):
                pages.setdefault(asset, set()).add(rel)
    return pages


def inventory(repo: Path) -> dict:
    from . import files
    pages = {}
    ids = {rel: page_ids(repo, rel) for rel in sorted(wiki_pages(repo))}
    for rel, related in sorted(related_pages(repo).items()):
        q = set().union(*(ids[page][0] for page in sorted(related)))
        d = set().union(*(ids[page][1] for page in sorted(related)))
        if q or d:
            pages[rel] = {"questions": sorted(q), "decisions": sorted(d)}
    items = {}
    for path in files.review_files(repo):
        page = files.read_report(repo, path)
        if page is None or not isinstance(page.meta.get("items"), dict):
            continue
        for key, status in page.meta["items"].items():
            full = f"{path.relative_to(repo).as_posix()}#{key}"
            items[full] = {**details(page, key), "status": status}
    return {"pages": pages, "items": dict(sorted(items.items()))}


def reviewer_inventory(repo: Path) -> dict:
    """The private reviewer input: active/disputed items grouped by their page."""
    known = inventory(repo)
    pages = {rel: {**ids, "items": {}} for rel, ids in known["pages"].items()}
    for key, item in known["items"].items():
        if item["status"] in ("open", "owner", "disagree"):
            page = pages.setdefault(item.get("file", ""), {"questions": [], "decisions": [], "items": {}})
            page["items"][key] = item
    return {"pages": dict(sorted(pages.items()))}


def chain(finding: dict, known: dict) -> int:
    other = known["items"].get(finding.get("relates_to"))
    if other:
        return min(1, other["chain"] + int(other["status"] in ("fixed", "settled")))
    return 0


def route(finding: dict, known: dict) -> tuple[str, bool]:
    """Return (open/owner/pending, unlocated), never silently drop unknown references."""
    from . import attempts
    ref = finding.get("relates_to")
    if attempts.decision(finding, known):
        return "owner", False
    if ref is None:
        return "open", False
    page = known["pages"].get(finding["file"], {})
    if ref in page.get("questions", []):
        return "pending", False
    if ref in page.get("decisions", []):
        return "owner", False
    other = known["items"].get(ref)
    if other:
        if other["status"] in ("open", "owner", "question", "disagree"):
            return "pending", False
        return attempts.failed_status(other), False
    return "open", True


def valid_responses(responses: list[dict], known: dict) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    counts = Counter(r["key"] for r in responses)
    for response in sorted(responses, key=lambda r: (r["key"], r["verdict"], r["answer"])):
        item = known["items"].get(response["key"], {})
        if (item.get("status") == "disagree" and item.get("round") == 1
                and not item.get("response") and counts[response["key"]] == 1):
            kept.append(response)
        else:
            reason = "duplicate response key" if counts[response["key"]] > 1 else "not an unanswered round-1 disagreement"
            dropped.append({"key": response["key"], "reason": reason})
    return kept, dropped


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
        from . import attempts
        items[item_id], record["round"] = attempts.failed_status(record), 2
    records[item_id] = record
    body = text.rstrip() + f"\n\n## Válasz ({item_id})\n\n{verdict}: {' '.join(answer.split())}\n"
    safefs.write_text(repo, rel, frontmatter.set_keys(body, {
        "items": items, "item_details": records, "status": compute_status(items)}))
    return rel
