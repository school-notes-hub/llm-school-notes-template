"""`fetch` (plan 5.2): Drive → downloads → Feldolgozva → sources/ + work branch + fetch.json.

Every phase is recorded before its external action (8.2) and can be repeated."""

import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ..drive import inventory
from ..drive.client import FileChanged
from ..drive.download import download_package
from ..drive.inventory import DriveFile, Package
from ..drive.move import move_to_processed
from ..git import repos, workbranch
from ..git.run import with_retries
from ..images import pending as image_pending
from ..images import plans as image_plans
from ..log import now_iso, today
from ..review import files as review_files
from ..schemas import validate
from ..sources import calls, cards, naming
from ..sources.batch import select_batch
from ..sources.duplicates import known_hashes
from ..sources.naming import subject_key
from ..sources.place import Downloaded, Settings, place_package
from ..sources.prepare import pdf_page_count
from ..state import phase
from ..state import safefs
from ..state.errors import Transient
from ..state.files import write_json
from ..state.phase import Task
from . import steps
from .context import Ctx


def start(ctx: Ctx, mode: str, drive) -> Task | None:
    """Create a run for ready packages, or always in an interactive session."""
    ready = _scan(ctx, drive, mode)
    if not ready and mode == "cron":
        return None
    task = phase.create(ctx.task_root(), ctx.name, "notes", mode, "downloading")
    task.update(candidates=[_pack(p) for p in ready])
    return task


def _scan(ctx: Ctx, drive, mode: str) -> list[Package]:
    if drive is None:
        return []
    try:
        inv = inventory.scan(drive, ctx.student.drive_root,
                             ready_after_s=ctx.cfg.sources.ready_after_s)
    except Transient:
        if mode == "interactive":
            ctx.log.event("drive.scan", "offline")      # 5.2: interactive runs go on offline
            return []
        raise
    write_json(ctx.cfg.state_dir / ctx.name / "last-run.json",
               {"at": now_iso(), **inv.summary(), "ready_ids": sorted(p.id for p in inv.ready)})
    return inv.ready


def download(ctx: Ctx, task: Task, drive) -> None:
    """`downloading` → `downloaded`: download candidates until the 30-page batch is full."""
    target = task.dir / "downloads"
    shutil.rmtree(target, ignore_errors=True)      # a repeated download starts clean (8.2)
    records: dict[str, list[dict]] = {}

    changed: list[Package] = []

    def page_count(pkg: Package) -> int:
        try:
            records[pkg.id] = download_package(drive, pkg, target / pkg.id,
                                               ctx.cfg.timeouts.download_package_s)
        except FileChanged as exc:
            # 4.1: a package that changed after the listing just waits on Drive.
            ctx.log.event("drive.download", "changed", target=pkg.label, message=str(exc)[:200])
            changed.append(pkg)
            shutil.rmtree(target / pkg.id, ignore_errors=True)
            return 0
        return _pages(pkg, records[pkg.id])

    candidates = [_unpack(p) for p in task.get("candidates", [])]
    selected, dropped = select_batch(candidates, page_count, ctx.cfg.sources.pages_per_call)
    selected = [(pkg, n) for pkg, n in selected if pkg not in changed]
    for pkg in dropped:
        shutil.rmtree(target / pkg.id, ignore_errors=True)
    task.set_phase("downloaded", selected=[
        {"package": _pack(pkg), "pages": pages, "files": records[pkg.id]}
        for pkg, pages in selected])


def _pages(pkg: Package, files: list[dict]) -> int:
    if pkg.preconverted:
        return 1
    return sum(pdf_page_count(Path(f["path"])) if f["rel"].lower().endswith(".pdf") else 1
               for f in files)


def move(ctx: Ctx, task: Task, drive) -> None:
    """`downloaded` → `moved`: each package to Feldolgozva unless it changed meanwhile."""
    _validated_base(ctx, task)
    kept = []
    for item in task.get("selected", []):
        pkg = item["package"]
        result = move_to_processed(drive, pkg["id"], pkg["listed"], ctx.student.drive_root)
        ctx.log.event("drive.move", result, target=f"{pkg['id']} {pkg['name']}")
        if result == "changed":
            shutil.rmtree(task.dir / "downloads" / pkg["id"], ignore_errors=True)
        else:
            kept.append(item)
    task.set_phase("moved", selected=kept)


