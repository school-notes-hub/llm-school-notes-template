"""Machine-written wiki data (plan 4.9, 5.2, 5.4/3): lesson-notes frontmatter,
`generated` stamps, subjects.json entries and the new-subject index skeleton.

The LLM decides which pages belong to which lesson-notes page (`result.notes[].pages`);
everything derivable from that and from fetch.json is written here, never by the LLM.
"""

import json
import posixpath
from pathlib import Path

from ..state import safefs
from ..sources.duplicates import original_key
from . import frontmatter, generate, markers

LESSON_KEYS = ("type", "grade", "sources", "source_file", "content_sha256", "original_sha256",
               "drive_folder", "generated")
LESSONS_LEGEND = ("A legújabb óra van legfelül. A `?` dátum azt jelenti, hogy a füzetben nincs "
                  "dátum; ilyenkor a zárójel azt az időszakot adja meg, amelybe az óra esik.")


def machine_keys(meta: dict) -> tuple[str, ...]:
    """Keys only the tool may write on a page of this kind (the path guard cuts these)."""
    keys = LESSON_KEYS if meta.get("type") == "lesson-notes" else ("generated",)
    return keys + ("draft_tracking",)


def _folder(path: str) -> str:
    return posixpath.dirname(path)


def _original(page: dict) -> str:
    """original_sha256 value in the one format the duplicate check reads (4.2)."""
    return original_key(page.get("original_sha256", ""), page.get("page"))


def source_entries(note_file: str, used: list[dict], folders: list[str]) -> list[dict]:
    """One footnote source per package folder; its id is the folder name (fetch.json shows it)."""
    up = posixpath.relpath(".", posixpath.dirname(note_file))
    entries = []
    for folder in folders:
        first = next(p for p in used if _folder(p["path"]) == folder)
        entries.append({"id": posixpath.basename(folder),
                        "resource": posixpath.join(up, first["path"]), "title": first["package"]})
    return entries


def lesson_values(note_file: str, seqs: list[int], fetch: dict, grade, by: str, at: str,
                  old: dict | None = None) -> dict:
    """The machine keys of one lesson-notes page, from the pages it was written from.

    `old` is the page's current frontmatter: a page extended by a later run keeps the
    hashes, folders and Drive folders of its earlier pages (union), so duplicates of the
    earlier pages are still recognised."""
    pages = {p["seq"]: p for p in fetch["pages"]}
    used = [pages[s] for s in sorted(set(seqs)) if s in pages]
    old = old or {}
    content = _full_paths(old, "content_sha256") | {p["path"]: p["sha256"] for p in used}
    original = _full_paths(old, "original_sha256") | {p["path"]: _original(p) for p in used}
    folders = list(dict.fromkeys(_old_folders(old) + [_folder(p["path"]) for p in used]))
    base = folders[0] if len(folders) == 1 else posixpath.commonpath(folders)
    drive = list(dict.fromkeys(_as_list(old.get("drive_folder")) + [p["package"] for p in used]))
    source_file = [f.removeprefix("sources/") + "/" for f in folders]
    return {
        "type": "lesson-notes", "grade": grade,
        "sources": source_entries(note_file, used, list(dict.fromkeys(_folder(p["path"])
                                                                       for p in used))),
        "source_file": _one_or_list(source_file),
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


def _old_folders(old: dict) -> list[str]:
    """The earlier source folders, repo-relative (`sources/...`), from `source_file`."""
    return [("sources/" + f).rstrip("/") for f in _as_list(old.get("source_file"))]


def _full_paths(old: dict, key: str) -> dict[str, str]:
    """An earlier hash map with repo-relative keys (its keys are relative to source_file)."""
    value = old.get(key)
    folders = _old_folders(old)
    if not isinstance(value, dict) or not folders:
        return {}
    base = folders[0] if len(folders) == 1 else posixpath.commonpath(folders)
    return {posixpath.normpath(posixpath.join(base, str(k))): str(v) for k, v in value.items()}


def merge_sources(old: list | None, new: list) -> list:
    """Package entries are the tool's; other entries (e.g. a cited textbook) are kept."""
    ids = {s["id"] for s in new}
    return new + [s for s in old or [] if isinstance(s, dict) and s.get("id") not in ids]


def write_lesson_notes(repo: Path, notes: list[dict], fetch: dict, grade, by: str,
                       at: str) -> list[str]:
    """Apply machine keys to every lesson-notes page of the run; returns changed paths."""
    changed = []
    for note in notes:
        text = safefs.read_text(repo, note["file"])
        meta = frontmatter.split(text).meta
        values = lesson_values(note["file"], note["pages"], fetch, grade, by, at,
                               old=meta if meta.get("type") == "lesson-notes" else None)
        values["sources"] = merge_sources(meta.get("sources"), values["sources"])
        new = frontmatter.set_keys(text, values)
        if new != text:
            safefs.write_text(repo, note["file"], new)
            changed.append(note["file"])
    return changed


def stamp_generated(repo: Path, paths: list[str], by: str, at: str) -> list[str]:
    """`generated: {by, at}` on every modified content page (not indexes, not the log)."""
    changed = []
    for rel in paths:
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


def light_tint(color: str, amount: float = 0.8) -> str:
    """The pale companion colour of subjects.json (`light`), mixed toward white."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * amount):02x}" for c in rgb)


def add_subjects(repo: Path, new_subjects: list[dict], names: dict[str, str]) -> bool:
    """Add the LLM's emoji/colour choice for subjects new in this run; never overwrite."""
    data = generate.load_subjects_json(repo)
    subjects = data.setdefault("subjects", {})
    added = False
    for item in new_subjects:
        slug = item["subject"]
        if slug in subjects:
            continue
        subjects[slug] = {"name": names.get(slug, slug), "emoji": item["emoji"],
                          "dark": item["color"].lower(), "light": light_tint(item["color"])}
        added = True
    if added:
        safefs.write_text(repo, "tools/subjects.json",
                          json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return added


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
