"""`school-notes status --reopen <learner> <target>...` (fix-49): the owner reopens a review
item and/or a pending figure that waits for him, once the obstacle is gone.

Targets are `docs/review/<file>.md#R<n>` (an item in `owner` state) and `figure:<id>` (a drawn
pending figure with `owner_required`). The command only records the request on the VM (it is
logged); the next fix run applies it in its own worktree, before it lists its work, and
commits it with the run: the item is `open` again with its repair counter at zero (a line
`## Újranyitva (<id>)` in the review file says so), the figure's run counter is zero. A
request whose run finished is done; one whose run was discarded is applied by the next run.
Generated images are reopened only with `--paid`, the owner's explicit approval: the run that
applies the request opens one new frame of paid attempts for the image in the image ledger (the
old attempts stay there, the monthly budget still applies), with a line in the review file.

`status --close <learner> docs/review/<file>.md#R<n>... --note "<text>"` (fix-51) is the pair:
an item waiting for the owner becomes `fixed` by the owner's decision, with a section
`## Tulajdonosi lezárás (<id>)` and the note; the nightly reviewer does not judge it again.

Recording needs the learner lock only, never the VM lock: a round with continuous work holds
the VM lock for hours, and the request touches only this learner's state files (fix-51)."""

import re
import sys
from contextlib import contextmanager

from ..figures import pending as figure_pending
from ..log import now_iso
from ..review import files
from ..state import phase, safefs
from ..state.files import read_json, write_json
from ..wiki import frontmatter as fm
from .context import Ctx

ITEM = re.compile(r"^(docs/review/[^#\s]+\.md)#(R\d+)$")
FIGURE = re.compile(r"^figure:([a-z0-9-]{1,64})$")
MAIN = "refs/remotes/origin/main"
NOTE_MAX = 500


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "reopen.json"


def load(ctx) -> list[dict]:
    return read_json(path(ctx), [])


def request(ctx: Ctx, targets: list[str], *, paid: bool = False) -> str:
    """Validate the targets against origin/main and record one reopen request."""
    with _learner_lock(ctx):
        return _request(ctx, targets, paid)


def close(ctx: Ctx, targets: list[str], note: str) -> str:
    """Validate owner items against origin/main and record one closing request."""
    with _learner_lock(ctx):
        return _close_request(ctx, targets, note)


@contextmanager
def _learner_lock(ctx):
    """The learner lock serializes this with the runs that read and write the same state
    files; it is free between two runs of a round, so the command never starves."""
    lock = ctx.lock()
    lock.acquire("reopen", poll_s=0.5, on_wait=lambda holder: print(
        f"várok a tanulói zárra ({holder.get('kind', 'ismeretlen')} óta {holder.get('since', '?')})…",
        file=sys.stderr))
    try:
        yield
    finally:
        lock.release()


def _request(ctx, targets, paid):
    items, figures, paid_ids, problems = [], [], [], []
    show = lambda rel: _show(ctx, rel)
    pending_entries = {e["commission"]["id"]: e for e in _pending_at(show)}
    for target in targets:
        item, figure = ITEM.match(target), FIGURE.match(target)
        if item:
            status, detail = _item_at(show, item[1], item[2])
            if status != files.OWNER:
                problems.append(f"{target}: not waiting for the owner ({status or 'no such item'})")
                continue
            items.append(target)
            fid, own = detail.get("figure_id"), pending_entries.get(detail.get("figure_id"))
            if (own and own["owner_required"] and "figure:" + fid not in targets
                    and not figure_pending.generated_at(own["commission"], show)):
                figures.append(fid)       # the item's own drawn figure is reopened with it
        elif figure:
            entry_ = pending_entries.get(figure[1])
            if not entry_ or not entry_["owner_required"]:
                problems.append(f"{target}: no pending figure waiting for the owner")
            elif figure_pending.generated_at(entry_["commission"], show):
                if not paid:
                    problems.append(f"{target}: a generated image; its paid attempts are in the image ledger. "
                                    "With the owner's approval `--paid` opens one new frame of paid attempts")
                elif not _paid_used_up(ctx, figure[1]):
                    problems.append(f"{target}: its paid attempts are not used up; nothing to approve")
                else:
                    figures.append(figure[1])
                    paid_ids.append(figure[1])
            elif paid:
                problems.append(f"{target}: a drawn figure costs nothing; reopen it without --paid")
            else:
                figures.append(figure[1])
        else:
            problems.append(f"{target}: use docs/review/<file>.md#R<n> or figure:<id>")
    if paid and not paid_ids and not problems:
        problems.append("--paid needs a generated image target: figure:<id>")
    if problems:
        return "Nem rögzítettem semmit:\n" + "\n".join(problems)
    requests = load(ctx)
    value = {"id": _new_id(requests), "at": now_iso(), "items": sorted(set(items)), "figures": sorted(set(figures))}
    if paid_ids:
        value["paid"] = sorted(set(paid_ids))
    write_json(path(ctx), requests + [value])
    _unpark(ctx, value)
    ctx.log.event("owner.reopen_requested", target=value["id"], items=value["items"], figures=value["figures"],
                  paid=value.get("paid", []))
    paid_text = f"; {len(paid_ids)} képnek új fizetős keret ({ctx.image_settings().max_attempts} próba)" if paid_ids else ""
    return (f"{value['id']}: a következő javító futás újranyitja "
            f"({len(value['items'])} tétel, {len(value['figures'])} ábra{paid_text})")


