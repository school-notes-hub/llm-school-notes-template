"""Durable writer assignments: subjects.json order, one subject per call (T-121)."""

from ..review import relations
from ..state import safefs
from .batch import split_ranges
from . import cards


def assignments(repo, packages: list[dict], pages: list[dict], reviews: list[dict],
                pending: list[dict], limit: int = 30) -> list[dict]:
    config = safefs.read_json(repo, "tools/subjects.json") or {}
    order = list(config.get("subjects", {}))
    inventory = relations.inventory(repo)["items"] if reviews else {}
    review_subjects = {i["file"] + "#" + i["item_id"]:
                       _subject(inventory.get(i["file"] + "#" + i["item_id"], {}).get("file", ""))
                       for i in reviews}
    subjects = ({p["subject"] for p in packages} | {_subject(i["page"]) for i in pending}
                | set(review_subjects.values())) - {""}
    ordered = [s for s in order if s in subjects] + sorted(subjects - set(order))
    out = []
    for subject in ordered:
        indices = [n for n, p in enumerate(packages) if p["subject"] == subject]
        own = sorted((p for p in pages if _subject(p["path"]) == subject), key=lambda p: p["seq"])
        # D16 admits an oversized package only on its own; no topic or aggregate split.
        chunks = split_ranges(len(own), limit) if len(indices) == 1 and len(own) > limit else [(1, len(own))]
        for first, last in chunks:
            seqs = [p["seq"] for p in own[first - 1:last]]
            out.append({"subject": subject, "packages": indices, "seqs": seqs,
                        "open_review_items": [i for i in reviews if review_subjects[
                            i["file"] + "#" + i["item_id"]] == subject],
                        "pending_images": [i for i in pending if _subject(i["page"]) == subject]})
    for call in out:
        card = cards.load(repo, call["subject"])
        if card is not None:
            call["card"] = card
    return out


def _subject(path: str) -> str:
    parts = path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] in ("wiki", "sources") else ""


def ranges(calls: list[dict]) -> list[list[int]]:
    return [[min(c["seqs"]), max(c["seqs"])] if c["seqs"] else [0, 0] for c in calls]