def prepare(ctx: Ctx, task: Task, *, new_subject_index) -> None:
    """`moved` → `prepared`: work branch, sources, fetch data, tool writes (5.2/5, 6.5).

    `new_subject_index(repo, subject, drive_name) -> list[str]` writes a new subject's
    index skeleton."""
    wt = ctx.worktree("notes")
    base = _validated_base(ctx, task)
    workbranch.start(wt, task.run_id, base, interactive=task.mode == "interactive")
    workbranch.reset_workdir(ctx.notes_path)
    packages, pages, written = _place_all(ctx, task, new_subject_index)
    settings = ctx.image_settings()
    found = image_pending.scan(settings)
    image_plans.restore(settings, [i["plan_id"] for i in found["pending"]])
    fresh = [p for p in pages if not p["duplicate_of"]]
    task.update(tool_writes=task.get("tool_writes", {}), tool_parts=task.get("tool_parts", {}))
    steps.record_tool_files(task, ctx.notes_path, written)
    from . import learning
    learning.migrate(ctx, task)
    reviews = calls.select_reviews(review_files.open_items(ctx.notes_path, task.mode),
                                   ctx.cfg.limits.review_closures_per_run, mode=task.mode, repo=ctx.notes_path) if task.mode == "interactive" else []
    assigned = calls.assignments(ctx.notes_path, packages, pages, reviews, found["pending"],
                                 ctx.cfg.sources.pages_per_call, ctx.cfg.limits.review_closures_per_run,
                                 mode=task.mode)
    from ..figures import pending as figure_pending
    from . import correction_figures
    subjects = {c["subject"] for c in assigned}
    waiting = [e for e in figure_pending.load(ctx.notes_path) if e["commission"]["page"].split("/")[1] in subjects]
    eligible = correction_figures.assignable(ctx, waiting)
    steps.record_tool_files(task, ctx.notes_path, correction_figures.persist_owners(ctx, waiting))
    pending_figures = figure_pending.for_subjects(ctx.notes_path, subjects,
                                                  allowed={e["commission"]["id"] for e in eligible})
    task.set_phase("prepared", base=base, packages=packages, pages=pages,
                   pending_figures=pending_figures,
                   max_agents=ctx.cfg.limits.max_agents, attempt=1,
                   calls=assigned, ranges=calls.ranges(assigned) or [[0, 0]],
                   open_review_items=reviews,
                   pending_images=found["pending"],
                   skip_writer=bool(pages) and not fresh and not found["pending"] and not reviews and not pending_figures,
                   dot_git=safefs.read_text(ctx.notes_path, ".git"))


def _base(ctx: Ctx, task: Task, wt) -> str:
    """origin/main after a fetch; interactively the last fetched one when GitHub is down."""
    try:
        with_retries(lambda: repos.fetch(ctx.bare(), ctx.cfg.timeouts.fetch_s), log=ctx.log)
    except Transient:
        if task.mode != "interactive":
            raise
        task.update(offline=True)
    return repos.rev(wt, "refs/remotes/origin/main")


def _validated_base(ctx: Ctx, task: Task, *, pin: bool = True) -> str:
    """Refresh during download; pin before the first move and keep it across resume."""
    base = task.get("preparation_base")
    if base and (task.get("preparation_started") or task.phase == "moved"):
        return base
    wt = ctx.worktree("notes")
    base = _base(ctx, task, wt)
    for path, check in ((naming.SUBJECTS, naming.preflight), (cards.PATH, cards.preflight)):
        pinned = wt.run("show", f"{base}:{path}", check=False)
        if pinned.returncode == 0:
            check(pinned.stdout)
    if pin:
        task.update(preparation_base=base, preparation_started=True)
    elif task.get("preparation_base"):
        task.update(preparation_base=None)  # Old tasks pinned too early, before download.
    return base


def _place_all(ctx: Ctx, task: Task, new_subject_index):
    repo = ctx.notes_path
    known = known_hashes(repo)
    settings = Settings(ctx.cfg.sources.max_side_px, ctx.cfg.sources.jpeg_quality,
                        ctx.cfg.sources.pdf_dpi, ctx.tools_dir())
    packages, pages, written, seq = [], [], [], 1
    for item in task.get("selected", []):
        pkg = item["package"]
        subject, is_new = subject_key(pkg["subject_name"], repo)
        if is_new:
            written += new_subject_index(repo, subject, pkg["subject_name"])
        placed = place_package(repo, Downloaded(
            drive_folder=pkg["name"], subject=subject, role=pkg["role"],
            description=pkg["description"], new_subject=is_new,
            preconverted=pkg["preconverted"], files=item["files"]), seq, known, settings)
        packages.append(placed.package)
        pages += placed.pages
        written += placed.written
        seq += len(placed.pages)
    return packages, pages, written


