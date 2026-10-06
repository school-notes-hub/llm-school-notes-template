"""`sn fetch <t> [--apply]` (plan 3.2, 3.3/1): the Drive inbox into the learner's working copy.

Without `--apply` it only lists: every package in the `Feltöltés_Kész` folders and every
leftover download. With `--apply`, package by package:

1. download (size and MD5 verified) into `downloads/<t>/<package id>/files/`;
2. place it into the working copy (`sources/<subject>/<folder>/`; a new subject gets its
   index skeleton; a doc-extract output nested in one subfolder is taken from that subfolder,
   `drive.inventory.wrapper`);
3. **only then** move the package folder on Drive to the subject's `Feldolgozva`;
4. delete the download.

No settle time: `Feltöltés_Kész` is filled by renaming, a package there is complete
(owner, 2026-10-06). The run can be repeated after any interruption: a marker file after each
step in the download folder says where to go on. A placed package is never placed twice (only
the move follows), and a placement cut off halfway is removed and placed again only while
none of its files is in git. Nothing is committed: the controller commits after the review."""

import json
import shutil
from pathlib import Path

from ..drive import inventory
from ..drive.client import FileChanged
from ..drive.download import download_package
from ..drive.inventory import Package
from ..drive.move import move_to_processed
from ..sources.duplicates import known_hashes
from ..sources.naming import slug, subject_key, unique_dir
from ..sources.place import Downloaded, Settings, place_package
from ..state import safefs
from ..state.errors import NeedsOwner

DOWNLOADED, PLACING, PLACED = "download.json", "placing.json", "placed.json"


def new_subject(repo: Path, subject: str, drive_name: str) -> list[str]:
    """The index skeleton of a subject seen for the first time (plan 5.9)."""
    from ..wiki import machine
    path = machine.create_subject(repo, subject, drive_name, f"{subject}-banner")
    return [path] if path else []


def order(pkg: Package) -> tuple:
    """A total, content-derived order (not Drive's upload times)."""
    return (pkg.role, pkg.subject_name, pkg.name, pkg.id)


def inbox(local, drive) -> tuple[list[Package], list[dict]]:
    """Every package in `Feltöltés_Kész` (ready and "waiting" alike: no settle time) and the
    skipped files, both in content order."""
    inv = inventory.scan(drive, local.ctx.student.drive_root, ready_after_s=0)
    packages = sorted(inv.ready + inv.waiting, key=order)
    return packages, inv.summary()["ignored"]


def stage(folder: Path) -> str:
    """Where a download folder stands: downloading | downloaded | placing | placed | unknown.
    `placing` without a download (the package changed on Drive) downloads again first."""
    if (folder / PLACED).is_file():
        return "placed"
    if (folder / DOWNLOADED).is_file():
        return "placing" if (folder / PLACING).is_file() else "downloaded"
    if (folder / "files").is_dir() or (folder / PLACING).is_file():
        return "downloading"
    return "unknown"          # e.g. a folder an older script left; not touched


def leftovers(local) -> dict[str, str]:
    root = local.downloads()
    return {p.name: stage(p) for p in sorted(root.iterdir())} if root.is_dir() else {}


def run(local, apply: bool, out=print) -> int:
    drive = local.drive()
    packages, ignored = inbox(local, drive)
    left = leftovers(local)
    out(f"{local.name}: {len(packages)} csomag a Feltöltés_Kész mappákban")
    for p in packages:
        kind = ", doc-extract" if p.preconverted else ""
        out(f"  {p.label} ({len(p.files)} fájl{kind}; {p.id})")
    for item in ignored:
        out(f"  kihagyva: {item['path']} – {item['reason']}")
    for pid, where in left.items():
        out(f"  félbemaradt letöltés: {pid} ({where})")
    if not apply:
        local.record("fetch", "listed", packages=[p.label for p in packages])
        return 0
    done, failed = [], []
    by_id = {p.id: p for p in packages}
    for pid in sorted(set(by_id) | {k for k, v in left.items() if v != "unknown"},
                      key=lambda i: (order(by_id[i]) if i in by_id else ("~",), i)):
        try:
            result = apply_one(local, drive, by_id.get(pid), local.downloads() / pid, out)
        except FileChanged as exc:
            result = f"changed: {exc}"
        (done if result in ("moved", "already") else failed).append((pid, result))
    local.record("fetch", "ok" if not failed else "partial", done=[d[0] for d in done],
                 failed=[f[0] for f in failed])
    for pid, result in failed:
        out(f"NEM KÉSZ: {pid}: {result}")
    return 1 if failed else 0


