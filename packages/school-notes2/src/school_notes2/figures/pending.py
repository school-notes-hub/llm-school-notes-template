"""Durable pending commissions; count distinct runs, never resumes (plan 5.4)."""

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
                or entry["owner_required"] != (entry["runs"] >= 3)
                or entry["run_ids"] != sorted(entry["run_ids"])):
            raise ValueError("invalid pending figure record")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate pending commission")
    return sorted(entries, key=lambda e: e["commission"]["id"])


def record(repo: Path, brief: dict, run_id: str, defects: list[dict]) -> dict:
    validate("figure-commission", brief)
    if not run_id:
        raise ValueError("pending figures need a run id")
    entries = {e["commission"]["id"]: e for e in load(repo)}
    previous = entries.get(brief["id"], {})
    runs = previous.get("run_ids", [])
    if run_id not in runs and len(runs) < 3:
        runs = sorted([*runs, run_id])
    entry = {"commission": brief, "status": "pending", "runs": len(runs),
             "run_ids": runs, "defects": defects, "owner_required": len(runs) >= 3}
    validate("figure-pending", [entry])
    entries[brief["id"]] = entry
    safefs.write_json(repo, PATH, [entries[k] for k in sorted(entries)])
    return entry


def clear(repo: Path, figure_id: str) -> None:
    entries = load(repo)
    if any(e["commission"]["id"] == figure_id for e in entries):
        safefs.write_json(repo, PATH, [e for e in entries if e["commission"]["id"] != figure_id])


def eligible(repo: Path, pages: set[str]) -> list[dict]:
    return [e for e in load(repo) if e["runs"] < 3 and e["commission"]["page"] in pages]


def restore(repo: Path, pages: set[str]) -> list[dict]:
    entries = eligible(repo, pages)
    for entry in entries:
        brief = entry["commission"]
        safefs.write_json(repo, f".school-notes/figures/{brief['id']}.json", brief)
    return entries


def for_subjects(repo: Path, subjects: set[str]) -> list[dict]:
    """Restore only eligible commissions for subjects already assigned to this run."""
    entries = [e for e in load(repo) if e["runs"] < 3 and
               e["commission"]["page"].split("/")[1] in subjects]
    for entry in entries:
        brief = entry["commission"]
        safefs.write_json(repo, f".school-notes/figures/{brief['id']}.json", brief)
    return entries