def advance(ctx: Ctx, task: Task, drive_factory) -> None:
    """`downloading` … `prepared` from the recorded phase (8.2); shared by cron and chat.
    `drive_factory()` returns the Drive client, or None when a session works offline."""
    if task.phase in ("downloading", "downloaded"):
        _validated_base(ctx, task, pin=False)
        drive = drive_factory()
        if drive is None:
            task.set_phase("moved", selected=[])        # offline session: no new packages
        else:
            if task.phase == "downloading":
                download(ctx, task, drive)
            move(ctx, task, drive)
    if task.phase == "moved":
        prepare(ctx, task, new_subject_index=new_subject)


def new_subject(repo, subject: str, drive_name: str) -> list[str]:
    """5.9: the index skeleton of a subject seen for the first time."""
    from ..wiki import machine
    path = machine.create_subject(repo, subject, drive_name, f"{subject}-banner")
    return [path] if path else []


def fetch_json(task: Task, k: int, *, grade: int, whole_run: bool = False, repo=None) -> dict:
    """The fetch.json of range k (1-based), validated (4.4). `grade` is the learner's
    configured school year: with PROFILE.md it places the subject for the writer (4.3)."""
    first, last = task.get("ranges")[k - 1]
    data = {"student": task.data["student"], "learner": {"grade": grade},
            "run_id": task.run_id, "mode": task.mode,
            "packages": task.get("packages", []), "pages": task.get("pages", []),
            "range": {"from": first, "to": last, "k": k, "n": len(task.get("ranges"))},
            "open_review_items": task.get("open_review_items", []),
            "pending_images": task.get("pending_images", [])}
    if task.get("calls") and not whole_run and (task.mode != "interactive" or task.get("mode") == "repair"):
        call = task.get("calls")[k - 1]
        data.update(subject=call["subject"],
                    packages=[data["packages"][n] for n in call["packages"]],
                    pages=[p for p in data["pages"] if p["seq"] in call["seqs"]],
                    open_review_items=call["open_review_items"],
                    pending_images=call["pending_images"])
        if "card" in call:
            data["card"] = call["card"]
    if task.get("mode") == "fix":
        data["mode"] = "fix"
    data["pending_figures"] = [e for e in task.get("pending_figures", [])
                               if whole_run or not data.get("subject") or
                               e["commission"]["page"].split("/")[1] == data["subject"]]
    if task.get("mode") == "repair":
        data.update(mode="repair", repair_targets=task.get("repair_targets", []))
    if task.get("conflict_files"):
        data["conflict_files"] = task.get("conflict_files")
    if task.get("offline"):
        data["offline"] = True
    if repo is not None:
        from . import licensing
        data["approved_figure_requests"] = licensing.for_fetch(repo, data)
        from ..figures import infographics
        if task.get("infographic_policy"):
            run_id = task.get("correction_parent", task.run_id)
            data["infographic_run_id"] = run_id
            data["infographic_commissions"] = task.get("infographic_commissions", [])
            pages = infographics.assigned(repo, data) if data["mode"] in ("fix", "repair") else []
            data["infographic_pages"] = infographics.needed(repo, pages, run_id)
    validate("fetch", data)
    return data


def _pack(pkg: Package) -> dict:
    data = asdict(pkg)
    data["latest"] = pkg.latest.isoformat()
    return data


def _unpack(data: dict) -> Package:
    fields = dict(data)
    fields["latest"] = datetime.fromisoformat(data["latest"])
    fields["files"] = [DriveFile(**f) for f in data["files"]]
    return Package(**fields)


def drive_client(ctx: Ctx):
    """The Drive client, or a Prerequisite error when the token is unusable."""
    from ..drive.client import DriveClient, DriveMediaTransport
    transport = DriveMediaTransport(ctx.cfg.secrets_dir, ctx.cfg.timeouts.drive_call_s,
                                    tools_dir=ctx.tools_dir())
    return DriveClient(transport, ctx.cfg.timeouts.download_package_s)
