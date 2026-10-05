"""Reader and figure verdicts, checked again on the final tree without an LLM."""

from ..figures import insert
from ..state import safefs
from .units import page_key

PATH = insert.VERDICTS


def record(repo, pages, keys, model, at):
    records = safefs.read_json(repo, PATH, [])
    updated = {p["file"] for p in pages}
    records = [r for r in records if r.get("role") not in ("reader", "reader-history") or r["file"] not in updated]
    records += [{"role": "reader", "file": p["file"], "key": keys[p["file"]],
                 "verdict": p["verdict"], "model": model, "at": at} for p in pages]
    safefs.write_json(repo, PATH, sorted(records, key=lambda r: (r["file"], r.get("key", ""), r["role"])))


def rekeyed(repo):
    """Mechanical re-keying after a key-formula change, without reading anything: a record
    still matching an older formula of the same text gets the current key (R2)."""
    from .units import banner_key
    records = safefs.read_json(repo, PATH, [])
    updated = []
    for record in records:
        if record.get("role") == "reader" and safefs.is_file(repo, record["file"]):
            key = page_key(repo, record["file"])
            if key != record.get("key", "") and record.get("key", "") in (
                    page_key(repo, record["file"], legacy_notices=True), banner_key(repo, record["file"])):
                record = {**record, "key": key}
        updated.append(record)
    return sorted(updated, key=lambda r: (r["file"], r.get("key", ""), r["role"])) if updated != records else None


def valid(repo, page):
    if not safefs.is_file(repo, page):
        return None
    key = page_key(repo, page)
    return next((r for r in safefs.read_json(repo, PATH, [])
                 if r.get("role") == "reader" and r["file"] == page and r.get("key", "") == key), None)


def ever_reviewed(repo, page):
    return any(r.get("role") in ("reader", "reader-history") and r["file"] == page
               for r in safefs.read_json(repo, PATH, []))


def invalidate(repo):
    records = safefs.read_json(repo, PATH, [])
    removed = [r for r in records if (r.get("role") == "figure-review" and insert.removed(repo, r))
               or (r.get("role") in ("reader", "reader-history") and not safefs.is_file(repo, r["file"]))]
    stale = insert.invalidated(repo)
    for r in records:
        if r.get("role") == "reader" and (not safefs.is_file(repo, r["file"]) or
                                         page_key(repo, r["file"]) != r.get("key", "")):
            stale.append(r)
    if stale or removed:
        safefs.write_json(repo, PATH, [({**r, "role": "reader-history"} if r in stale else r)
                                      for r in records if r not in removed and
                                      (r not in stale or r.get("role") == "reader")])
    return sorted(stale, key=lambda r: (r["file"], r.get("key", ""), r["role"]))
