"""Durable writer assignments: subjects.json order, one subject per call (T-121)."""

import re
from datetime import date
from pathlib import PurePosixPath

from ..review import relations
from ..state import safefs
from .batch import split_ranges
from . import cards


def review_order(item):
    # Regular reports use YYYY-MM-DD; repair reports start with a YYYYMMDD run ID.
    match = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})-", PurePosixPath(item["file"]).name)
    try:
        day = date(*map(int, match.groups())) if match else date.max
    except ValueError:
        day = date.max
    return (item.get("round", 1) != 2, day,
            int(item["item_id"][1:]), item["file"], item["item_id"])


def review_groups(reviews, *, mode="cron", repo=None):
    ordered = sorted(reviews, key=lambda i: (
        mode == "interactive" and i.get("status") != "owner", *review_order(i)))
    inventory = relations.inventory(repo)["items"] if repo is not None and reviews else {}
    embedded = relations.related_pages(repo) if inventory else {}
    groups = {}
    for item in ordered:
        key = item["file"] + "#" + item["item_id"]
        page = inventory.get(key, {}).get("file") or key
        page = min(embedded.get(page, {page}))
        groups.setdefault(page, []).append(item)
    return groups


def select_reviews(reviews, limit=20, *, mode="cron", repo=None):
    selected = []
    for number, group in enumerate(review_groups(reviews, mode=mode, repo=repo).values()):
        if number == 0 and len(group) > limit:
            return group[:limit]
        if len(selected) + len(group) <= limit:
            selected.extend(group)
    return selected


def assignments(repo, packages: list[dict], pages: list[dict], reviews: list[dict],
                pending: list[dict], limit: int = 30, review_limit: int = 20, *,
                mode: str = "cron") -> list[dict]:
    config = safefs.read_json(repo, "tools/subjects.json") or {}
    order = list(config.get("subjects", {}))
    reviews = select_reviews(reviews, review_limit, mode=mode, repo=repo)
    inventory = relations.inventory(repo)["items"] if reviews else {}
    embedded = relations.related_pages(repo)
    review_subjects = {i["file"] + "#" + i["item_id"]:
                       subject(inventory.get(i["file"] + "#" + i["item_id"], {}).get("file", ""), embedded)
                       for i in reviews}
    subjects = ({p["subject"] for p in packages} | {subject(i["page"], embedded) for i in pending}
                | set(review_subjects.values())) - {""}
    ordered = [s for s in order if s in subjects] + sorted(subjects - set(order))
    if not ordered and (reviews or pending):
        ordered = [order[0] if order else ""]
    out = []
    for name in ordered:
        indices = [n for n, p in enumerate(packages) if p["subject"] == name]
        own = sorted((p for p in pages if subject(p["path"]) == name), key=lambda p: p["seq"])
        # D16 admits an oversized package only on its own; no topic or aggregate split.
        chunks = split_ranges(len(own), limit) if len(indices) == 1 and len(own) > limit else [(1, len(own))]
        for first, last in chunks:
            out.append({"subject": name, "packages": indices,
                        "seqs": [p["seq"] for p in own[first - 1:last]],
                        "open_review_items": [], "pending_images": []})
    # Every assignment appears once, including D36 and subjectless legacy items.
    for item in reviews:
        name = review_subjects[item["file"] + "#" + item["item_id"]]
        target = next((c for c in out if name and c["subject"] == name), out[0])
        target["open_review_items"].append(item)
    for item in sorted(pending, key=lambda i: (i["page"], i["plan_id"])):
        name = subject(item["page"], embedded)
        target = next((c for c in out if name and c["subject"] == name), out[0])
        target["pending_images"].append(item)
    for call in out:
        card = cards.load(repo, call["subject"]) if call["subject"] else None
        if card is not None:
            call["card"] = card
    return out


def subject(path: str, embedded=None) -> str:
    if path.startswith("wiki/assets/"):
        # A shared asset has one writer: the first embedding content page by path.
        return next((s for p in sorted((embedded or {}).get(path, []))
                     if (s := subject(p))), "")
    parts = path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] in ("wiki", "sources") else ""


def ranges(calls: list[dict]) -> list[list[int]]:
    return [[min(c["seqs"]), max(c["seqs"])] if c["seqs"] else [0, 0] for c in calls]


def fix_assignments(repo, reviews, pending, limit=30):
    """Every item once; whole page groups where possible, all figures in call one."""
    groups = review_groups(reviews, repo=repo)
    embedded = relations.related_pages(repo)
    out, chunk, name = [], [], None
    for page, items in groups.items():
        own = subject(page, embedded)
        for first in range(0, len(items), limit):
            portion = items[first:first + limit]
            if chunk and (own != name or len(chunk) + len(portion) > limit):
                out.append(_fix_call(repo, name, chunk))
                chunk = []
            name = own
            chunk += portion
    if chunk:
        out.append(_fix_call(repo, name, chunk))
    if pending:
        # Figures precede the first page group in the same call, without an extra invocation.
        if not out:
            out.append(_fix_call(repo, "", []))
        out[0]["pending_figure_ids"] = sorted(e["commission"]["id"] for e in pending)
    return out


def _fix_call(repo, name, items):
    call = {"subject": name, "packages": [], "seqs": [], "open_review_items": items,
            "pending_images": [], "pending_figure_ids": []}
    card = cards.load(repo, name) if name else None
    if card is not None:
        call["card"] = card
    return call
