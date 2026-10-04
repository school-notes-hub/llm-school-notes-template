"""Durable writer assignments: subjects.json order, one subject per call (T-121)."""

from pathlib import PurePosixPath

from ..review import relations
from ..state import safefs
from .batch import split_ranges
from . import cards


def review_order(item):
    return (item.get("round", 1) != 2, PurePosixPath(item["file"]).name[:10],
            int(item["item_id"][1:]), item["file"], item["item_id"])


def select_reviews(reviews, limit=20):
    return sorted(reviews, key=review_order)[:limit]


def assignments(repo, packages: list[dict], pages: list[dict], reviews: list[dict],
                pending: list[dict], limit: int = 30, review_limit: int = 20) -> list[dict]:
    config = safefs.read_json(repo, "tools/subjects.json") or {}
    order = list(config.get("subjects", {}))
    reviews = select_reviews(reviews, review_limit)
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
