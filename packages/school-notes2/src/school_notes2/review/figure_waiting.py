"""Missing nightly figure verdicts are operational state, never writer assignments."""

from ..figures import insert
from ..state import safefs
from ..wiki import pages
from . import night_figures

PATH = "docs/review/night-figure-pending.json"


def active(repo, entries=None):
    records = safefs.read_json(repo, insert.VERDICTS, [])
    result = []
    for entry in entries if entries is not None else safefs.read_json(repo, PATH, []):
        spec = entry["spec"]
        if not safefs.is_file(repo, spec["page"]):
            continue
        text = safefs.read_text(repo, spec["page"])
        present = (any(l.image and pages.resolve(spec["page"], l.target) == spec["asset"]
                       for l in pages.links(text)) if spec.get("asset") else spec["source"] in text)
        if not present:
            continue
        try:
            if night_figures.valid(repo, spec, records):
                continue
        except (ValueError, OSError):
            pass
        result.append(entry)
    return sorted(result, key=lambda e: (e["spec"]["page"], e["spec"]["id"]))


def apply(repo, entries, checked=()):
    saved = safefs.read_json(repo, PATH, [])
    judged = {_identity(spec) for spec in checked}
    remaining = [e for e in saved if _identity(e["spec"]) not in judged]
    combined = {e["spec"]["id"]: e for e in remaining + entries}
    current = active(repo, combined.values())
    if current == saved:
        return []
    safefs.write_json(repo, PATH, current)
    return [PATH]


def _identity(spec):
    return (spec["page"], spec.get("asset") or (spec["anchor"], spec["source"]))
