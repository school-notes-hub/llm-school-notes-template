"""`school-notes status --reopen <learner> <target>...` (fix-49): the owner reopens a review
item and/or a pending figure that waits for him, once the obstacle is gone.

Targets are `docs/review/<file>.md#R<n>` (an item in `owner` state) and `figure:<id>` (a drawn
pending figure with `owner_required`). The command only records the request on the VM (it is
logged); the next fix run applies it in its own worktree, before it lists its work, and
commits it with the run: the item is `open` again with its repair counter at zero (a line
`## Újranyitva (<id>)` in the review file says so), the figure's run counter is zero. A
request whose run finished is done; one whose run was discarded is applied by the next run.
Generated images are reopened only with `--paid`, the owner's explicit approval, and only when
their paid attempts are used up: the run that applies the request opens one new frame of paid
attempts for the image in the image ledger (the old attempts stay there, the monthly budget
still applies); the frame's line goes into the request's first review file when it has an item,
otherwise the ledger and the log keep it. Without a ledger entry no frame opens and the image
stays with the owner (logged).

A figure that is only parked (no progress in a run, not used up) needs no reopening: the
command lifts the parking at once, without a request and without any paid frame (fix-52).

`status --close` is the pair (`owner_close.py`). Recording needs the learner lock only, never
the VM lock (fix-51); the wait for it is bounded, then the owner tries later (fix-52)."""

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
WAIT_S = 600


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "reopen.json"


def load(ctx) -> list[dict]:
    return read_json(path(ctx), [])


class LockBusy(Exception):
    """The learner lock stayed held for `WAIT_S`: the owner tries later."""


def request(ctx: Ctx, targets: list[str], *, paid: bool = False) -> str:
    """Validate the targets against origin/main and record one reopen request."""
    try:
        with learner_lock(ctx):
            return _request(ctx, targets, paid)
    except LockBusy as exc:
        return f"Nem rögzítettem semmit: {exc}"


@contextmanager
def learner_lock(ctx):
    """The learner lock serializes this with the runs that read and write the same state
    files; it is free between two runs of a round. A long run makes the command give up
    after `WAIT_S` instead of blocking for hours."""
    lock = ctx.lock()
    if not lock.acquire("reopen", poll_s=0.5, timeout_s=WAIT_S, on_wait=lambda holder: print(
            f"várok a tanulói zárra ({holder.get('kind', 'ismeretlen')} óta {holder.get('since', '?')}), "
            f"legfeljebb {WAIT_S // 60} percig…", file=sys.stderr)):
        holder = lock.holder()
        raise LockBusy(f"a tanulói zárat {holder.get('kind', 'ismeretlen')} tartja {holder.get('since', '?')} óta; "
                       f"{WAIT_S // 60} perc várakozás után feladtam, próbáld később")
    try:
        yield
    finally:
        lock.release()


def _request(ctx, targets, paid):
    from . import reopen_targets
    found = {"items": [], "figures": [], "paid": [], "unpark": []}
    read = lambda rel: show(ctx, rel)
    entries = {e["commission"]["id"]: e for e in _pending_at(read)}
    problems = [f"{t}: {p}" for t in targets if (p := reopen_targets.sort(ctx, t, targets, paid, read, entries, found))]
    if paid and not found["paid"] and not problems:
        problems.append("--paid needs a generated image waiting for the owner: figure:<id>"
                        + ("; a parked figure is freed without --paid" if found["unpark"] else ""))
    if problems:
        return "Nem rögzítettem semmit:\n" + "\n".join(problems)
    answers = [_record(ctx, found)] if found["items"] or found["figures"] else []
    if found["unpark"]:
        unparked = ["figure:" + f for f in sorted(set(found["unpark"]))]
        unpark(ctx, {"items": [], "figures": sorted(set(found["unpark"]))})
        ctx.log.event("owner.unparked", figures=unparked)
        answers.append(f"parkolás feloldva (fizetős keret nélkül): {', '.join(unparked)}; "
                       "a következő javító futás dolgozik rajta")
    return "; ".join(answers)


def _record(ctx, found):
    requests = load(ctx)
    value = {"id": new_id(requests), "at": now_iso(), "items": sorted(set(found["items"])),
             "figures": sorted(set(found["figures"]))}
    if found["paid"]:
        value["paid"] = sorted(set(found["paid"]))
    write_json(path(ctx), requests + [value])
    unpark(ctx, value)
    ctx.log.event("owner.reopen_requested", target=value["id"], items=value["items"], figures=value["figures"],
                  paid=value.get("paid", []))
    paid_text = (f"; {len(value['paid'])} képnek új fizetős keret ({ctx.image_settings().max_attempts} próba)"
                 if found["paid"] else "")
    return (f"{value['id']}: a következő javító futás újranyitja "
            f"({len(value['items'])} tétel, {len(value['figures'])} ábra{paid_text})")


