"""Mechanical content-protection checks for a repair; semantic coverage stays with review."""

from ..wiki.check import item


def problems(ctx, task, paths):
    """Assignment is a focus, not an author-content or page permission boundary."""
    return []


def coverage(result, fetch):
    targets = fetch.get("repair_targets", [])
    if not targets or targets[0]["kind"] != "lesson-notes" or result.get("status") != "done":
        return []
    ledger = result.get("coverage", [])
    if not ledger or not result.get("checks"):
        return [item(".school-notes/result.json", None,
                     "repair: shortening a lesson log requires item coverage and checks")]
    return []
