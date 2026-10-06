"""Fix-50/4: an orphan figure place – a figure or image marker on a wiki page with no pending
figure and no accepted figure behind it – keeps a picture from the learner, so it is a
machine item for the next fix run. The tool only states the fact (page, line, marker); the
writer decides what is right: embed an existing image through a commission and candidate, or
remove a stale marker. One item per place: a place that already has an item (any status) gets
no second one, so nothing comes back run after run."""

from ..figures import commissions, migration_gate, pending
from ..review import relations
from ..state import safefs

PREFIX = "orphan-figure-place:"
PROBLEM = ("Árva ábrahely: a(z) `{marker}` jelölőhöz nem tartozik függő ábra, és elfogadott ábra sincs "
           "a helyén, így az olvasó nem lát képet. Döntsd el, mi a helyes: ha az ábra kell, ágyazd be "
           "(megbízás és jelölt a meglévő vagy új képpel, a tool az ábraellenőr elfogadása után illeszti "
           "be); ha a jelölő elavult, távolítsd el.")


def places(repo) -> list[dict]:
    """Every orphan place, in page/line order: {id, page, line, quote}."""
    from .work_pending import missing_parts
    if migration_gate.blocked(repo):
        return []
    missing, _ = missing_parts(repo)
    queued = {e["commission"]["id"] for e in pending.load(repo)}
    found = commissions.markers(repo)
    out = []
    for fid in sorted(missing - queued):
        for page, position in found.get(fid, []):
            text = safefs.read_text(repo, page)
            line = text.count("\n", 0, position) + 1
            out.append({"id": fid, "page": page, "line": line, "quote": text.splitlines()[line - 1].strip()})
    return sorted(out, key=lambda p: (p["page"], p["line"], p["id"]))


def key(place) -> str:
    return f"{PREFIX}{place['page']}#{place['id']}"


def split(repo) -> tuple[list[dict], list[dict]]:
    """(places without an item yet, places that already have one)."""
    every = places(repo)
    if not every:
        return [], []
    known = {i.get("hit_id") for i in relations.inventory(repo)["items"].values()}
    return [p for p in every if key(p) not in known], [p for p in every if key(p) in known]


def new(repo) -> list[dict]:
    return split(repo)[0]


def record(ctx, task) -> None:
    """In the fix run's worktree, before the run lists its items."""
    from . import machine_findings
    found = new(ctx.notes_path)
    if found:
        ctx.log.event("figure.orphan_places", places=[key(p) for p in found])
    machine_findings.append(ctx, task, [
        {"file": p["page"], "line": p["line"], "quote": p["quote"], "problem": PROBLEM.format(marker=p["quote"]),
         "category": "szerkezeti", "severity": "hiba", "origin": "check", "chain": 0, "relates_to": None,
         "hit_id": key(p), "figure_id": p["id"]} for p in found])