def new_id(requests, prefix="reopen") -> str:
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
    from . import owner_close
    repo, written, reopened = ctx.notes_path, set(), []
    pending(ctx)
    requests = load(ctx)
    for value in requests:
        if value.get("run_id") not in (None, task.run_id):
            continue
        granted = {fid: _grant(ctx, fid, value["id"]) for fid in value.get("paid", [])}
        extra = [f"* figure:{fid} – új fizetős keret: legfeljebb {g['attempts']} próba, a tulajdonos jóváhagyásával; "
                 "a korábbi próbák a képnyilvántartásban maradnak." for fid, g in sorted(granted.items()) if g]
        for rel, item_ids in sorted(by_file(value["items"]).items()):
            if _reopen_items(repo, rel, item_ids, value["id"], extra):
                written.add(rel)
                extra = []                # the frame's line goes into the request's first written file
        if value.get("close"):
            written |= owner_close.apply(ctx, repo, value, task.run_id)
        for fid in value["figures"]:
            if fid in granted and granted[fid] is None:
                continue                  # no frame opened: the image stays with the owner
            if _reopen_figure(repo, fid):
                written.add(figure_pending.PATH)
            reopened.append(fid)
        value["run_id"] = task.run_id
        if not value.get("close"):
            ctx.log.event("owner.reopened", target=value["id"], run_id=task.run_id, items=value["items"],
                          figures=value["figures"], paid=value.get("paid", []))
    if requests:
        write_json(path(ctx), requests)
    return sorted(written), sorted(set(reopened))


def by_file(keys):
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


def _grant(ctx, fid, request_id) -> dict | None:
    """The owner's paid exception: one new frame of attempts for the image (once per request).
    Returns the request's grant, or None when the image has no ledger entry (logged; the image
    stays with the owner). The old frame's free review assignments are dropped before the grant
    is written, so an interrupted preparation cannot keep them for the new frame."""
    from ..images import generate, plans
    settings = ctx.image_settings()
    job = settings.ledger().get("jobs", {}).get(plans.job_id(settings.learner, fid))
    if job is not None and not any(g.get("request") == request_id for g in job.get("grants", [])):
        _drop_rechecks(ctx, fid)
    result = generate.grant(settings, fid, request_id) if job is not None else None
    if result is None:
        ctx.log.event("owner.paid_frame", "no_ledger_entry", level="warning", target=fid, request=request_id,
                      message="no frame opened; the image stays with the owner")
        return None
    granted, new = result
    if new:
        ctx.log.event("owner.paid_frame", target=fid, request=request_id, first_attempt=granted["first_attempt"],
                      attempts=granted["attempts"])
    return granted


def _drop_rechecks(ctx, fid):
    from ..figures import rechecks
    saved = read_json(rechecks.path(ctx), {})
    if fid in saved:
        write_json(rechecks.path(ctx), {k: v for k, v in saved.items() if k != fid})


def _reopen_figure(repo, fid) -> bool:
    entries = figure_pending.load(repo)
    found = next((e for e in entries if e["commission"]["id"] == fid), None)
    if found is None or not found["owner_required"]:
        return False
    found.update(runs=0, run_ids=[], owner_required=False)
    found.pop("review_pending", None)
    safefs.write_json(repo, figure_pending.PATH, entries)
    return True


def unpark(ctx, value):
    from . import fix_progress
    keys = set(value["items"]) | {"figure:" + f for f in value["figures"]}
    parked = read_json(fix_progress.path(ctx), {})
    if keys & set(parked):
        write_json(fix_progress.path(ctx), {k: v for k, v in parked.items() if k not in keys})


def show(ctx, rel):
    proc = ctx.bare().run("show", f"{MAIN}:{rel}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def item_at(show, rel, item_id):
    text = show(rel)
    if text is None:
        return None, {}
    page = files.parse_report(text)
    return (page.meta.get("items") or {}).get(item_id), (page.meta.get("item_details") or {}).get(item_id, {})


def _pending_at(show):
    import json
    text = show(figure_pending.PATH)
    return json.loads(text) if text else []
