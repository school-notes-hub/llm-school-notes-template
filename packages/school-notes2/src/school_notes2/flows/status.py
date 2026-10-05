"""`school-notes status [<learner>]` (plan 8.7): local state only, fast, no network."""

import json
import re
from datetime import date, datetime
from pathlib import Path

from ..git import workbranch
from ..images import pending as image_pending
from ..figures import requests as figure_requests, licenses
from ..log import TZ
from ..notify import incidents
from ..review import files as review_files
from ..sources import cards
from ..state.errors import NeedsOwner
from ..state import phase
from ..state import safefs
from ..state.files import read_json
from ..wiki import drafts
from ..wiki.pages import PageError, subjects as wiki_subjects
from .context import Ctx

OPEN_QUESTIONS = re.compile(r"^#+\s.*Nyitott kérdések", re.M)
BIG_REFERENCE = 40 * 1024


def summary(ctx: Ctx) -> dict:
    from .operation import vm_lock
    vm = vm_lock(ctx.cfg)
    vm_state = {"held": not vm.probe(), **vm.holder()}
    round_state = read_json(ctx.cfg.state_dir / "round.json", {})
    if round_state.get("status") == "running" and (not vm_state["held"] or vm_state.get("kind") != "round"):
        round_state["status"] = "interrupted"
    tasks = phase.all_tasks(ctx.task_root(), ctx.name)
    from .work_pending import completion
    return {
        "learner": ctx.name,
        "completion": completion(ctx, tasks=tasks, held=not ctx.lock().probe()),
        "incidents": incidents.active(ctx),
        "last_error": read_json(ctx.cfg.state_dir / ctx.name / "last-error.json"),
        "browser_warnings": [{"run_id": t.run_id, **i} for t in tasks for i in t.get("browser_warnings", [])],
        "vm_lock": vm_state,
        "round": round_state,
        "quota": read_json(ctx.cfg.state_dir / "quota.json", {}),
        "timeouts": read_json(ctx.cfg.state_dir / ctx.name / "timeouts.json", {}),
        **_permissions(ctx.notes_path),
        "lock": _lock(ctx),
        "open": [_task(t) for t in tasks if t.open],
        "needs_owner": [{"kind": t.kind, "run_id": t.run_id, **t.data["needs_owner"]}
                        for t in tasks if t.open and t.data.get("needs_owner")],
        "worktree_dirty_outside_run": _dirty_outside_run(ctx, tasks),
        "drive": read_json(ctx.cfg.state_dir / ctx.name / "last-run.json", {}),
        "images": _images(ctx),
        "review_items": _review_items(ctx),
        "last_review": _last(tasks, "review"),
        "nightly_state": _nightly_state(ctx),
        "wiki_open_questions": _open_questions(ctx.notes_path),
        "drafts": _drafts(ctx.notes_path),
        "cards": _cards(ctx.notes_path),
        "source_ref_counts": next((t.get("source_ref_counts", {}) for t in reversed(tasks)
                                   if t.kind == "notes"), {}),
        "public_footnote_counts": next((t.get("public_footnote_counts", {}) for t in reversed(tasks)
                                        if t.kind == "notes"), {}),
        "references_without_map": _unmapped(ctx.notes_path),
        "pack_mb": _pack_mb(ctx.cfg.bare(ctx.name)),
        "log": str(ctx.cfg.log_path),
    }


def _lock(ctx: Ctx) -> dict:
    lock = ctx.lock()
    if lock.probe():
        return {"held": False}
    return {"held": True, **lock.holder()}


def _task(t: phase.Task) -> dict:
    return {"kind": t.kind, "mode": t.get("mode", t.mode), "no_push": bool(t.get("no_push")), "run_id": t.run_id, "phase": t.phase,
            "age_h": _age_h(t.data["created"]), "packages": len(t.get("packages", [])),
            "retries": t.data["retries"], "llm_failures": t.data["llm_failures"],
            "source_ref_counts": t.get("source_ref_counts", {}),
            "quota_phase": t.get("quota_phase"), "blocked_topics": t.get("blocked_topics", []),
            "last_error": t.data.get("last_error"), "questions": t.get("question", [])}


