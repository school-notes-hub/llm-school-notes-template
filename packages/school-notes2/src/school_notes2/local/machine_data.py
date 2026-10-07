"""The machine data `sn close` writes, never the writer: the lesson-log machine frontmatter
(`type`, `grade`, `sources`, `source_file`, the hashes, `drive_folder`, `generated`) of the pages
the hand-over's `adatok.json` `notes` names, from the source manifests; the `generated` stamp of
every other content page the pass changed; the page evidence records
`docs/evidence/pages/<subject>/<page>.md` from `checks`; `docs/figure-requests.json` from
`requests`; the draft tracking and the ⏳ notice; the banner and 📎 blocks; the reader-verdict
bookkeeping. `check` finds everything that would stop these writes, before any write."""

import hashlib
import json
from datetime import date
from pathlib import Path

import yaml

from ..evidence import records
from ..figures import insert, requests
from ..sources import manifest
from ..state import safefs
from ..wiki import banners, drafts, frontmatter, lesson_log, machine
from ..wiki.author import page_key
from ..wiki.pages import PageError, read_page, wiki_pages
from .common import today
from .handoff import Handoff, in_scope


def pass_id(h: Handoff) -> str:
    """The pass's identity: the hand-over's content and subject. Replaying the same hand-over is
    the same pass (any day, byte-identical); another hand-over is another pass."""
    digest = hashlib.sha256(json.dumps(h.data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return f"helyi-{digest}-{h.subject}"


def check(repo: Path, found: list[Handoff], pages: dict[str, dict], new_pages=(), subjects=None
          ) -> tuple[list[str], list | None]:
    """(problems, the new figure-requests value or None when nothing changes). `new_pages`: the
    wiki pages that are not in HEAD; a new lesson log must be in its subject's `notes`."""
    out = []
    noted = {note["file"] for h in found for note in h.data.get("notes", [])}
    for rel in sorted(new_pages):
        if rel.endswith("-jegyzet.md") and in_scope(rel, subjects) and rel not in noted and safefs.is_file(repo, rel):
            out.append(f"{rel}: a new lesson log that is in no adatok.json `notes` (its source pages are needed)")
    for h in found:
        for note in h.data.get("notes", []):
            if not in_scope(note["file"], [h.subject]) or not note["file"].endswith("-jegyzet.md"):
                out.append(f"{h.subject}: notes: {note['file']} is not a lesson log of the subject")
            elif not safefs.is_file(repo, note["file"]):
                out.append(f"{h.subject}: notes: {note['file']} does not exist")
            else:
                try:
                    frontmatter.split(safefs.read_text(repo, note["file"]))
                except (ValueError, yaml.YAMLError) as exc:
                    out.append(f"{h.subject}: notes: {note['file']}: unreadable frontmatter: {str(exc)[:120]}")
            out += [f"{h.subject}: notes: {note['file']}: {p} is in no source manifest (sn fetch)"
                    for p in note["pages"] if p not in pages]
        out += [f"{h.subject}: checks: {problem}" for problem in
                records.check_entries(repo, records.from_writer(h.data.get("checks", [])), pages)]
    incoming = [r for h in found for r in h.data.get("requests", [])]
    try:
        value = requests.collect(repo, incoming, list(pages.values()), subjects=subjects)
    except (ValueError, OSError) as exc:
        return out + [f"requests: {exc}"], None
    current = safefs.read_json(repo, requests.PATH, None) if safefs.is_file(repo, requests.PATH) else None
    return out, (value if value != (current or []) else None)


def write(local, repo: Path, found: list[Handoff], changed_pages: list[str], head_generated: dict,
          new_requests: list | None, at: str, changed: list[str], out) -> None:
    pages = manifest.pages(repo)
    for h in found:
        if not h.data:
            continue
        by = h.data["writer"]
        changed += machine.write_lesson_notes(repo, h.data.get("notes", []), pages, local.student.grade, by, at)
        mine = [p for p in changed_pages if in_scope(p, [h.subject])
                and (frontmatter_generated(repo, p) == head_generated.get(p))]
        changed += machine.stamp_generated(repo, mine, by, at)
        written = records.append(repo, records.from_writer(h.data.get("checks", [])),
                                 run_id=pass_id(h), checker=by, at=at, pages=pages)
        changed += written
    if new_requests is not None:
        safefs.write_json(repo, requests.PATH, new_requests)
        changed.append(requests.PATH)
    for r in requests.load(repo):
        out(f"képkérés a tulajdonosnak: {r['id']} ({r['page']}, {r['origin']}): {r['purpose']}")


def frontmatter_generated(repo: Path, rel: str):
    try:
        return frontmatter.split(safefs.read_text(repo, rel)).meta.get("generated")
    except (ValueError, OSError, yaml.YAMLError):
        return None


def draft_notices(repo: Path, changed: list[str], warnings: list[str], subjects=None) -> None:
    """The draft tracking and ⏳ notice of every page (`drafts.update`)."""
    try:
        linked = drafts.lesson_keys(repo)
    except (PageError, ValueError, OSError, yaml.YAMLError) as exc:
        warnings.append(f"vázlatkövetés kihagyva: {str(exc)[:160]}")
        return
    day = date.fromisoformat(today())
    for rel in sorted(wiki_pages(repo)):
        if not in_scope(rel, subjects):
            continue
        old = safefs.read_text(repo, rel)
        try:
            new = drafts.update(old, linked.get(rel, []), day)
        except (ValueError, yaml.YAMLError):
            continue                    # an unreadable page: the content check reports it
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)


def reader_bookkeeping(repo: Path) -> None:
    """A reader verdict of a changed page becomes history, one of a deleted page goes; figure
    verdicts are never touched here."""
    records_ = safefs.read_json(repo, insert.VERDICTS, [])
    kept, changed = [], False
    for r in records_:
        if r.get("role") in ("reader", "reader-history") and not safefs.is_file(repo, r["file"]):
            changed = True
            continue
        if r.get("role") == "reader" and page_key(repo, r["file"]) != r.get("key", ""):
            r, changed = {**r, "role": "reader-history"}, True
        kept.append(r)
    if changed:
        safefs.write_json(repo, insert.VERDICTS, kept)


def machine_blocks(repo: Path, changed: list[str], warnings: list[str], subjects=None) -> set[str]:
    """Banner and lesson-log source blocks of every page; an unreadable page is skipped
    (its problem stays for the content check)."""
    skipped = set()
    pages = manifest.pages(repo)
    for rel in sorted(wiki_pages(repo)):
        if not in_scope(rel, subjects):
            continue
        old = safefs.read_text(repo, rel)
        try:
            meta = read_page(repo, rel).meta
            new = banners.update(repo, rel, old)
            if lesson_log.is_lesson(rel, meta):
                new = lesson_log.after_header(new, lesson_log.BLOCK,
                                              lesson_log.source_line(meta, notebook=has_notebook(meta, pages)))
        except (ValueError, OSError, yaml.YAMLError) as exc:
            warnings.append(f"{rel}: gépi blokk kihagyva: {str(exc)[:160]}")
            skipped.add(rel)
            continue
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return skipped


def has_notebook(meta: dict, pages: dict[str, dict]) -> bool:
    """Is any source page of a lesson log a notebook page? A page in a source manifest says its
    role (`fuzet`); any other stored image counts as a notebook page; a `document.md` is a
    teacher's material. A page without recorded sources is shown as before (notebook)."""
    paths = machine.source_paths(meta)
    if not paths:
        return True
    for path in paths:
        role = pages.get(path, {}).get("role")
        if role == "fuzet" or (role is None and not path.endswith(".md")):
            return True
    return False
