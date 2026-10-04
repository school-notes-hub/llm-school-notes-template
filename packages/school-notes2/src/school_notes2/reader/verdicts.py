"""Reader and figure verdicts, checked again on the final tree without an LLM."""

from ..figures import insert
from ..state import safefs
from .units import page_key

PATH = insert.VERDICTS


def record(repo, pages, keys, model, at):
    records = safefs.read_json(repo, PATH, [])
    updated = {p["file"] for p in pages}
    records = [r for r in records if r.get("role") != "reader" or r["file"] not in updated]
    records += [{"role": "reader", "file": p["file"], "key": keys[p["file"]],
                 "verdict": p["verdict"], "model": model, "at": at} for p in pages]
    safefs.write_json(repo, PATH, sorted(records, key=lambda r: (r["file"], r["key"], r["role"])))


def valid(repo, page):
    if not safefs.is_file(repo, page):
        return None
    key = page_key(repo, page)
    return next((r for r in safefs.read_json(repo, PATH, [])
                 if r.get("role") == "reader" and r["file"] == page and r["key"] == key), None)


def invalidate(repo):
    records = safefs.read_json(repo, PATH, [])
    removed = [r for r in records if r.get("role") == "figure-review" and insert.removed(repo, r)]
    stale = insert.invalidated(repo)
    for r in records:
        if r.get("role") == "reader" and (not safefs.is_file(repo, r["file"]) or
                                         page_key(repo, r["file"]) != r["key"]):
            stale.append(r)
    if stale or removed:
        safefs.write_json(repo, PATH, [r for r in records if r not in stale and r not in removed])
    return sorted(stale, key=lambda r: (r["file"], r["key"], r["role"]))
