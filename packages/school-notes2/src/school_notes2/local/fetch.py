"""`sn fetch <t> [--apply]` (plan 3.2, 3.3/1): the Drive inbox into the learner's working copy.

Without `--apply` it only lists: every package in the `Feltöltés_Kész` folders and every
leftover download. With `--apply`, package by package (one package's failure does not stop
the others; the exit code is 1 if any is not done):

1. download (size and MD5 verified) into `downloads/<t>/<package id>/files/`;
2. place it into the working copy: the target `sources/<subject>/<folder>/` is reserved first
   (created empty and claimed in the download folder's `placing.json`), the package is prepared
   in `.school-notes/fetch/<id>/` and renamed into the reserved folder in one step (a new
   subject gets its index skeleton; a doc-extract output nested in one subfolder is taken from
   that subfolder, `drive.inventory.wrapper`);
3. **only then** move the package folder on Drive to the subject's `Feldolgozva`, checked
   against the listing taken at download time (a package changed since is downloaded again,
   never moved unplaced);
4. delete the download.

No settle time: `Feltöltés_Kész` is filled by renaming, a package there is complete
(owner, 2026-10-06). The run can be repeated after any interruption: the marker files in the
download folder say where to go on. A placement is replaced only file by file as recorded in
`staged.json`, only while those files are unchanged and not in git; anything else in the
folder stops the package for the owner. Nothing is committed: the controller commits after
the review."""

import hashlib
import json
import os
import shutil
from pathlib import Path

from ..drive import inventory
from ..drive.download import download_package
from ..drive.inventory import Package
from ..drive.move import move_to_processed
from ..sources.duplicates import known_hashes
from ..sources.naming import slug, subject_key, unique_dir
from ..sources.place import Downloaded, Settings, place_package
from ..state import safefs
from ..state.errors import NeedsOwner, SnError

DOWNLOADED, PLACING, STAGED, PLACED = "download.json", "placing.json", "staged.json", "placed.json"
STAGE = ".school-notes/fetch"


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
    return packages, sorted(inv.summary()["ignored"], key=lambda i: (i["path"], i["reason"]))


def stage(folder: Path) -> str:
    """Where a download folder stands: downloading | downloaded | placing | placed | unknown.
    `unknown` is a folder without this command's markers (e.g. an older script's download)."""
    if (folder / PLACED).is_file():
        return "placed"
    if (folder / DOWNLOADED).is_file():
        return "placing" if (folder / PLACING).is_file() else "downloaded"
    if (folder / "files").is_dir() or (folder / PLACING).is_file() or not any(folder.iterdir()):
        return "downloading"
    return "unknown"


def leftovers(local) -> dict[str, str]:
    root = local.downloads()
    return {p.name: stage(p) for p in sorted(root.iterdir()) if p.is_dir()} if root.is_dir() else {}


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
        except (SnError, OSError, ValueError) as exc:
            result = f"{type(exc).__name__}: {exc}"
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
        return _move(local, drive, data["package"], folder, out)
    where = stage(folder) if folder.is_dir() else "downloading"
    if where == "unknown":
        _adopt(pkg, folder)             # an older script's complete download of this package, or STOP
        where = stage(folder)
    if where in ("downloaded", "placing", "placed"):
        saved = _read(folder / DOWNLOADED)["package"]["listed"]
        if saved != [list(e) for e in pkg.listed]:
            out(f"változott a Drive-on a letöltés óta, újra letöltöm: {pkg.label}")
            _drop_download(folder)
            where = "downloading"
    if where == "downloading":
        shutil.rmtree(folder / "files", ignore_errors=True)    # our own unfinished download
        try:
            files = download_package(drive, pkg, folder / "files", local.cfg.timeouts.download_package_s)
        except SnError:
            shutil.rmtree(folder / "files", ignore_errors=True)
            raise
        _write(folder / DOWNLOADED, {"package": _pack(pkg), "files": files})
        out(f"letöltve: {pkg.label} ({len(files)} fájl)")
    if stage(folder) != "placed":
        _place(local, repo, pkg, folder, out)
    return _move(local, drive, _read(folder / DOWNLOADED)["package"], folder, out)


def _adopt(pkg: Package, folder: Path) -> None:
    """A folder without markers is taken only if it holds exactly this package's files with
    Drive's sizes and MD5s (an older script's finished download); otherwise it is left alone."""
    found = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*") if p.is_file()}
    wanted = {f.rel: f for f in pkg.files}
    if set(found) != set(wanted) or any(
            found[rel].stat().st_size != f.size or _digest(found[rel], "md5") != f.md5
            for rel, f in wanted.items()):
        raise NeedsOwner(f"{folder} holds an older download that is not exactly this package",
                         todo="look at the folder; remove it by hand if it is not needed")
    records = []
    for rel in sorted(wanted):
        target = folder / "files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        found[rel].rename(target)
        f = wanted[rel]
        records.append({"drive_id": f.id, "rel": rel, "path": str(target), "size": f.size,
                        "md5": f.md5, "sha256": _digest(target, "sha256")})
    _write(folder / DOWNLOADED, {"package": _pack(pkg), "files": records})