def _close_request(ctx, targets, note):
    note = " ".join((note or "").split())
    problems = [] if note else ["--note is required: the owner's reason, one line"]
    if len(note) > NOTE_MAX:
        problems.append(f"--note is longer than {NOTE_MAX} characters")
    show = lambda rel: _show(ctx, rel)
    for target in targets:
        item = ITEM.match(target)
        if not item:
            problems.append(f"{target}: use docs/review/<file>.md#R<n>")
            continue
        status, _ = _item_at(show, item[1], item[2])
        if status != files.OWNER:
            problems.append(f"{target}: not waiting for the owner ({status or 'no such item'})")
    if problems:
        return "Nem rögzítettem semmit:\n" + "\n".join(problems)
    requests = load(ctx)
    value = {"id": _new_id(requests, "close"), "at": now_iso(), "items": [], "figures": [],
             "close": sorted(set(targets)), "note": note}
    write_json(path(ctx), requests + [value])
    _unpark(ctx, {"items": value["close"], "figures": []})
    ctx.log.event("owner.close_requested", target=value["id"], items=value["close"], note=note)
    return f"{value['id']}: a következő javító futás lezárja ({len(value['close'])} tétel, javítva)"


def _paid_used_up(ctx, fid) -> bool:
    from ..images import plans
    from ..images.generate import attempts_used
    settings = ctx.image_settings()
    job = settings.ledger().get("jobs", {}).get(plans.job_id(settings.learner, fid))
    return bool(job) and attempts_used(job) >= settings.max_attempts


def _new_id(requests, prefix="reopen") -> str:
    """Unique among the recorded requests, also within one second (a sequence suffix)."""
    stamp, known = prefix + "-" + now_iso()[:19].replace(":", "").replace("-", ""), {v["id"] for v in requests}
    n = len(requests) + 1
    while f"{stamp}-{n}" in known:
        n += 1
    return f"{stamp}-{n}"


def waiting(ctx) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Read-only: (requests still to carry, (request, run id) pairs a finished run carried).
    A request whose run was closed without finishing (discarded) is free again."""
    tasks = {t.run_id: t for t in phase.all_tasks(ctx.task_root(), ctx.name)}
    kept, done = [], []
    for value in load(ctx):
        task = tasks.get(value.get("run_id"))
        if task is not None and task.phase == "done":
            done.append((value, task.run_id))
        elif value.get("run_id") and (task is None or not task.open):
            kept.append({k: v for k, v in value.items() if k != "run_id"})
        else:
            kept.append(value)
    return kept, done


def pending(ctx) -> list[dict]:
    """Requests no run carries now; a finished run's request is done, a discarded run's
    request is applied again."""
    kept, done = waiting(ctx)
    for value, run_id in done:
        ctx.log.event("owner.reopen_done", target=value["id"], run_id=run_id)
    if kept != load(ctx):
        write_json(path(ctx), kept)
    return [v for v in kept if not v.get("run_id")]


def apply(ctx, task) -> tuple[list[str], list[str]]:
    """In the fix run's worktree: returns (written paths, reopened figure ids). A discarded
    run's request is freed here too: `next_task` asks `pending` only when it has no other work."""
    repo, written, reopened = ctx.notes_path, set(), []
    pending(ctx)
    requests = load(ctx)
    for value in requests:
        if value.get("run_id") not in (None, task.run_id):
            continue
        granted = [(fid, _grant(ctx, fid, value["id"])) for fid in value.get("paid", [])]
        extra = [f"* figure:{fid} – új fizetős keret: legfeljebb {g['attempts']} próba, a tulajdonos jóváhagyásával; "
                 "a korábbi próbák a képnyilvántartásban maradnak." for fid, g in granted if g]
        for rel, item_ids in sorted(_by_file(value["items"]).items()):
            if _reopen_items(repo, rel, item_ids, value["id"], extra):
                written.add(rel)
            extra = []                    # the frame's line goes into the request's first file
        for rel, item_ids in sorted(_by_file(value.get("close", [])).items()):
            if _close_items(repo, rel, item_ids, value["id"], value["note"]):
                written.add(rel)
        for fid in value["figures"]:
            if _reopen_figure(repo, fid):
                written.add(figure_pending.PATH)
            reopened.append(fid)
        value["run_id"] = task.run_id
        ctx.log.event("owner.closed" if value.get("close") else "owner.reopened", target=value["id"],
                      run_id=task.run_id, items=value["items"] or value.get("close", []),
                      figures=value["figures"], paid=value.get("paid", []))
    if requests:
        write_json(path(ctx), requests)
    return sorted(written), sorted(set(reopened))