def apply_one(local, drive, pkg: Package | None, folder: Path, out) -> str:
    """Download → place → move → delete for one package; resumes from the folder's markers."""
    repo = local.repo
    if pkg is None:                     # its folder is no longer in Feltöltés_Kész
        if stage(folder) != "placed":
            return "not on Drive any more and not placed; check by hand"
        data = _read(folder / DOWNLOADED)
        return _move(local, drive, data["package"]["id"], data["package"]["listed"],
                     data["package"]["label"], folder, out)
    if stage(folder) in ("downloading", "unknown"):
        if stage(folder) == "unknown":
            shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(folder / "files", ignore_errors=True)    # a repeated download starts clean
        try:
            files = download_package(drive, pkg, folder / "files", local.cfg.timeouts.download_package_s)
        except FileChanged:
            shutil.rmtree(folder / "files", ignore_errors=True)
            raise
        _write(folder / DOWNLOADED, {"package": _pack(pkg), "files": files})
        out(f"letöltve: {pkg.label} ({len(files)} fájl)")
    if stage(folder) in ("downloaded", "placing"):
        _place(local, repo, pkg, folder, out)
    return _move(local, drive, pkg.id, pkg.listed, pkg.label, folder, out)


def _place(local, repo: Path, pkg: Package, folder: Path, out) -> None:
    data = _read(folder / DOWNLOADED)
    if (folder / PLACING).is_file():
        _remove_partial(local, repo, _read(folder / PLACING)["folder"])
    subject, is_new = subject_key(pkg.subject_name, repo)
    if is_new:
        for path in new_subject(repo, subject, pkg.subject_name):
            out(f"új tantárgy: {path}")
    target = unique_dir(repo / "sources" / subject, slug(pkg.name), repo)
    rel = safefs.rel_of(repo, target)
    _write(folder / PLACING, {"folder": rel})
    settings = Settings(local.cfg.sources.max_side_px, local.cfg.sources.jpeg_quality,
                        local.cfg.sources.pdf_dpi, local.ctx.tools_dir())
    files = [{**f, "path": str(folder / "files" / f["rel"])} for f in data["files"]]
    placed = place_package(repo, Downloaded(
        drive_folder=pkg.name, subject=subject, role=pkg.role, description=pkg.description,
        new_subject=is_new, preconverted=pkg.preconverted, files=files), 1, known_hashes(repo), settings)
    outside = [p for p in placed.written if not p.startswith(rel + "/")]
    if outside:
        raise NeedsOwner(f"placement wrote outside {rel}: {outside[:3]}", todo="check sources/ by hand")
    duplicates = sorted(p["path"] for p in placed.pages if p["duplicate_of"])
    _write(folder / PLACED, {"folder": rel, "written": sorted(placed.written), "duplicates": duplicates})
    out(f"elhelyezve: {rel} ({len(placed.written)} fájl, {len(duplicates)} már ismert oldal)")


def _remove_partial(local, repo: Path, rel: str) -> None:
    """A placement cut off halfway: its folder holds only tool-written copies of this package.
    Removed only while none of its files is in git (nobody has worked on it)."""
    if not safefs.exists(repo, rel):
        return
    tracked = local.git().out("ls-files", "--", rel).split()
    if tracked:
        raise NeedsOwner(f"{rel}: an interrupted placement whose files are already in git",
                         todo="check the folder by hand; the tool removes nothing that is in git")
    safefs.rmtree(repo, rel)


def _move(local, drive, package_id: str, listed: list, label: str, folder: Path, out) -> str:
    result = move_to_processed(drive, package_id, listed, local.ctx.student.drive_root)
    if result == "changed":
        # Changed on Drive after the download: download again next time, and replace the
        # placement (still outside git) with the new content.
        (folder / DOWNLOADED).unlink(missing_ok=True)
        (folder / PLACED).unlink(missing_ok=True)
        shutil.rmtree(folder / "files", ignore_errors=True)
        return "changed on Drive after the download; run sn fetch --apply again"
    out(f"Drive: {label} → Feldolgozva ({result})")
    shutil.rmtree(folder, ignore_errors=True)
    return result


def _pack(pkg: Package) -> dict:
    return {"id": pkg.id, "label": pkg.label, "listed": [list(e) for e in pkg.listed]}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
