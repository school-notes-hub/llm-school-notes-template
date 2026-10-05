"""Content-bound list verdicts; writer decisions never suppress a warning (8.5)."""

from pathlib import Path

from ..state import safefs

PATH = "docs/review/warning-verdicts.json"


def key(item: dict) -> tuple:
    return item["file"], item["line_hash"], item["occurrence"]


def load(repo: Path) -> list[dict]:
    return safefs.read_json(repo, PATH, [])


def pending(repo: Path, items: list[dict], review_ids=()) -> list[dict]:
    closed = {key(v) for v in load(repo)}
    return [i for i in items if i.get("id") not in review_ids and
            (i.get("kind") not in ("source_ref", "public_footnote") or key(i) not in closed)]


def record(repo: Path, assigned: list[dict], verdicts: list[dict]) -> list[dict]:
    """Validate complete accounting before writing; return errors for review-item creation.

    The reviewer integrations supply this list only after their independent pass.
    No writer reason is stored here. Repeating the same call is byte-identical.
    """
    by_id = {i["id"]: i for i in assigned}
    ids = [v["id"] for v in verdicts]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError("warning verdicts must cover exactly the assigned ids")
    stored = {key(v): v for v in load(repo)}
    errors = []
    for v in sorted(verdicts, key=lambda v: key(by_id[v["id"]])):
        if v.get("verdict") not in ("megengedett", "téves", "hiba") or not v.get("reason", "").strip():
            raise ValueError("warning verdict needs a verdict and nonempty reason")
        finding = by_id[v["id"]]
        if v["verdict"] == "hiba" and v.get("severity", "hiba") == "hiba":
            stored.pop(key(finding), None)
            errors.append({**finding, "reason": v["reason"], "covered_by": v.get("covered_by")})
        else:
            stored[key(finding)] = {k: finding[k] for k in ("file", "line_hash", "occurrence", "id")}
            stored[key(finding)].update(verdict=v["verdict"], reason=v["reason"])
    safefs.write_json(repo, PATH, [stored[k] for k in sorted(stored)])
    return errors
