"""Private figure requests, identified by source bytes and a unique hidden marker."""

from ..state import safefs
from ..schemas import validate

PATH = "docs/figure-requests.json"
FIELDS = ("id", "page", "source", "crop", "purpose", "origin")


def load(repo):
    value = safefs.read_json(repo, PATH, [])
    validate("figure-requests", value)
    if len({r["id"] for r in value}) != len(value):
        raise ValueError("duplicate figure request ids")
    return sorted(({k: r[k] for k in (*FIELDS, "content_sha256", "original_sha256")} for r in value),
                  key=lambda r: (r["source"], r["page"], r["id"]))
