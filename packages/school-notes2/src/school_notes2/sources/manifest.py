"""The durable source manifest `sources/<subject>/<folder>/sn-fetch.json` (written by `sn fetch`
when it places a package, never changed afterwards).

It keeps what the download records knew and the repository would otherwise lose when the
download is deleted: per stored page its file, PDF page, Drive file id, `original_sha256` (the
uploaded file; `#p<n>` for a PDF page) and `content_sha256` (the stored image), the package's
Drive folder and role, and the SHA-256 of every file the tool wrote into the folder. The
duplicate check (`duplicates.known_hashes`), the lesson-log machine frontmatter (`sn close`) and
the writer guard read it."""

import json
from pathlib import Path

import yaml

from ..state import safefs

NAME = "sn-fetch.json"


def build(package: dict, pages: list[dict], drive_ids: dict[str, str], written: dict[str, str]) -> dict:
    """`package`: {drive_id, drive_folder, subject_name, role, description}; `pages`: the placed
    pages (`place.Placed.pages`); `drive_ids`: download file → Drive file id."""
    return {"package": package,
            "pages": [{"path": p["path"], "file": p["file"], "page": p["page"],
                       "drive_id": drive_ids.get(p["file"], ""),
                       "original_sha256": p["original_key"], "content_sha256": p["sha256"],
                       "duplicate_of": p["duplicate_of"]} for p in pages],
            "written": dict(sorted(written.items()))}


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def load_all(repo: Path) -> dict[str, dict]:
    """Every manifest under `sources/`, keyed by its repo path, in path order."""
    out = {}
    if not safefs.is_dir(repo, "sources"):
        return out
    for rel in sorted(safefs.glob(repo, "sources", f"sources/**/{NAME}")):
        try:
            out[rel] = json.loads(safefs.read_text(repo, rel))
        except (ValueError, UnicodeDecodeError, yaml.YAMLError):
            continue            # a broken manifest is the guard's finding, not a crash here
    return out


def pages(repo: Path) -> dict[str, dict]:
    """Every stored source page of every manifest by its repo path: {path, file, page, drive_id,
    sha256, original_sha256, package, role}."""
    out = {}
    for data in load_all(repo).values():
        package = data.get("package", {})
        for p in data.get("pages", []):
            if p.get("duplicate_of"):
                continue
            out[p["path"]] = {"path": p["path"], "file": p["file"], "page": p.get("page"),
                              "drive_id": p.get("drive_id", ""), "sha256": p["content_sha256"],
                              "original_sha256": p["original_sha256"],
                              "package": package.get("drive_folder", ""), "role": package.get("role", "")}
    return out


def written(repo: Path) -> dict[str, str]:
    """Every file a manifest says the tool wrote, with its SHA-256 (the manifests included)."""
    out = {}
    for rel, data in load_all(repo).items():
        out.update(data.get("written", {}))
        out[rel] = None             # the manifest itself: present is enough
    return out