def _by_file(keys):
    found = {}
    for key in keys:
        rel, item_id = key.split("#", 1)
        found.setdefault(rel, []).append(item_id)
    return found


def _reopen_items(repo, rel, item_ids, request_id, extra=()) -> bool:
    if not safefs.is_file(repo, rel):
        return False
    text = safefs.read_text(repo, rel)
    page = fm.split(text)
    if f"## Újranyitva ({request_id})" in page.body:
        return True                       # an interrupted preparation already wrote it
    items, details = dict(page.meta.get("items") or {}), dict(page.meta.get("item_details") or {})
    reopened = [i for i in sorted(item_ids, key=files._num) if items.get(i) == files.OWNER]
    if not reopened:
        return False
    for item_id in reopened:
        items[item_id] = files.OPEN
        record = {k: v for k, v in details.get(item_id, {}).items() if k != "owner_question"}
        details[item_id] = {**record, "repair_attempts": 0}
    lines = [f"* {i} – újranyitva: a tulajdonos újranyitotta, az akadály megszűnt; a próbaszámláló nullázva."
             for i in reopened] + list(extra)
    body = page.body.rstrip("\n") + f"\n\n## Újranyitva ({request_id})\n\n" + "\n".join(lines) + "\n"
    new = fm.set_keys(f"---\n{page.raw_meta}\n---\n{body}",
                      {"items": items, "item_details": details, "status": files.compute_status(items)})
    safefs.write_text(repo, rel, new)
    return True


def _close_items(repo, rel, item_ids, request_id, note) -> bool:
    """Owner items become `fixed` by the owner's decision; the nightly reviewer does not
    judge such a closure again (`owner_closed`)."""
    if not safefs.is_file(repo, rel):
        return False
    text = safefs.read_text(repo, rel)
    page = fm.split(text)
    if f"## Tulajdonosi lezárás ({request_id})" in page.body:
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
    body = page.body.rstrip("\n") + f"\n\n## Tulajdonosi lezárás ({request_id})\n\n" + "\n".join(lines) + "\n"
    new = fm.set_keys(f"---\n{page.raw_meta}\n---\n{body}",
                      {"items": items, "item_details": details, "status": files.compute_status(items)})
    safefs.write_text(repo, rel, new)
    return True


def _grant(ctx, fid, request_id) -> dict | None:
    """The owner's paid exception: one new frame of attempts for the image (once per request).
    Returns the request's grant, or None when the image has no ledger entry (logged)."""
    from ..images import generate
    from ..figures import rechecks
    result = generate.grant(ctx.image_settings(), fid, request_id)
    if result is None:
        ctx.log.event("owner.paid_frame", "no_ledger_entry", level="warning", target=fid, request=request_id)
        return None
    granted, new = result
    if new:
        # The new frame's candidates need their own free review assignments.
        saved = read_json(rechecks.path(ctx), {})
        if fid in saved:
            write_json(rechecks.path(ctx), {k: v for k, v in saved.items() if k != fid})
        ctx.log.event("owner.paid_frame", target=fid, request=request_id, first_attempt=granted["first_attempt"],
                      attempts=granted["attempts"])
    return granted


def _reopen_figure(repo, fid) -> bool:
    entries = figure_pending.load(repo)
    found = next((e for e in entries if e["commission"]["id"] == fid), None)
    if found is None or not found["owner_required"]:
        return False
    found.update(runs=0, run_ids=[], owner_required=False)
    found.pop("review_pending", None)
    safefs.write_json(repo, figure_pending.PATH, entries)
    return True


def _unpark(ctx, value):
    from . import fix_progress
    keys = set(value["items"]) | {"figure:" + f for f in value["figures"]}
    parked = read_json(fix_progress.path(ctx), {})
    if keys & set(parked):
        write_json(fix_progress.path(ctx), {k: v for k, v in parked.items() if k not in keys})


def _show(ctx, rel):
    proc = ctx.bare().run("show", f"{MAIN}:{rel}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def _item_at(show, rel, item_id):
    text = show(rel)
    if text is None:
        return None, {}
    page = files.parse_report(text)
    return (page.meta.get("items") or {}).get(item_id), (page.meta.get("item_details") or {}).get(item_id, {})


def _pending_at(show):
    import json
    text = show(figure_pending.PATH)
    return json.loads(text) if text else []

