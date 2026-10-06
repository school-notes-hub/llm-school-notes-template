"""`school-notes status --reopen <learner> <target>...` (fix-49): the owner reopens a review
item and/or a pending figure that waits for him, once the obstacle is gone.

Targets are `docs/review/<file>.md#R<n>` (an item in `owner` state) and `figure:<id>` (a drawn
pending figure with `owner_required`). The command only records the request on the VM (it is
logged); the next fix run applies it in its own worktree, before it lists its work, and
commits it with the run: the item is `open` again with its repair counter at zero (a line
`## Újranyitva (<id>)` in the review file says so), the figure's run counter is zero. A
request whose run finished is done; one whose run was discarded is applied by the next run.
Generated images are not reopened here: their paid attempts live in the image ledger."""

import re

from ..figures import pending as figure_pending
from ..log import now_iso
from ..review import files
from ..state import phase, safefs
from ..state.files import read_json, write_json
from ..wiki import frontmatter as fm
from .context import Ctx
from .operation import entry

ITEM = re.compile(r"^(docs/review/[^#\s]+\.md)#(R\d+)$")
FIGURE = re.compile(r"^figure:([a-z0-9-]{1,64})$")
MAIN = "refs/remotes/origin/main"


def path(ctx):
    return ctx.cfg.state_dir / ctx.name / "reopen.json"


def load(ctx) -> list[dict]:
    return read_json(path(ctx), [])


@entry("reopen", manual=True)
def request(ctx: Ctx, targets: list[str]) -> str:
    """Validate the targets against origin/main and record one request."""
    items, figures, problems = [], [], []
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
                problems.append(f"{target}: a generated image; its paid attempts are in the image ledger, "
                                "a new image needs a new commission")
            else:
                figures.append(figure[1])
        else:
            problems.append(f"{target}: use docs/review/<file>.md#R<n> or figure:<id>")
    if problems:
        return "Nem rögzítettem semmit:\n" + "\n".join(problems)
    requests = load(ctx)
    value = {"id": _new_id(requests), "at": now_iso(), "items": sorted(set(items)), "figures": sorted(set(figures))}
    write_json(path(ctx), requests + [value])
    _unpark(ctx, value)
    ctx.log.event("owner.reopen_requested", target=value["id"], items=value["items"], figures=value["figures"])
    return (f"{value['id']}: a következő javító futás újranyitja "
            f"({len(value['items'])} tétel, {len(value['figures'])} ábra)")


def _new_id(requests) -> str:
    """Unique among the recorded requests, also within one second (a sequence suffix)."""
    stamp, known = "reopen-" + now_iso()[:19].replace(":", "").replace("-", ""), {v["id"] for v in requests}
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
        for rel, item_ids in sorted(_by_file(value["items"]).items()):
            if _reopen_items(repo, rel, item_ids, value["id"]):
                written.add(rel)
        for fid in value["figures"]:
            if _reopen_figure(repo, fid):
                written.add(figure_pending.PATH)
            reopened.append(fid)
        value["run_id"] = task.run_id
        ctx.log.event("owner.reopened", target=value["id"], run_id=task.run_id,
                      items=value["items"], figures=value["figures"])
    if requests:
        write_json(path(ctx), requests)
    return sorted(written), sorted(set(reopened))


def _by_file(keys):
    found = {}
    for key in keys:
        rel, item_id = key.split("#", 1)
        found.setdefault(rel, []).append(item_id)
    return found


def _reopen_items(repo, rel, item_ids, request_id) -> bool:
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
             for i in reopened]
    body = page.body.rstrip("\n") + f"\n\n## Újranyitva ({request_id})\n\n" + "\n".join(lines) + "\n"
    new = fm.set_keys(f"---\n{page.raw_meta}\n---\n{body}",
                      {"items": items, "item_details": details, "status": files.compute_status(items)})
    safefs.write_text(repo, rel, new)
    return True


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

