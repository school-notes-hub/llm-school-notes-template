"""`sn done <t>` (plan 3.2): is the learner's notes content finished? Read-only; exit 0/1.

Counted: pending and invalidated figures, inserted figures gone from their page (their
verdict is kept), orphan figure places, textbook placeholder lines,
figure places without an accepted figure, broken image links, and every page-check error on
every wiki page (`check_files(..., fix=False)`: unlike `check_text` it also checks links).
With a git handle (`sn done`, `sn publish`) the writer guard runs too: a change since HEAD no
writer may make (`guard.py`). The worktree's cleanliness is not looked at here (`sn publish`
checks it)."""

from pathlib import Path

from ..figures import insert, pending
from ..state import safefs
from ..wiki import check
from ..wiki.pages import wiki_pages
from . import guard, places as facts


def problems(repo: Path, git=None) -> list[tuple[str, list[str]]]:
    """(name, items) in a fixed order; every item list sorted by content."""
    places, links = facts.missing_parts(repo)
    errors = check.errors(check.check_files(repo, sorted(wiki_pages(repo)), fix=False))
    return [
        ("függő ábra", sorted(e["commission"]["id"] for e in pending.load(repo))),
        ("érvénytelenedett ábraítélet", sorted(f"{r['file']}#{r['id']}" for r in insert.invalidated(repo))),
        ("beillesztett ábra eltűnt a lapról", sorted(
            f"{r['file']}#{r['id']}" for r in safefs.read_json(repo, insert.VERDICTS, [])
            if r.get("role") == "figure-review" and not r.get("night_spec") and insert.removed(repo, r))),
        ("árva ábrahely", sorted(f"{p['page']}:{p['line']} {p['id']}" for p in facts.orphan_places(repo))),
        ("tankönyvi helyőrző sor", sorted(f"{p['page']}:{p['line']}" for p in facts.textbook_lines(repo))),
        ("ábrahely elfogadott ábra nélkül", sorted(places)),
        ("törött képlink", sorted(links)),
        ("lapellenőrzési hiba", sorted(f"{e['file']}:{e.get('line') or ''} {e['message']}" for e in errors)),
    ] + ([("író-őr: tiltott módosítás", guard.violations(repo, git))] if git is not None else [])


def report(repo: Path, out=print, git=None) -> int:
    found = problems(repo, git)
    for name, items in found:
        out(f"{name}: {len(items)}")
        for item in items[:20]:
            out(f"  {item}")
        if len(items) > 20:
            out(f"  … és még {len(items) - 20}")
    total = sum(len(items) for _, items in found)
    out(f"összesen: {total}")
    return 1 if total else 0


def run(local) -> int:
    code = report(local.repo, git=local.git())
    local.record("done", "ok" if code == 0 else "open")
    return code