def _age_h(iso: str) -> float:
    return round((datetime.now(TZ) - datetime.fromisoformat(iso)).total_seconds() / 3600, 1)


def _dirty_outside_run(ctx: Ctx, tasks: list[phase.Task]) -> bool:
    if any(t.kind == "notes" and t.open for t in tasks):
        return False
    try:
        return workbranch.worktree_dirty(ctx.worktree("notes"))
    except Exception:  # noqa: BLE001 - status never fails on a missing worktree
        return False


def _images(ctx: Ctx) -> dict:
    try:
        found = image_pending.scan(ctx.image_settings())
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}
    return {k: found[k] for k in ("pending", "exhausted", "waiting_unknown", "budget_left")}


def _review_items(ctx: Ctx) -> dict:
    if not ctx.notes_path.exists():
        return {"open": 0, "owner": 0}
    everything = review_files.open_items(ctx.notes_path, "interactive")   # open + owner
    still_open = review_files.open_items(ctx.notes_path, "cron")           # open only
    return {"open": len(still_open), "owner": len(everything) - len(still_open)}


def _last(tasks: list[phase.Task], kind: str) -> str | None:
    done = [t for t in tasks if t.kind == kind and t.phase == "done"]
    return done[-1].data["updated"] if done else None


def _open_questions(repo: Path) -> list[str]:
    out = []
    for rel in safefs.glob(repo, "wiki", "wiki/**/*.md") if repo.is_dir() else []:
        try:
            text = safefs.read_text(repo, rel, errors="replace")
        except (OSError, safefs.UnsafePath):
            continue                     # status never fails on the worktree's state
        if OPEN_QUESTIONS.search(text):
            out.append(rel)
    return out


def _drafts(repo: Path) -> dict:
    try:
        return {"warnings": [{"file": rel, "message": message}
                             for rel, message in drafts.warnings(repo, date.today())]} \
            if repo.is_dir() else {"warnings": []}
    except (PageError, OSError, safefs.UnsafePath) as exc:
        return {"error": str(exc)}


def _cards(repo: Path) -> dict:
    """Subjects of the learner without a shared card (plan 4.3): shown until the template's
    `subject-cards.json` has one and the shared files are synced. The run is not stopped."""
    if not repo.is_dir():
        return {"missing": []}
    try:
        known = set(wiki_subjects(repo))
        if safefs.is_file(repo, "tools/subjects.json"):
            known |= set(json.loads(safefs.read_text(repo, "tools/subjects.json")).get("subjects", {}))
        return {"missing": cards.missing(repo, known)}
    except (ValueError, TypeError, AttributeError, OSError, safefs.UnsafePath) as exc:
        return {"error": str(exc)[:200]}


def _unmapped(repo: Path) -> list[str]:
    """Big reference material without a map: the writer must not read it (5.9, B29)."""
    out = []
    for rel in safefs.glob(repo, "references", "references/**/document.md") \
            if repo.is_dir() else []:
        folder = rel.rsplit("/", 1)[0]
        try:
            big = len(safefs.read_bytes(repo, rel)) >= BIG_REFERENCE
            mapped = safefs.is_file(repo, f"{folder}/index.md")
        except (OSError, safefs.UnsafePath):
            continue
        if big and not mapped:
            out.append(folder)
    return out


def _pack_mb(bare: Path) -> float:
    packs = bare / "objects" / "pack"
    size = sum(p.stat().st_size for p in packs.glob("*.pack")) if packs.is_dir() else 0
    return round(size / 2**20, 1)


