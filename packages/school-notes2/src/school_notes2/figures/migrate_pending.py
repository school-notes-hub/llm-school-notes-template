"""One-time pending reset after installing 2.4.0, before the next learner run.

python -m school_notes2.figures.migrate_pending LEARNER [--config CONFIG] [--dry-run | --push]
Dry-run is read-only; real execution commits and optionally pushes with the tool Git.
"""

import argparse
import hashlib
import json
from pathlib import Path

from ..schemas import validate
from ..state import safefs
from ..wiki.pages import wiki_pages
from . import migrate_headers, pending
from .migration_gate import MARK

RECEIPT = "figure-pending-migration-22.json"
VERSION = "generated-headers-22"
POISON = ("nem készült új jelölt", "missing figure.json")


def historical(repo, ids):
    found = {}
    for commit in repo.out("log", "--format=%H", "--", pending.PATH).splitlines():
        raw = repo.run("show", f"{commit}:{pending.PATH}", check=False)
        if raw.returncode:
            continue
        try:
            entries = json.loads(raw.stdout)
        except (ValueError, UnicodeError):
            continue
        for entry in entries:
            fid, defects = entry.get("commission", {}).get("id"), entry.get("defects", [])
            if fid in ids and fid not in found and defects and not poisoned(defects):
                found[fid] = defects
        if set(found) == ids:
            break
    return found


def poisoned(defects):
    return any(word in json.dumps(defects, ensure_ascii=False) for word in POISON)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def current(repo, path):
    return digest(safefs.read_text(repo, path)) if safefs.is_file(repo, path) else None


def plan(path, repo):
    entries, texts, skipped = pending.load(path), {}, []
    ids = {e["commission"]["id"] for e in entries if safefs.is_file(path, e["commission"]["page"])}
    restored = historical(repo, ids)
    for entry in entries:
        brief = entry["commission"]
        if not safefs.is_file(path, brief["page"]):
            skipped.append({"id": brief["id"], "page": brief["page"]})
            continue
        entry.update(runs=0, run_ids=[], owner_required=False)
        entry.pop("review_pending", None)
        entry["defects"] = restored.get(brief["id"], [] if poisoned(entry["defects"]) else entry["defects"])
        if brief["kind"] in ("banner", "infographic"):
            page = brief["page"]
            text = texts.get(page, safefs.read_text(path, page))
            texts[page] = text.replace(f"<!-- figure: {brief['id']} -->", f"<!-- image: {brief['id']} -->")
    entries = migrate_headers.replacements(path, entries, texts)
    validate("figure-pending", entries)
    for entry in entries:
        validate("figure-commission", entry["commission"])
    texts[pending.PATH] = encoded(entries)
    return texts, {"restored": sorted(restored), "unrestored": sorted(ids - restored.keys()),
                   "commissions": sorted(e["commission"]["id"] for e in entries), "skipped": skipped}


def receipt(before, texts, summary):
    return {**summary, "files": {p: {"before": before.get(p), "after": digest(texts[p])}
                                 for p in sorted(texts)}}


def recovery(state_dir):
    return (f"inspect and preserve the new changes, then remove {state_dir.resolve() / RECEIPT} "
            f"and {state_dir.resolve() / 'migration-operation-24.json'}; "
            "rerun --dry-run, then rerun the migration command")


def check_current(path, saved, state_dir):
    for name, hashes in saved["files"].items():
        if current(path, name) not in (hashes["before"], hashes["after"]):
            raise ValueError(f"migration input changed: {name}; {recovery(state_dir)}")


def apply(path, texts, saved, state_dir):
    # All input hashes are checked before any write, and again at each replacement.
    check_current(path, saved, state_dir)
    for name, hashes in saved["files"].items():
        actual = current(path, name)
        if actual == hashes["after"]:
            continue
        if actual != hashes["before"] or digest(texts[name]) != hashes["after"]:
            raise ValueError(f"migration input changed: {name}; {recovery(state_dir)}")
        safefs.write_text(path, name, texts[name])
    # This repository flag, not the host receipt, prevents another counter reset.
    safefs.write_json(path, MARK, {"version": VERSION})


def migrate(path, *, state_dir, repo, dry_run=False):
    if safefs.read_json(path, MARK, {}).get("version") == VERSION:
        return {"status": "already-migrated"}
    if state_dir.resolve().is_relative_to(path.resolve()):
        raise ValueError("migration receipt must be outside the learner repository")
    saved = safefs.read_json(state_dir, RECEIPT)
    if saved is not None:
        check_current(path, saved, state_dir)
    before = {p: current(path, p) for p in sorted([*wiki_pages(path), pending.PATH])}
    texts, summary = plan(path, repo)
    saved = saved or receipt(before, texts, summary)
    output = {k: saved.get(k, []) for k in ("restored", "unrestored", "commissions", "skipped")}
    output["changes"] = sorted(p for p in saved["files"] if current(path, p) != saved["files"][p]["after"])
    output["changes"].append(MARK)
    if not dry_run:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        safefs.write_json(state_dir, RECEIPT, saved)
        apply(path, texts, saved, state_dir)
    return output


def main(argv=None):
    from .. import config
    from ..flows import context
    from . import migrate_operation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("learner")
    parser.add_argument("--config", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--push", action="store_true")
    args = parser.parse_args(argv)
    ctx = context.make(config.load(args.config), args.learner)
    return migrate_operation.run(ctx, dry_run=args.dry_run, push=args.push)


if __name__ == "__main__":
    raise SystemExit(main())
