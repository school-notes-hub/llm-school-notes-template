"""`sn check <t> <page…>` (plan 3.2): the page check, read-only (`fix=False`); exit 0/1."""

import json
from pathlib import Path

from ..wiki import check


def rel(repo: Path, page: str) -> str:
    path = Path(page)
    if path.is_absolute():
        return path.resolve().relative_to(repo.resolve()).as_posix()
    return path.as_posix()


def run(local, pages: list[str]) -> int:
    paths = sorted({rel(local.repo, p) for p in pages})
    items = check.check_files(local.repo, paths, fix=False)
    print(json.dumps(items, ensure_ascii=False, indent=1))
    errors = check.errors(items)
    print(f"hiba: {len(errors)}, figyelmeztetés: {len(items) - len(errors)}")
    return 1 if errors else 0