def _place(local, repo: Path, pkg: Package, folder: Path, out) -> None:
    data = _read(folder / DOWNLOADED)
    version = hashlib.sha256(json.dumps(data["files"], sort_keys=True).encode()).hexdigest()
    claim = _read(folder / PLACING) if (folder / PLACING).is_file() else None
    if claim is None:
        subject, is_new = subject_key(pkg.subject_name, repo)
        if is_new:
            for path in new_subject(repo, subject, pkg.subject_name):
                out(f"új tantárgy: {path}")
        target = unique_dir(repo / "sources" / subject, slug(pkg.name), repo)
        rel = safefs.rel_of(repo, target)
        _unclaimed(local, rel, pkg.id)
        target.mkdir(parents=True)                      # reserved: no other package takes it
        claim = {"package": pkg.id, "folder": rel, "subject": subject, "new_subject": is_new}
        _write(folder / PLACING, claim)
    rel, target = claim["folder"], repo / claim["folder"]
    _unclaimed(local, rel, pkg.id)
    if target.is_dir() and any(target.iterdir()):
        if _ours(local, repo, rel, folder, version):
            _write(folder / PLACED, _read(folder / STAGED))
            return
    target.mkdir(parents=True, exist_ok=True)
    stage_root = repo / STAGE / pkg.id
    shutil.rmtree(stage_root, ignore_errors=True)       # our own private preparation folder
    stage_root.mkdir(parents=True)
    settings = Settings(local.cfg.sources.max_side_px, local.cfg.sources.jpeg_quality,
                        local.cfg.sources.pdf_dpi, local.ctx.tools_dir())
    files = [{**f, "path": str(folder / "files" / f["rel"])} for f in data["files"]]
    placed = place_package(stage_root, Downloaded(
        drive_folder=pkg.name, subject=claim["subject"], role=pkg.role, description=pkg.description,
        new_subject=claim["new_subject"], preconverted=pkg.preconverted, files=files), 1,
        known_hashes(repo), settings, folder=stage_root / rel)
    staged = stage_root / rel
    written = _tree(staged) if staged.is_dir() else {}
    outside = [p for p in placed.written if not p.startswith(rel + "/")]
    if outside:
        raise NeedsOwner(f"placement wrote outside {rel}: {outside[:3]}", todo="check sources/ by hand")
    record = {"package": pkg.id, "folder": rel, "download": version,
              "files": {f"{rel}/{k}": v for k, v in written.items()},
              "duplicates": sorted(p["path"] for p in placed.pages if p["duplicate_of"])}
    _write(folder / STAGED, record)
    os.rmdir(target)                                    # the empty reservation …
    if written:
        os.rename(staged, target)                       # … replaced by the package in one step
    shutil.rmtree(stage_root, ignore_errors=True)
    _write(folder / PLACED, record)
    out(f"elhelyezve: {rel} ({len(written)} fájl, {len(record['duplicates'])} már ismert oldal)")


def _ours(local, repo: Path, rel: str, folder: Path, version: str) -> bool:
    """The reserved folder is not empty. True: it holds exactly this download's placement.
    An earlier download's placement (the package changed on Drive) is removed file by file
    when every file is unchanged and not in git, so it can be placed again (False). Anything
    else – a file this package did not write, a changed or committed file – stops it."""
    staged = _read(folder / STAGED) if (folder / STAGED).is_file() else None
    current = {f"{rel}/{k}": v for k, v in _tree(repo / rel).items()}
    if not staged or current != staged["files"]:
        raise NeedsOwner(f"{rel} holds files this package did not place, or they changed",
                         todo="look at the folder; the tool removes nothing it cannot prove its own")
    if staged["download"] == version:
        return True
    if local.git().out("ls-files", "--", rel).split():
        raise NeedsOwner(f"{rel}: the package changed on Drive, but its earlier placement is in git",
                         todo="decide by hand which version of the source stays")
    for path in sorted(staged["files"]):
        safefs.unlink(repo, path)
    for sub in sorted((p for p in (repo / rel).rglob("*") if p.is_dir()), reverse=True):
        sub.rmdir()
    (folder / STAGED).unlink()
    return False


def _unclaimed(local, rel: str, package_id: str) -> None:
    """No other download in progress has reserved the same folder."""
    root = local.downloads()
    for other in sorted(root.glob(f"*/{PLACING}")) if root.is_dir() else []:
        claim = _read(other)
        if claim["folder"] == rel and claim["package"] != package_id:
            raise NeedsOwner(f"{rel} is reserved by package {claim['package']}",
                             todo="finish that package first (sn fetch --apply)")


def _drop_download(folder: Path) -> None:
    """Forget the download (not the reservation and the placement record)."""
    shutil.rmtree(folder / "files", ignore_errors=True)
    for name in (DOWNLOADED, PLACED):
        (folder / name).unlink(missing_ok=True)


def _move(local, drive, saved: dict, folder: Path, out) -> str:
    """The move checks Drive against the listing of the download (`saved`), never a newer one."""
    result = move_to_processed(drive, saved["id"], saved["listed"], local.ctx.student.drive_root)
    if result == "changed":
        _drop_download(folder)          # next run: download again, replace the placement
        return "changed on Drive after the download; run sn fetch --apply again"
    out(f"Drive: {saved['label']} → Feldolgozva ({result})")
    shutil.rmtree(folder, ignore_errors=True)
    return result


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _digest(p, "sha256")
            for p in sorted(root.rglob("*")) if p.is_file() or p.is_symlink()}


def _digest(path: Path, name: str) -> str:
    h = hashlib.new(name)
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _pack(pkg: Package) -> dict:
    return {"id": pkg.id, "label": pkg.label, "listed": [list(e) for e in pkg.listed]}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
