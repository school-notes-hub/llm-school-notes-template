"""Rebase conflicts (plan 6.7): generated files are resolved, content stays for the owner."""

import fnmatch
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..state import safefs
from .run import Git

FULLY_GENERATED = ("publication/public.json",)
VERDICT_RECORDS = ("docs/review/verdicts.json",)
WITH_GENERATED_BLOCKS = ("wiki/index.md", "wiki/*/index.md", "docs/review/index.md")
REVIEW_REPORTS = ("docs/review/*-review.md", "docs/review/*-review-*.md", "docs/review/*-run.md")
ORIGIN_LABEL = "origin/main (kívülről)"


@dataclass
class Outcome:
    resolved: list[str]
    content: list[str]   # left with conflict markers for the interactive session


def conflicted(wt: Git) -> list[str]:
    out = wt.out("diff", "--no-ext-diff", "--name-only", "--diff-filter=U", "-z")
    return sorted(p for p in out.split("\0") if p)


def resolve(wt: Git, run_id: str, empty_blocks) -> Outcome:
    """Resolve classes 1–2 of 6.7; rewrite class-3 text files with the plan's labels.

    `empty_blocks(text) -> text` empties every generated block (the wiki module's markers)."""
    resolved, content = [], []
    for path in conflicted(wt):
        if path in FULLY_GENERATED:
            wt.run("checkout", "--theirs", "--", path)
            wt.run("add", "--", path)
            resolved.append(path)
        elif path in VERDICT_RECORDS and _merge_verdicts(wt, path):
            wt.run("add", "--", path)
            resolved.append(path)
        elif _matches(path, REVIEW_REPORTS) and _merge_review(wt, path):
            wt.run("add", "--", path)
            resolved.append(path)
        elif _matches(path, WITH_GENERATED_BLOCKS) and _merge_blocks(wt, path, empty_blocks):
            wt.run("add", "--", path)
            resolved.append(path)
        else:
            _relabel(wt, path, run_id)
            content.append(path)
    return Outcome(resolved, content)


def merge_verdict_records(origin: list, own: list) -> list:
    """Union of both sides' verdict records; per (role, file, id, key) the later `at` wins."""
    merged = {}
    for record in [*origin, *own]:
        ident = (record.get("role"), record.get("file"), record.get("id"), record.get("key"))
        if ident not in merged or str(record.get("at", "")) >= str(merged[ident].get("at", "")):
            merged[ident] = record
    return sorted(merged.values(), key=lambda r: (r["file"], r.get("key", ""), r["role"]))


def _merge_verdicts(wt: Git, path: str) -> bool:
    """`docs/review/verdicts.json` is tool output: both sides' verdicts are kept (a night's
    verdicts on origin and this run's reader verdicts never contradict for the same key)."""
    versions = _stages(wt, path)
    if versions is None:
        return False
    try:
        origin, own = (json.loads(v.decode("utf-8") or "[]") for v in versions[1:])
    except ValueError:
        return False
    if not isinstance(origin, list) or not isinstance(own, list):
        return False
    safefs.write_json(wt.work_tree, path, merge_verdict_records(origin, own))
    return True


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) and path.count("/") == p.count("/") for p in patterns)


def _stages(wt: Git, path: str) -> list[bytes] | None:
    """Base, origin and own versions (:1:, :2:, :3:); None when one side deleted the file."""
    out = []
    for stage in (1, 2, 3):
        proc = wt.run("show", f":{stage}:{path}", check=False)
        if proc.returncode != 0:
            return None
        out.append(proc.stdout)
    return out


def _merge_file(versions: list[bytes], labels: tuple[str, str, str]) -> tuple[int, bytes]:
    """`git merge-file -p` on three temp files; returns (conflict count, merged bytes)."""
    with tempfile.TemporaryDirectory() as tmp:
        names = []
        for name, data in zip(("base", "origin", "own"), versions):
            path = Path(tmp) / name
            path.write_bytes(data)
            names.append(str(path))
        proc = subprocess.run(
            ["git", "merge-file", "-p", "-L", labels[1], "-L", labels[0], "-L", labels[2],
             names[1], names[0], names[2]],
            capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                                      "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
        if proc.returncode < 0 or proc.returncode > 127:
            raise RuntimeError(f"git merge-file failed: {proc.stderr[:200]!r}")
        return proc.returncode, proc.stdout


def _merge_blocks(wt: Git, path: str, empty_blocks) -> bool:
    """Merge with generated blocks emptied; clean means the clash was only generated text."""
    versions = _stages(wt, path)
    if versions is None:
        return False
    emptied = [empty_blocks(v.decode("utf-8")).encode("utf-8") for v in versions]
    conflicts, merged = _merge_file(emptied, ("base", ORIGIN_LABEL, "own"))
    if conflicts:
        return False
    safefs.write_bytes(wt.work_tree, path, merged)
    return True


def _relabel(wt: Git, path: str, run_id: str) -> None:
    """Rewrite a text conflict with the owner-facing labels; binary and delete/modify
    conflicts stay as Git left them."""
    versions = _stages(wt, path)
    if versions is None or any(b"\0" in v for v in versions):
        return
    _, merged = _merge_file(versions, ("base", ORIGIN_LABEL, f"futás {run_id}"))
    safefs.write_bytes(wt.work_tree, path, merged)


def has_markers(text: str) -> bool:
    lines = text.split("\n")
    return any(ln.startswith("<<<<<<< ") for ln in lines) and any(
        ln.startswith(">>>>>>> ") for ln in lines)


def _merge_review(wt: Git, path: str) -> bool:
    from ..review.merge import merge
    versions = _stages(wt, path)
    merged = merge(versions) if versions is not None else None
    if merged is None:
        return False
    safefs.write_bytes(wt.work_tree, path, merged)
    return True
