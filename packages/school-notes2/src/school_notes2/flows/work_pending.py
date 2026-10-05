"""Read-only admission facts shared by the scheduler and status."""

from ..figures import pending, migration_gate
from ..repair import queue
from ..review import files
from ..state import phase, safefs
from ..state.files import read_json
from . import correction_figures, fix_progress


def ready(ctx):
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    opened = [t for t in tasks if t.open and t.kind == "notes"]
    if opened:
        from . import transient_retry
        if not transient_retry.ready(opened[0]):
            return False
        return (opened[0].data.get("needs_owner") or {}).get("class") in (None, "transient") and opened[0].phase != "waiting_quota"
    drive = read_json(ctx.cfg.state_dir / ctx.name / "last-run.json", {})
    moved = {e["package"]["id"] for t in tasks if t.data["created"] >= drive.get("at", "")
             and t.phase not in ("downloading", "downloaded") for e in t.get("selected", [])}
    if set(drive.get("ready_ids", [])) - moved:
        return True
    if not ctx.notes_path.is_dir():
        return False
    items, figures = assignments(ctx)
    if items or any(not pending.generated(ctx.notes_path, e["commission"]) or
                    correction_figures.awaiting(ctx, e["commission"]) for e in figures) or (
                    figures and not fix_progress.image_wait(ctx, figures)):
        return True
    stopped = fix_progress.parked(ctx)
    data = queue.load(ctx.notes_path)
    states = {i["page"]: i["status"] for i in data["items"]}
    return any(i["status"] == "pending" and "repair:" + i["page"] not in stopped
               and all(states.get(p) == "done" for p in i["depends_on"]) for i in data["items"])


def assignments(ctx):
    items = [i for i in files.open_items(ctx.notes_path, "cron") if not migration_gate.concerns(ctx.notes_path, i)]
    figures = [] if migration_gate.blocked(ctx.notes_path) else [e for e in pending.load(ctx.notes_path)
        if not e["owner_required"] and (e["runs"] < 3 or e.get("review_pending"))]
    return fix_progress.available(ctx, items, figures)


def completion(ctx, *, tasks=None, held=False):
    tasks = tasks if tasks is not None else phase.all_tasks(ctx.task_root(), ctx.name)
    items = files.open_items(ctx.notes_path, "interactive") if ctx.notes_path.is_dir() else []
    figures = pending.load(ctx.notes_path) if ctx.notes_path.is_dir() else []
    missing = missing_images(ctx.notes_path) if ctx.notes_path.is_dir() else set()
    missing.update(e["commission"]["id"] for e in figures)
    opened = [t for t in tasks if t.open]
    n, m, k = sum(i["status"] == "open" for i in items), sum(i["status"] == "owner" for i in items), len(missing)
    eligible, waiting = assignments(ctx) if ctx.notes_path.is_dir() else ([], [])
    if held:
        automatic = "fut"
    elif opened:
        reason = "tulajdonosi döntés" if any(t.data.get("needs_owner") for t in opened) else "folytatás"
        automatic = f"vár ({reason})"
    elif eligible or waiting or ready(ctx):
        reason = "képkeret vagy ismeretlen képhívás" if not eligible and fix_progress.image_wait(ctx, waiting) else "indítható munka"
        automatic = f"vár ({reason})"
    elif n or any(not e["owner_required"] and e["runs"] < 3 for e in figures):
        automatic = "vár (félretett munka vagy migrációs kapu)"
    else:
        automatic = "lezárult"
    return [f"Automatikus feldolgozás: {automatic}",
            f"Tanulásra kész: {'igen' if n == m == k == 0 else 'nem'} – {n} nyitott tétel, {m} tulajdonosi tétel, {k} hiányzó kép"]


def missing_images(repo):
    from ..figures import commissions, context
    from ..wiki.pages import wiki_pages, links, resolve
    missing = set(commissions.markers(repo))
    for fid in sorted(missing):
        try:
            evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json", {})
            brief = safefs.read_json(repo, f".school-notes/figures/{fid}.json", evidence.get("commission"))
            candidate = safefs.read_json(repo, f".school-notes/figures/{fid}/figure.json", evidence.get("candidate"))
            if candidate and candidate.get("state") == "no-figure":
                missing.remove(fid)
            elif brief and candidate and evidence.get("verdict", {}).get("verdict") == "accept" and (
                    evidence["verdict"]["key"] == context.verdict_key(repo, brief, candidate)):
                missing.remove(fid)
        except (ValueError, OSError, KeyError):
            pass
    for page in sorted(wiki_pages(repo)):
        for link in links(safefs.read_text(repo, page)):
            if link.image and (target := resolve(page, link.target)) and not safefs.is_file(repo, target):
                missing.add(target)
    return missing
