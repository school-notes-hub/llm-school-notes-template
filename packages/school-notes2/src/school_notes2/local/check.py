"""`sn check <t> <page…>` (plan 3.2): the page check, read-only (`fix=False`); exit 0/1."""

import json
from pathlib import Path

from ..state import safefs
from ..wiki import check


def rel(repo: Path, page: str) -> str:
    path = Path(page)
    if path.is_absolute():
        return path.resolve().relative_to(repo.resolve()).as_posix()
    return path.as_posix()


def wrong(repo: Path, path: str) -> str | None:
    """Why a requested path cannot be checked (the library would skip it silently)."""
    if not (path.startswith("wiki/") and path.endswith(".md")) or path.startswith("wiki/assets/"):
        return "nem wiki-lap (wiki/…/*.md, wiki/assets/ nélkül)"
    if not safefs.is_file(repo, path):
        return "nincs ilyen lap"
    return None


def run(local, pages: list[str]) -> int:
    try:
        paths = sorted({rel(local.repo, p) for p in pages})
    except ValueError:
        print("hiba: a lap nem a tanuló munkapéldányában van")
        return 1
    bad = [(p, why) for p in paths if (why := wrong(local.repo, p))]
    for path, why in bad:
        print(f"hiba: {path}: {why}")
    if bad:
        return 1
    items = check.check_files(local.repo, paths, fix=False)
    print(json.dumps(items, ensure_ascii=False, indent=1))
    errors = check.errors(items)
    print(f"hiba: {len(errors)}, figyelmeztetés: {len(items) - len(errors)}")
    return 1 if errors else 0
