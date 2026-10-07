"""Machine-written wiki data: lesson-notes frontmatter, `generated` stamps, the subjects.json
entry and the index skeleton of a new subject.

The writer decides which source pages belong to which lesson-notes page (the hand-over's
`adatok.json` `notes[].pages`); everything derivable from that and from the source manifests
(`sources/**/sn-fetch.json`) is written by `sn close`, never by the writer.
"""

import json
import posixpath
from pathlib import Path

from ..state import safefs
from . import frontmatter, generate, markers

LESSON_KEYS = ("type", "grade", "sources", "source_file", "content_sha256", "original_sha256",
               "drive_folder", "generated")
LESSONS_LEGEND = ("A legújabb óra van legfelül. A `~` bizonytalan dátumot jelöl; az időszakot az "
                  "egér rávitelekor vagy koppintásra látod.")


def machine_keys(meta: dict) -> tuple[str, ...]:
    """Keys only the tool may write on a page of this kind (the path guard cuts these)."""
    keys = LESSON_KEYS if meta.get("type") == "lesson-notes" else ("generated",)
    return keys + ("draft_tracking",)


def _folder(path: str) -> str:
    return posixpath.dirname(path)


def source_entries(note_file: str, used: list[dict], folders: list[str]) -> list[dict]:
    """One footnote source per package folder; its id is the folder name."""
    up = posixpath.relpath(".", posixpath.dirname(note_file))
    entries = []
    for folder in folders:
        first = next(p for p in used if _folder(p["path"]) == folder)
        entries.append({"id": posixpath.basename(folder),
                        "resource": posixpath.join(up, first["path"]), "title": first["package"]})
    return entries


def lesson_values(note_file: str, used: list[dict], grade, by: str, at: str, old: dict | None = None) -> dict:
    """The machine keys of one lesson-notes page from the source pages it was written from
    (`used`: manifest pages `{path, sha256, original_sha256, package}`, in source order).

    `old` is the page's current frontmatter: a continued lesson keeps the hashes, folders and
    Drive folders of its earlier pages (union), so duplicates of those pages are still recognised."""
    old = old or {}
    content = _full_paths(old, "content_sha256") | {p["path"]: p["sha256"] for p in used}
    original = _full_paths(old, "original_sha256") | {p["path"]: p["original_sha256"] for p in used}
    folders = list(dict.fromkeys(_old_folders(old) + [_folder(p["path"]) for p in used]))
    base = folders[0] if len(folders) == 1 else posixpath.commonpath(folders)
    drive = list(dict.fromkeys(_as_list(old.get("drive_folder")) + [p["package"] for p in used]))
    return {
        "type": "lesson-notes", "grade": grade,
        "sources": source_entries(note_file, used, list(dict.fromkeys(_folder(p["path"]) for p in used))),
        "source_file": _one_or_list([f.removeprefix("sources/") + "/" for f in folders]),
        "content_sha256": {posixpath.relpath(k, base): v for k, v in sorted(content.items())},
        "original_sha256": {posixpath.relpath(k, base): v for k, v in sorted(original.items())},
        "drive_folder": _one_or_list(drive),
        "generated": {"by": by, "at": at},
    }


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _one_or_list(values: list):
    return values[0] if len(values) == 1 else values


def _source_path(value: str) -> str:
    """A `source_file` value as a repo path: v2 `<subject>/<folder>/`, v1 `sources/<folder>/<file>`."""
    value = value.strip()
    return value if value.startswith("sources/") else "sources/" + value


def _is_file(path: str) -> bool:
    return bool(posixpath.splitext(path.rstrip("/"))[1]) and not path.endswith("/")


def _old_folders(old: dict) -> list[str]:
    """The earlier source folders, repo-relative (`sources/...`): from `source_file` (a v2
    folder, or a v1 file path whose folder counts) and from v1 `source_files[].file`."""
    paths = [_source_path(f) for f in _as_list(old.get("source_file"))]
    paths += [_source_path(str(e["file"])) for e in old.get("source_files") or [] if isinstance(e, dict) and e.get("file")]
    return list(dict.fromkeys((posixpath.dirname(p) if _is_file(p) else p.rstrip("/")) for p in paths))


