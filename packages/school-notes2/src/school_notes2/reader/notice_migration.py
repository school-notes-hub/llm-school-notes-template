"""One replay-safe refresh of all notices, retaining proof of earlier reader reviews."""

import json

from ..state import safefs
from ..wiki.pages import wiki_pages
from . import notices, verdicts

PATH = "docs/review/notice-policy.json"
POLICY = "real-gaps-2"


def refresh(repo, *, git=None, write=None):
    if safefs.read_json(repo, PATH, {}).get("policy") == POLICY:
        return []
    write = write or (lambda path, text: safefs.write_text(repo, path, text))
    records = safefs.read_json(repo, verdicts.PATH, [])
    known = {r["file"] for r in records if r.get("role") in ("reader", "reader-history")}
    # Old releases deleted stale verdicts. Recover their existence, never their validity.
    if git is not None:
        commits = git.out("log", "--format=%H", "HEAD", "--", verdicts.PATH).splitlines()
        for commit in commits:
            old = git.run("show", f"{commit}:{verdicts.PATH}", check=False)
            if old.returncode:
                continue
            for record in json.loads(old.stdout):
                if record.get("role") in ("reader", "reader-history") and record["file"] not in known:
                    records.append({**record, "role": "reader-history"})
                    known.add(record["file"])
    records = [r for r in records if safefs.is_file(repo, r["file"])]
    records.sort(key=lambda r: (r["file"], r.get("key", ""), r["role"]))
    written = []
    if records != safefs.read_json(repo, verdicts.PATH, []):
        write(verdicts.PATH, json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        written.append(verdicts.PATH)
    written += notices.refresh(repo, sorted(wiki_pages(repo)), write=write, remove_only=True)
    # Last write: an interruption repeats the idempotent refresh, including untouched pages.
    write(PATH, json.dumps({"policy": POLICY}, ensure_ascii=False, indent=2) + "\n")
    return written + [PATH]