def render(data: dict) -> str:
    """The console form of `summary`."""
    lines = [f"== {data['learner']}"] + data.get("completion", [])
    for key, label in (("vm_lock", "VM-zár"), ("round", "kör"), ("quota", "heti keret"), ("timeouts", "T-125"), ("figure_requests", "licenckérelmek"),
                       ("approved_figure_requests", "engedélyezve, beillesztésre vár"),
                       ("license_error", "licencadat javítandó"), ("nightly_state", "éjszakai témakörök")):
        if data.get(key):
            lines.append(label + ": " + json.dumps(data[key], ensure_ascii=False, sort_keys=True))
    if data.get("last_error"):
        error = data["last_error"]
        lines.append(f"utolsó hiba ({error['at']}): {error['message']}")
    for error in data.get("incidents", []):
        lines.append(f"nyitott hiba ({error['at']}): {error['message']}")
    for warning in data.get("browser_warnings", []):
        lines.append(f"böngészős figyelmeztetés ({warning['run_id']}): {warning['file']}: {warning['message']}")
    lock = data["lock"]
    lines.append(f"zár: {'foglalt – ' + str(lock.get('kind')) + ' óta ' + str(lock.get('since')) if lock['held'] else 'szabad'}")
    for t in data["open"]:
        lines.append(f"nyitott {t['kind']} ({t['mode']}): {t['run_id']} fázis={t['phase']} "
                     f"kor={t['age_h']} h csomag={t['packages']} retries={t['retries']} "
                     f"llm_failures={t['llm_failures']}")
        if t.get("no_push"):
            state = "commit után megállt" if t["phase"] == "committed" else f"folyamatban; fázis: {t['phase']}"
            lines.append(f"próba: {state}; folytatás: school-notes finish, vagy status --discard")
    for n in data["needs_owner"]:
        lines.append(f"TULAJDONOSRA VÁR ({n['kind']} {n['run_id']}): {n['reason']} → {n['todo']}")
    if data["worktree_dirty_outside_run"]:
        lines.append("futáson kívüli változás a notes worktree-ben (school-notes chat)")
    drive = data["drive"]
    if drive:
        lines.append(f"Drive ({drive.get('at')}): kész {len(drive.get('ready', []))}, "
                     f"várakozik {len(drive.get('waiting', []))}, kihagyva {len(drive.get('ignored', []))}")
    img = data["images"]
    lines.append(f"képek: függő {len(img.get('pending', []))}, elakadt {len(img.get('exhausted', []))}, "
                 f"ismeretlen kimenet {'igen' if img.get('waiting_unknown') else 'nem'}, "
                 f"havi keret {'van' if img.get('budget_left') else 'elfogyott'}")
    r = data["review_items"]
    lines.append(f"review-tételek: nyitott {r['open']}, tulajdonosra vár {r['owner']}; "
                 f"utolsó review: {data['last_review'] or '-'}")
    if data["wiki_open_questions"]:
        lines.append(f"„Nyitott kérdések” a wikiben: {len(data['wiki_open_questions'])} oldal")
    for warning in data.get("drafts", {}).get("warnings", []):
        lines.append(f"14 napnál régebbi draft: {warning['file']}")
    if data.get("drafts", {}).get("error"):
        lines.append(f"draft-áttekintés: {data['drafts']['error']}")
    for subject in data.get("cards", {}).get("missing", []):
        lines.append(f"hiányzó kártya: {subject}")
    if data.get("cards", {}).get("error"):
        lines.append(f"kártyafájl: {data['cards']['error']}")
    for ref in data["references_without_map"]:
        lines.append(f"térkép nélkül, felvétel szükséges: {ref}")
    lines.append(f"pack: {data['pack_mb']} MiB; napló: {data['log']}")
    return "\n".join(lines)


def _permissions(repo):
    try:
        licenses.preflight(repo)
        active = figure_requests.active(repo)
        approved = figure_requests.approved(repo)
        return {"figure_requests": [r for r in active if r not in approved],
                "approved_figure_requests": approved}
    except (ValueError, OSError, safefs.UnsafePath, NeedsOwner) as exc:
        todo = getattr(exc, "todo", "correct docs/licenses.json")
        return {"figure_requests": [], "approved_figure_requests": [], "license_error": f"{exc}; {todo}"}


def _nightly_state(ctx):
    from ..review import figure_waiting, topics
    from ..git import repos
    wt = ctx.worktree("review")
    try:
        head = repos.rev(wt, "refs/remotes/origin/main")
        state = topics.read_state(ctx.bare(), head)
        state["pending_figures"] = json.loads(topics.text(ctx.bare(), head, figure_waiting.PATH) or "[]")
        state["blocked_topics"] = topics.unblocked(state.get("blocked_topics", []), ctx.cfg.state_dir, ctx.name)
        return state
    except (OSError, ValueError):
        return {}