def _full_paths(old: dict, key: str) -> dict[str, str]:
    """An earlier hash map with repo-relative keys. v2: a map relative to `source_file`. v1: a
    single hash string (the first source file's) and `source_files: [{file, sha256}]` (content)."""
    value = old.get(key)
    folders = _old_folders(old)
    out = {}
    if isinstance(value, dict) and folders:
        base = folders[0] if len(folders) == 1 else posixpath.commonpath(folders)
        out = {posixpath.normpath(posixpath.join(base, str(k))): str(v) for k, v in value.items()}
    elif isinstance(value, str) and value.strip():
        files = [_source_path(f) for f in _as_list(old.get("source_file")) if _is_file(_source_path(f))]
        if files:
            out[files[0]] = value.strip()
    if key == "content_sha256":
        for entry in old.get("source_files") or []:
            if isinstance(entry, dict) and entry.get("file") and entry.get("sha256"):
                out.setdefault(_source_path(str(entry["file"])), str(entry["sha256"]))
    return out


def source_paths(meta: dict) -> list[str]:
    """The repo paths of a lesson page's source pages (from its hash map), in natural order."""
    from ..sources.order import ordered
    return ordered(_full_paths(meta, "content_sha256"))


def merge_sources(old: list | None, new: list) -> list:
    """Package entries are the tool's; other entries (e.g. a cited textbook) are kept."""
    ids = {s["id"] for s in new}
    return new + [s for s in old or [] if isinstance(s, dict) and s.get("id") not in ids]


def write_lesson_notes(repo: Path, notes: list[dict], pages: dict[str, dict], grade, by: str,
                       at: str) -> list[str]:
    """Machine keys on every lesson-notes page of the pass (`notes`: `{file, pages}` with source
    page paths, looked up in `pages`); returns the changed paths."""
    changed = []
    for note in notes:
        text = safefs.read_text(repo, note["file"])
        meta = frontmatter.split(text).meta
        old = meta if meta.get("type") == "lesson-notes" else None
        values = lesson_values(note["file"], [pages[p] for p in note["pages"]], grade, by, at, old=old)
        values["sources"] = merge_sources(meta.get("sources"), values["sources"])
        if old is not None and all(old.get(k) == values[k] for k in values if k != "generated"):
            continue                    # a repeated close does not move the stamp
        new = frontmatter.set_keys(text, values)
        if new != text:
            safefs.write_text(repo, note["file"], new)
            changed.append(note["file"])
    return changed


def stamp_generated(repo: Path, paths: list[str], by: str, at: str) -> list[str]:
    """`generated: {by, at}` on the given content pages (not indexes, not the log). The caller
    passes only pages not stamped since the last commit, so a repeated close is a no-op."""
    changed = []
    for rel in sorted(paths):
        name = posixpath.basename(rel)
        if not rel.startswith("wiki/") or not rel.endswith(".md") or name in ("index.md", "log.md"):
            continue
        if rel.startswith("wiki/assets/") or not safefs.is_file(repo, rel):
            continue
        text = safefs.read_text(repo, rel)
        new = frontmatter.set_keys(text, {"generated": {"by": by, "at": at}})
        if new != text:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return changed


def add_subject(repo: Path, slug: str, name: str) -> bool:
    """A new subject's `tools/subjects.json` entry with its Drive name; never overwrites. Its
    emoji and colours are the writer's proposal, applied by the controller."""
    data = generate.load_subjects_json(repo)
    subjects = data.setdefault("subjects", {})
    if slug in subjects:
        return False
    subjects[slug] = {"name": name}
    safefs.write_text(repo, "tools/subjects.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return True


def subject_skeleton(name: str, banner_id: str) -> str:
    """wiki/<subject>/index.md for a new subject: hand-written frame, empty generated blocks."""
    head = frontmatter.set_keys("", {"description": generate.subject_sentence(name),
                                     "chapters": []})
    return (head + f"\n# {name}\n\n<!-- image: {banner_id} -->\n\n"
            "[⬅️ Vissza a kezdőlapra](../index.md)\n\n<br />\n\n"
            + markers.wrap("chapters", "")
            + "\n<br />\n\n# 🗓️ Órák\n\n" + LESSONS_LEGEND + "\n\n"
            + markers.wrap("lessons", generate.TABLE_HEAD)
            + "\n<br />\n\n" + markers.wrap("review", "") + markers.wrap("notes", ""))


def create_subject(repo: Path, slug: str, name: str, banner_id: str) -> str | None:
    """Write the skeleton if the subject index does not exist yet; returns its path."""
    rel = f"wiki/{slug}/index.md"
    if safefs.exists(repo, rel):
        return None
    safefs.write_text(repo, rel, subject_skeleton(name, banner_id))
    return rel
