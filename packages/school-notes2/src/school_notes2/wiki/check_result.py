"""result.json checks of plan 4.5 (part of `check`), on the merged result of a run."""

from pathlib import Path, PurePosixPath

from ..state import safefs
from ..review.relations import closure_problems
from .check import item

# A check's image must be a committed file: a source page or a wiki asset (4.5, 4.8).
IMAGE_ROOTS = ("sources/", "wiki/assets/")

RESULT = ".school-notes/result.json"


def check_result(repo: Path, result: dict, fetch: dict, open_items: set[tuple[str, str]],
                 closure_limit: int = 20, whole_run: bool = True, base_content=None,
                 generated=None) -> list[dict]:
    """`open_items`: {(file, item_id)} the run may close (fetch.json's list).

    `whole_run`: coverage of every page of the run (finish, merged results); False checks
    only the pages of fetch.json's `range` (the writer's MCP check of one range)."""
    out = []
    out += check_coverage(repo, result, fetch, whole_run)
    if fetch.get("mode") == "repair" and result.get("notes"):
        out.append(item(RESULT, None, "repair has no new source pages: notes must be empty"))
    new = {p["subject"] for p in fetch["packages"] if p.get("new_subject")}
    for s in result.get("new_subjects") or []:
        if s["subject"] not in new:
            out.append(item(RESULT, None, f"new_subjects: {s['subject']!r} is not new in this run"))
    out += check_closures(repo, result, open_items, closure_limit)
    out += check_figures(repo, result, fetch, base_content, generated)
    out += check_checks(repo, result, fetch)
    from ..repair import check as repair_check
    out += repair_check.coverage(result, fetch)
    return out


def check_closures(repo, result, open_items, closure_limit):
    out = []
    closures = result.get("review_closure") or []
    if len([c for c in closures if c["status"] != "open"]) > closure_limit:
        out.append(item(RESULT, None, f"review_closure: at most {closure_limit} items per run"))
    keys = [(c["file"], c["item_id"]) for c in closures]
    if len(keys) != len(set(keys)):
        out.append(item(RESULT, None, "review_closure: duplicate item keys"))
    for c in closures:
        out += [item(RESULT, None, f"review_closure: {m}") for m in closure_problems(repo, c)]
        if not safefs.is_file(repo, c["file"]):
            out.append(item(RESULT, None, f"review_closure: {c['file']} does not exist"))
        elif (c["file"], c["item_id"]) not in open_items:
            out.append(item(RESULT, None, f"review_closure: {c['file']} {c['item_id']} is not open"))
    return out


def check_figures(repo, result, fetch, base_content, generated):
    out = []
    from ..figures import commissions, pending, requests, licenses
    licenses.preflight(repo)
    requested = []
    try:
        requested = requests.collect(repo, result.get("figure_requests", []), fetch["pages"])
        for request in requested:
            if request["id"] in {f["id"] for f in result.get("figures", [])}:
                brief = commissions.read(repo, request["id"])
                licenses.candidate(repo, brief, commissions.candidate(repo, brief), request)
    except (ValueError, OSError) as exc:
        out.append(item(RESULT, None, str(exc)))
    inherited = fetch.get("pending_figures", [])
    out += check_pending(repo, inherited, generated)
    invalid = {e["commission"]["id"] for e in inherited
               if base_content is not None and not pending.valid_at(e["commission"], base_content)}
    assignments = [a for a in commissions.assignments(result, inherited) if a["id"] not in invalid]
    out += commissions.check(repo, assignments,
                             [d for d in result.get("notebook_drawings", []) if d["figure"] not in invalid],
                             generated=generated, requests=requested)
    return out


def check_pending(repo, inherited, generated):
    from ..figures import commissions, machine
    out = []
    for entry in inherited:
        fid = entry["commission"]["id"]
        path = f".school-notes/figures/{fid}/figure.json"
        if not safefs.is_file(repo, path):
            out.append(item(path, None, "pending figure needs a new candidate or explicit failed reason in this run"))
        else:
            try:
                candidate = commissions.candidate(repo, entry["commission"])
                if candidate["state"] == "candidate":
                    out += [item(path, None, message) for message in
                            machine.generation_errors(repo, entry["commission"], candidate, generated)]
                if candidate["state"] == "no-figure":
                    raise ValueError("pending figure needs a new candidate or explicit failed reason")
            except (ValueError, OSError) as exc:
                out.append(item(path, None, str(exc)))
    return out


def check_coverage(repo: Path, result: dict, fetch: dict, whole_run: bool = True) -> list[dict]:
    """The notes must cover every non-duplicate page (of the run, or of the range)."""
    wanted = {p["seq"] for p in fetch["pages"] if not p.get("duplicate_of")}
    if not whole_run:
        first, last = fetch["range"]["from"], fetch["range"]["to"]
        wanted = {seq for seq in wanted if first <= seq <= last}
    known = {p["seq"] for p in fetch["pages"]}
    covered: set[int] = set()
    out = []
    for note in result.get("notes") or []:
        covered |= set(note["pages"])
        if not safefs.is_file(repo, note["file"]):
            out.append(item(RESULT, None, f"notes: {note['file']} does not exist"))
        unknown = sorted(set(note["pages"]) - known)
        if unknown:
            out.append(item(note["file"], None, f"notes.pages: unknown page numbers {unknown}"))
    missing = sorted(wanted - covered)
    if missing and result.get("status") == "done":
        out.append(item(RESULT, None, f"notes: pages {missing} belong to no lesson-notes page"))
    return out


def check_checks(repo: Path, result: dict, fetch: dict) -> list[dict]:
    seqs = {p["seq"] for p in fetch["pages"]}
    out = []
    for n, c in enumerate(result.get("checks") or [], start=1):
        if not safefs.is_file(repo, c["page"]):
            out.append(item(RESULT, None, f"checks[{n}]: page {c['page']} does not exist"))
        image = c["image"]
        if isinstance(image, int) or str(image).isdigit():
            if int(image) not in seqs:
                out.append(item(RESULT, None, f"checks[{n}]: page number {image} is not in this run"))
        elif not committed_image(repo, str(image)):
            out.append(item(RESULT, None, f"checks[{n}]: image {image!r} must be an existing file "
                                          f"under {' or '.join(IMAGE_ROOTS)}"))
    return out


def committed_image(repo: Path, rel: str) -> bool:
    """A repo-relative file under sources/ or wiki/assets/, without `..`."""
    pure = PurePosixPath(rel)
    return (not pure.is_absolute() and ".." not in pure.parts and rel.startswith(IMAGE_ROOTS)
            and safefs.is_file(repo, rel))
