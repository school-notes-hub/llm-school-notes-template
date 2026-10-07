"""The durable pending-figure queue `docs/figure-pending.json`: `sn done` counts it, an
insertion takes its figure off. A missing file is an empty queue."""

from pathlib import Path

from ..schemas import validate
from ..state import safefs

PATH = "docs/figure-pending.json"


def load(repo: Path) -> list[dict]:
    entries = safefs.read_json(repo, PATH, [])
    validate("figure-pending", entries)
    ids = []
    for entry in entries:
        validate("figure-commission", entry["commission"])
        ids.append(entry["commission"]["id"])
        if (entry.get("status") != "pending" or not isinstance(entry.get("run_ids"), list)
                or entry.get("runs") != len(set(entry["run_ids"]))
                or (entry["runs"] >= 3 and not entry["owner_required"] and not entry.get("review_pending"))
                or entry["run_ids"] != sorted(entry["run_ids"])):
            raise ValueError("invalid pending figure record")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate pending commission")
    return sorted(entries, key=lambda e: e["commission"]["id"])


def clear(repo: Path, figure_id: str) -> None:
    entries = load(repo)
    if any(e["commission"]["id"] == figure_id for e in entries):
        safefs.write_json(repo, PATH, [e for e in entries if e["commission"]["id"] != figure_id])
