"""Find ready packages under a learner's Drive root (plan 4.1, 5.2/1).

Layout: <root>/{Füzet,Tanári-tanulni}/<Tantárgy>/Feltöltés_Kész/<package folder>/...
Every package folder there is ready: the owner fills `Feltöltés_Kész` by renaming (an atomic
move), so there is no settle time.
"""

import unicodedata
from dataclasses import dataclass, field

from .client import FOLDER, DriveClient

ROLES = {"Füzet": "fuzet", "Tanári-tanulni": "tanari"}
READY, PROCESSED = "Feltöltés_Kész", "Feldolgozva"
IMAGES = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp")   # phones save .webp too
PDF = ".pdf"
DOCUMENT = "document.md"
OFFICE = (".pptx", ".ppt", ".docx", ".doc")


@dataclass
class DriveFile:
    id: str
    rel: str            # path inside the package, "/"-separated
    size: int
    md5: str
    mime: str

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    def as_item(self) -> dict:
        return {"id": self.id, "name": self.name, "size": str(self.size), "md5Checksum": self.md5}


@dataclass
class Package:
    id: str
    name: str
    subject_name: str
    role: str
    description: str
    ready_folder_id: str    # its parent, Feltöltés_Kész
    subject_folder_id: str
    preconverted: bool
    files: list[DriveFile] = field(default_factory=list)      # to download
    ignored: list[dict] = field(default_factory=list)         # {"path", "reason"}
    listed: list[list] = field(default_factory=list)           # snapshot of everything listed

    @property
    def label(self) -> str:
        return f"{self.role}/{self.subject_name}/{self.name}"


@dataclass
class Inventory:
    ready: list[Package] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)

    def skipped(self) -> list[dict]:
        """Every file not taken, the ones inside a package with the package's label, in path order."""
        return sorted(self.ignored + [dict(i, path=f"{p.label}/{i['path']}") for p in self.ready for i in p.ignored],
                      key=lambda i: (i["path"], i["reason"]))


def nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def segment(name: str) -> str:
    """A Drive name as one safe path segment: Drive allows "/" in names, the disk does not."""
    clean = nfc(name).replace("/", "_").replace("\0", "_")
    return "_" if clean in ("", ".", "..") else clean


def child_folder(client: DriveClient, parent_id: str, name: str) -> dict | None:
    for item in client.list_children(parent_id):
        if item["mimeType"] == FOLDER and nfc(item["name"]) == nfc(name):
            return item
    return None


def walk(client: DriveClient, folder_id: str, prefix: str = "") -> list[tuple[str, dict]]:
    """Every item below a folder as (relative path, metadata), folders included."""
    out = []
    for item in client.list_children(folder_id):
        rel = f"{prefix}{segment(item['name'])}"
        out.append((rel, item))
        if item["mimeType"] == FOLDER:
            out += walk(client, item["id"], rel + "/")
    return out


def order(pkg: Package) -> tuple:
    """A total, content-derived order (not Drive's upload times)."""
    return (pkg.role, pkg.subject_name, pkg.name, pkg.id)


def scan(client: DriveClient, root_id: str) -> Inventory:
    inv = Inventory()
    for top_name, role in ROLES.items():
        top = child_folder(client, root_id, top_name)
        if top is None:
            continue
        for subject in client.list_children(top["id"]):
            if subject["mimeType"] != FOLDER:
                continue
            ready = child_folder(client, subject["id"], READY)
            if ready is not None:
                _scan_ready(client, inv, ready["id"], subject, role)
    inv.ready.sort(key=order)
    inv.ignored.sort(key=lambda i: (i["path"], i["reason"]))
    return inv


def _scan_ready(client, inv, ready_id, subject, role) -> None:
    where = f"{role}/{nfc(subject['name'])}/{READY}"
    for item in client.list_children(ready_id):
        if item["mimeType"] != FOLDER:
            inv.ignored.append({"path": f"{where}/{nfc(item['name'])}",
                                "reason": "loose file outside a package folder"})
            continue
        pkg = build_package(client, item, subject, role, ready_id)
        if not pkg.files:
            inv.ignored.append({"path": f"{where}/{pkg.name}", "reason": "no usable file"})
            inv.ignored += [dict(i, path=f"{where}/{pkg.name}/{i['path']}") for i in pkg.ignored]
        else:
            inv.ready.append(pkg)


def build_package(client: DriveClient, folder: dict, subject: dict, role: str,
                  ready_id: str) -> Package:
    items = walk(client, folder["id"])
    names = {rel for rel, i in items if i["mimeType"] != FOLDER}
    prefix = wrapper(names)
    pkg = Package(id=folder["id"], name=nfc(folder["name"]), subject_name=nfc(subject["name"]),
                  role=role, description=folder.get("description", "") or "",
                  ready_folder_id=ready_id, subject_folder_id=subject["id"],
                  preconverted=DOCUMENT in names or bool(prefix))
    for rel, item in items:
        if item["mimeType"] == FOLDER:
            continue
        pkg.listed.append(snapshot_entry(rel, item))
        reason = rejection(rel, item, pkg.preconverted)
        if reason:
            pkg.ignored.append({"path": rel, "reason": reason})
        else:
            pkg.files.append(DriveFile(item["id"], rel[len(prefix):], int(item.get("size", 0)),
                                       item.get("md5Checksum", ""), item["mimeType"]))
    pkg.listed.sort()
    _refuse_duplicate_names(pkg)
    pkg.files.sort(key=lambda f: (f.rel, f.id))
    return pkg


def wrapper(names: set[str]) -> str:
    """The owner's doc-extract layout may nest the output in one subfolder
    (`<package>/<subfolder>/document.md`, manifest, provenance, figures): that subfolder's
    prefix, so its files are taken with paths relative to it; "" for any other layout. The
    snapshot (`listed`) keeps the full paths, so the move compares what is really on Drive."""
    tops = {name.split("/", 1)[0] for name in names}
    if len(tops) != 1 or not all("/" in name for name in names):
        return ""
    top = tops.pop()
    return f"{top}/" if f"{top}/{DOCUMENT}" in names else ""


def _refuse_duplicate_names(pkg: Package) -> None:
    """Drive allows two files with one name; their order would be Drive's choice, so such a
    package is not taken until a file is renamed (the order must be fixed, plan 4.3)."""
    seen: dict[str, int] = {}
    for f in pkg.files:
        seen[f.rel] = seen.get(f.rel, 0) + 1
    clashes = sorted(rel for rel, n in seen.items() if n > 1)
    if clashes:
        pkg.ignored += [{"path": rel, "reason": "two files with the same name; rename one on "
                                                 "Drive"} for rel in clashes]
        pkg.files = []


def snapshot_entry(rel: str, item: dict) -> list:
    return [item["id"], rel, str(item.get("size", "")), item.get("md5Checksum", "")]


def rejection(rel: str, item: dict, preconverted: bool) -> str:
    """Why a file is not taken, or "" when it is."""
    if item["mimeType"].startswith("application/vnd.google-apps."):
        return "Google-native document (cannot be downloaded as a file)"
    if not item.get("md5Checksum"):
        return "no checksum on Drive"
    if preconverted:
        return ""       # a doc-extract package is copied unchanged (plan 4.2)
    lower = rel.lower()
    if lower.endswith(OFFICE):
        return "teacher pptx/docx: convert it with doc-extract first"
    if lower.endswith(IMAGES) or lower.endswith(PDF):
        return ""
    return "unsupported format"
