"""Durable pending commissions; count distinct runs, never resumes (plan 5.4)."""

from pathlib import Path

import yaml

from ..schemas import validate
from ..log import Log
from ..state import safefs
from . import migration_gate

PATH = migration_gate.PATH


def assignment_order(entry):
    brief = entry["commission"]
    return bool(brief.get("replaces")), brief["page"], brief.get("anchor", ""), brief["id"]


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


def record(repo: Path, brief: dict, run_id: str, defects: list[dict], *, attempted: bool | None = None,
           owner_required=False, review_pending=False, log=None) -> dict:
    if migration_gate.blocked(repo):
        previous = next((e for e in load(repo) if e["commission"]["id"] == brief["id"]), None)
        if previous is None:
            (log or Log(None)).event("figure.migration_dropped", target=brief["id"])
        return previous or {"commission": brief, "runs": 0, "run_ids": [], "owner_required": False}
    from .commissions import check_identity
    validate("figure-commission", brief)
    check_identity(repo, brief)
    if not run_id:
        raise ValueError("pending figures need a run id")
    if attempted is None:
        attempted = has_attempt(repo, brief)
    entries = {e["commission"]["id"]: e for e in load(repo)}
    previous = entries.get(brief["id"], {})
    runs = previous.get("run_ids", [])
    if attempted and run_id not in runs and len(runs) < 3:
        runs = sorted([*runs, run_id])
    entry = {"commission": brief, "status": "pending", "runs": len(runs),
             "run_ids": runs, "defects": defects,
             "owner_required": owner_required or previous.get("owner_required", False) or (len(runs) >= 3 and not review_pending)}
    if review_pending:
        entry["review_pending"] = True
    validate("figure-pending", [entry])
    entries[brief["id"]] = entry
    if not safefs.is_file(repo, migration_gate.MARK):
        # An empty/new queue has no legacy counters. Header migration remains separate.
        safefs.write_json(repo, migration_gate.MARK, {"pending_format": "attempted-runs"})
    safefs.write_json(repo, PATH, [entries[k] for k in sorted(entries)])
    return entry


def clear(repo: Path, figure_id: str) -> None:
    if migration_gate.blocked(repo):
        return
    entries = load(repo)
    if any(e["commission"]["id"] == figure_id for e in entries):
        safefs.write_json(repo, PATH, [e for e in entries if e["commission"]["id"] != figure_id])


def eligible(repo: Path, pages: set[str]) -> list[dict]:
    if migration_gate.blocked(repo):
        return []
    return [e for e in load(repo) if not e["owner_required"] and e["commission"]["page"] in pages]


def restore(repo: Path, pages: set[str]) -> list[dict]:
    entries = eligible(repo, pages)
    for entry in entries:
        brief = entry["commission"]
        safefs.write_json(repo, f".school-notes/figures/{brief['id']}.json", brief)
    return entries


def for_subjects(repo: Path, subjects: set[str], *, allowed=None) -> list[dict]:
    """Restore only eligible commissions for subjects already assigned to this run."""
    if migration_gate.blocked(repo):
        return []
    entries = [e for e in load(repo) if not e["owner_required"] and
               e["commission"]["page"].split("/")[1] in subjects
               and (allowed is None or e["commission"]["id"] in allowed)]
    entries.sort(key=assignment_order)
    for entry in entries:
        brief = entry["commission"]
        safefs.write_json(repo, f".school-notes/figures/{brief['id']}.json", brief)
    return entries


def valid_at(brief: dict, read) -> bool:
    """Was the inherited commission usable before this writer started?

    Candidates are run-local; only the committed embedding and dependencies count.
    A pre-existing defect belongs to P2's failed/pending path, not to the writer.
    """
    from . import commissions, context
    from .render import png
    from ..wiki.pages import CODE_FENCE, INLINE_CODE
    try:
        raw = read(brief["page"])
        if raw is None:
            return False
        text = context.with_markers(raw.decode("utf-8"))
        visible = INLINE_CODE.sub("", CODE_FENCE.sub("", text))
        matches = [m for m in commissions.MARKER.finditer(visible) if m[1] == brief["id"]]
        if len(matches) != 1:
            return False
        marker = f"<!-- figure: {brief['id']} -->"
        if marker not in visible.splitlines():
            return False
        if brief["kind"] != "banner" and marker not in context.section(text, brief["anchor"])[0]:
            return False
        if brief.get("replaces") and read(brief["replaces"]) is None:
            return False
        if source := brief.get("source_image"):
            data = read(source["path"])
            if data is None:
                return False
            png(data, crop=source["crop"])
    except (ValueError, OSError, yaml.YAMLError):
        return False
    return True


def generated(repo: Path, brief: dict) -> bool:
    return generated_at(brief, lambda rel: safefs.read_text(repo, rel) if safefs.is_file(repo, rel) else None)


def generated_at(brief: dict, read) -> bool:
    """A generated (paid) image: a banner or infographic, or a page with its image marker.
    `read(rel)` gives a page's text or None (the worktree, or a commit)."""
    if brief["kind"] in ("banner", "infographic"):
        return True
    return f"<!-- image: {brief['id']} -->" in (read(brief["page"]) or "")


def has_attempt(repo: Path, brief: dict, *, paid=False) -> bool:
    from .commissions import candidate
    if paid:
        return True
    if not safefs.is_file(repo, f".school-notes/figures/{brief['id']}/figure.json"):
        return False
    try:
        state = candidate(repo, brief)["state"]
        return state == "candidate" or (state == "failed" and not generated(repo, brief))
    except (ValueError, OSError):
        return False
