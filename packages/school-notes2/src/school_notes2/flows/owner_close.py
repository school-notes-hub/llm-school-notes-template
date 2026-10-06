"""`status --close <learner> docs/review/<file>.md#R<n>... --note "<text>"` (fix-51, its own
module since fix-52): an item waiting for the owner becomes `fixed` by the owner's decision,
with a section `## Tulajdonosi lezárás (<id>)` and the note; the nightly reviewer does not
judge it again. Recorded like a reopen request (`reopen.json`, learner lock only); the next
fix run applies it in its worktree. A closure that finds nothing to close is logged as a
warning (`owner.close_skipped`), not as done work."""

from ..review import files
from ..state import safefs
from ..state.files import write_json
from ..wiki import frontmatter as fm
from . import reopen
from .reopen import ITEM, NOTE_MAX

SECTION = "## Tulajdonosi lezárás ({})"


def close(ctx, targets: list[str], note: str) -> str:
    """Validate owner items against origin/main and record one closing request."""
    try:
        with reopen.learner_lock(ctx):
            return _request(ctx, targets, note)
    except reopen.LockBusy as exc:
        return f"Nem rögzítettem semmit: {exc}"


def _request(ctx, targets, note):
    note = " ".join((note or "").split())
    problems = [] if note else ["--note is required: the owner's reason, one line"]
    if len(note) > NOTE_MAX:
        problems.append(f"--note is longer than {NOTE_MAX} characters")
    show = lambda rel: reopen.show(ctx, rel)
    for target in targets:
        item = ITEM.match(target)
        if not item:
            problems.append(f"{target}: use docs/review/<file>.md#R<n>")
            continue
        status, _ = reopen.item_at(show, item[1], item[2])
        if status != files.OWNER:
            problems.append(f"{target}: not waiting for the owner ({status or 'no such item'})")
    if problems:
        return "Nem rögzítettem semmit:\n" + "\n".join(problems)
    requests = reopen.load(ctx)
    value = {"id": reopen.new_id(requests, "close"), "at": reopen.now_iso(), "items": [], "figures": [],
             "close": sorted(set(targets)), "note": note}
    write_json(reopen.path(ctx), requests + [value])
    reopen.unpark(ctx, {"items": value["close"], "figures": []})
    ctx.log.event("owner.close_requested", target=value["id"], items=value["close"], note=note)
    return f"{value['id']}: a következő javító futás lezárja ({len(value['close'])} tétel, javítva)"


def apply(ctx, repo, value, run_id) -> set[str]:
    """In the fix run's worktree: closes the request's owner items; returns the written paths."""
    written = set()
    for rel, item_ids in sorted(reopen.by_file(value["close"]).items()):
        if _close_items(repo, rel, item_ids, value["id"], value["note"]):
            written.add(rel)
    if written:
        ctx.log.event("owner.closed", target=value["id"], run_id=run_id, items=value["close"])
    else:
        # Nothing waited for the owner any more (reopened meanwhile, or the file is gone).
        ctx.log.event("owner.close_skipped", "nothing_closed", level="warning", target=value["id"],
                      run_id=run_id, items=value["close"])
    return written


def _close_items(repo, rel, item_ids, request_id, note) -> bool:
    """Owner items become `fixed` by the owner's decision; the nightly reviewer does not
    judge such a closure again (`owner_closed`)."""
    if not safefs.is_file(repo, rel):
        return False
    page = fm.split(safefs.read_text(repo, rel))
    if SECTION.format(request_id) in page.body:
        return True                       # an interrupted preparation already wrote it
    items, details = dict(page.meta.get("items") or {}), dict(page.meta.get("item_details") or {})
    closed = [i for i in sorted(item_ids, key=files._num) if items.get(i) == files.OWNER]
    if not closed:
        return False
    for item_id in closed:
        items[item_id] = files.FIXED
        record = {k: v for k, v in details.get(item_id, {}).items() if k not in ("owner_question", "recheck")}
        details[item_id] = {**record, "owner_closed": {"request": request_id, "note": note}}
    lines = [f"* {i} – {files.WORDS[files.FIXED]} (tulajdonosi döntés): {note}" for i in closed]
    body = page.body.rstrip("\n") + f"\n\n{SECTION.format(request_id)}\n\n" + "\n".join(lines) + "\n"
    new = fm.set_keys(f"---\n{page.raw_meta}\n---\n{body}",
                      {"items": items, "item_details": details, "status": files.compute_status(items)})
    safefs.write_text(repo, rel, new)
    return True
