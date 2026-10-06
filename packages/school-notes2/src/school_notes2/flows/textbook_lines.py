"""Fix-52: a 🔖 textbook line without any lesson or page number tells the learner nothing
(a placeholder such as "the lesson is not identified yet" on the public site). The check
warns on the pages a run changes; this scan makes each such page a machine item of the next
fix run, so the lines already there come out too. The tool only states the fact (page, line);
the writer gives the identified lesson and page or leaves the line out. One item per page:
a page that already has an item (any status) gets no second one, so nothing comes back run
after run."""

from ..review import relations
from ..state import safefs
from ..wiki.check import textbook_lines
from ..wiki.pages import wiki_pages

PREFIX = "textbook-line:"
PROBLEM = ("Tankönyvi sor lecke- és oldalszám nélkül: „{quote}”. A `🔖 Tankönyv:` sor csak azonosított "
           "leckével és oldalszámmal áll. Ha a lecke azonosítható, add meg a leckét és az oldalt; ha nem, "
           "töröld a sort (a hiány a bizonyítékrekordba, és ha a tanuló segíthet, a nyitott kérdések közé "
           "kerül). Az oldal minden ilyen sorára vonatkozik.")


def places(repo) -> list[dict]:
    """Every page with such a line, its first one: {page, line, quote}, in page order."""
    out = []
    for page in sorted(wiki_pages(repo)):
        text = safefs.read_text(repo, page)
        lines = textbook_lines(page, text)
        if lines:
            out.append({"page": page, "line": lines[0], "quote": text.split("\n")[lines[0] - 1].strip()})
    return out


def key(place) -> str:
    return PREFIX + place["page"]


def new(repo) -> list[dict]:
    found = places(repo)
    if not found:
        return []
    known = {i.get("hit_id") for i in relations.inventory(repo)["items"].values()}
    return [p for p in found if key(p) not in known]


def record(ctx, task) -> None:
    """In the fix run's worktree, before the run lists its items."""
    from . import machine_findings
    found = new(ctx.notes_path)
    if found:
        ctx.log.event("check.textbook_lines", pages=[p["page"] for p in found])
    machine_findings.append(ctx, task, [
        {"file": p["page"], "line": p["line"], "quote": p["quote"], "problem": PROBLEM.format(quote=p["quote"]),
         "category": "szerkezeti", "severity": "hiba", "origin": "check", "chain": 0, "relates_to": None,
         "hit_id": key(p)} for p in found])
