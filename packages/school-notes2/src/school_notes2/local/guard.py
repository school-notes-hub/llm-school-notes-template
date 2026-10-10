"""The writer guard: what changed in the working copy since HEAD that no writer may change.
Read-only; run by `sn done` and by `sn close` before it writes (a finding there is a STOP).

From `git diff HEAD` (staged and unstaged) and the untracked files (ignored files are not
looked at):

* a committed file under `sources/` changed or deleted; a new file there (untracked or staged)
  that no source manifest (`sn fetch`) names with its current bytes; a manifest's file missing
  or changed; under `references/` a file `sn book` did not write (a book's `README.md` stays the
  writer's in the *textbook table* scope);
* a symlink, a non-regular file or a dotfile under `wiki/`;
* an existing `decisions` entry removed or changed (compared as parsed YAML, flow style too; a
  renamed page is compared with its old version, a deleted page's entries must stand on some
  page; a new entry is the writer's, under the rules for answered questions);
* a machine frontmatter key or a generated block that is neither the HEAD version nor the
  tool's own last write (`tool_writes`); of `sources` only the tool's package entries (pointing
  into `sources/`) count – a web or textbook entry is the writer's; removing a whole generated
  block is the writer's choice;
* a new raster image link outside a generated block, or changed bytes of a committed raster
  image: a raster image goes in only through a commission and the reviewer's accept;
* a podcast MP3 under `wiki/` or a podcast receipt under `docs/evidence/podcast/` (new, changed
  or deleted) that is not `sn podcast`'s last write (`tool_writes` files).

With `subjects` the `wiki/` part looks only at those subjects; the `sources/` part stays global.
Each finding is one line: `<path>: <what>`, in path order."""

import difflib
import posixpath
import stat
from pathlib import Path

import yaml

from ..sources import manifest
from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.machine import machine_keys
from ..wiki.pages import links, resolve, wiki_pages
from . import tool_writes

RASTER = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif")
PODCAST_RECEIPTS = "docs/evidence/podcast/"
INTERRUPTED = " (if an earlier `sn close` was interrupted, run it again: it records its own writes)"


def changes(git) -> tuple[dict[str, str], list[str]]:
    """({path: status M/A/D/T} against HEAD, untracked paths), both from git."""
    tracked = {}
    fields = git.out("diff", "--name-status", "--no-renames", "-z", "HEAD").split("\0")
    for status, path in zip(fields[0::2], fields[1::2]):
        if path:
            tracked[path] = status[:1]
    untracked = [p for p in git.out("ls-files", "--others", "--exclude-standard", "-z").split("\0") if p]
    return tracked, sorted(untracked)


def in_subjects(rel: str, subjects) -> bool:
    if not subjects:
        return True
    parts = rel.split("/")
    return len(parts) > 2 and parts[0] == "wiki" and (parts[1] in subjects or
                                                     (parts[1] == "assets" and parts[2] in subjects))


def violations(repo: Path, git, subjects=None) -> list[str]:
    tracked, untracked = changes(git)

    def base(rel: str) -> str | None:
        proc = git.run("show", f"HEAD:{rel}", check=False)
        return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None

    record = tool_writes.load(repo)
    known = manifest.written(repo)
    out = []
    added = {r for r, s in tracked.items() if s == "A"} | set(untracked)
    for rel, status in sorted(tracked.items()):
        if rel in added:
            continue
        if rel.startswith("sources/"):
            out.append(f"{rel}: a committed source changed or was deleted ({status})")
        elif rel.startswith("references/") and not _readme(rel) and (
                status == "D" or record["files"].get(rel) != _sha(repo, rel)):
            out.append(f"{rel}: a committed reference changed or was deleted ({status})")
    for rel in sorted(added):
        if rel.startswith("sources/") and rel not in known:
            out.append(f"{rel}: new file under sources/ that no source manifest names")
        elif rel.startswith("references/") and not _readme(rel) and record["files"].get(rel) != _sha(repo, rel):
            out.append(f"{rel}: new file under references/ that sn book did not write")
    for rel, sha in sorted(known.items()):
        if sha is not None and _sha(repo, rel) != sha:
            out.append(f"{rel}: a file of its source manifest is missing or changed")
    for rel in sorted({*tracked, *untracked}):
        if rel.startswith(PODCAST_RECEIPTS) and not _tool_file(record, repo, rel):
            out.append(f"{rel}: a podcast receipt only `sn podcast` writes ({tracked.get(rel, 'A')})")
    deleted = sorted(r for r, s in tracked.items() if s == "D" and r.startswith("wiki/") and r.endswith(".md"))
    present = sorted(r for r in {*(r for r, s in tracked.items() if s != "D"), *untracked} if r.startswith("wiki/"))
    renamed = _pairs(repo, deleted, [r for r in present if r in added and r.endswith(".md")], base)
    for rel in present:
        if not in_subjects(rel, subjects):
            continue
        if any(part.startswith(".") for part in rel.split("/")):
            out.append(f"{rel}: dotfile under wiki/")
            continue
        try:
            mode = safefs.mode(repo, rel)
        except safefs.UnsafePath:
            out.append(f"{rel}: symlink under wiki/")
            continue
        if mode is not None and not stat.S_ISREG(mode):
            out.append(f"{rel}: not a regular file under wiki/")
            continue
        if rel.endswith(".md"):
            out += _page(repo, rel, base(renamed.get(rel, rel)), record)
        elif _raster(rel) and tracked.get(rel) == "M":
            out.append(f"{rel}: the bytes of a committed image changed (a replacement is a new file "
                       "with `replaces`)")
        elif rel.lower().endswith(".mp3") and not _tool_file(record, repo, rel):
            out.append(f"{rel}: a podcast MP3 only `sn podcast` writes")
    moved = set(renamed.values())
    standing = None
    for rel in deleted:
        if rel in moved or not in_subjects(rel, subjects):
            continue
        lost = _decisions(base(rel))
        if lost:
            if standing is None:
                standing = [e for page in wiki_pages(repo) for e in _decisions(safefs.read_text(repo, page))]
            if any(e not in standing for e in lost):
                out.append(f"{rel}: the page was deleted with `decisions` entries that stand on no other page")
    return out


def _pairs(repo: Path, deleted: list[str], new: list[str], base) -> dict[str, str]:
    """{new path: old path} for pages renamed in the working copy (content pairing: the most
    similar deleted page, at least half the same), in path order."""
    out, free = {}, list(deleted)
    for rel in new:
        try:
            text = safefs.read_text(repo, rel)
        except (safefs.UnsafePath, OSError):
            continue                    # a link or a non-file: reported on its own
        scored = sorted(((difflib.SequenceMatcher(None, base(old) or "", text).ratio(), old) for old in free),
                        reverse=True)
        if scored and scored[0][0] >= 0.5:
            out[rel] = scored[0][1]
            free.remove(scored[0][1])
    return out


def _decisions(text: str | None) -> list:
    if text is None:
        return []
    try:
        value = frontmatter.split(text).meta.get("decisions") or []
    except (ValueError, yaml.YAMLError):
        return []
    return value if isinstance(value, list) else [value]


def tool_part(key: str, value):
    """The part of a machine key the tool owns: of `sources` the package entries only (their
    `resource` points into `sources/`); web and textbook entries are the writer's."""
    if key == "sources" and isinstance(value, list):
        return [e for e in value if isinstance(e, dict)
                and str(e.get("resource", "")).lstrip("./").startswith("sources/")]
    return value


def _page(repo: Path, rel: str, old: str | None, record: dict) -> list[str]:
    text = safefs.read_text(repo, rel)
    out = []
    try:
        page, before = frontmatter.split(text), frontmatter.split(old) if old is not None else None
    except Exception:               # noqa: BLE001 - unreadable frontmatter: the page check reports it
        return []
    if before is not None:
        now_entries = _decisions(text)
        if any(entry not in now_entries for entry in _decisions(old)):
            out.append(f"{rel}: an existing `decisions` entry was removed or changed")
    out += _machine(rel, text, page, old, before, record)
    out += _raster_links(rel, text, old)
    return out


def _machine(rel: str, text: str, page, old: str | None, before, record: dict) -> list[str]:
    """Machine frontmatter keys and generated blocks that are neither the HEAD's nor the tool's
    last write."""
    if record["parts"].get(rel) == tool_writes.sha(tool_writes.machine_parts(text)):
        return []
    keys, blocks = _differences(text, page, old, before)
    out = []
    if keys:
        out.append(f"{rel}: a machine frontmatter key was written by hand ({', '.join(keys)}){INTERRUPTED}")
    out += [f"{rel}: the generated block `{name}` was written by hand{INTERRUPTED}" for name in blocks]
    return out


def _differences(text: str, page, old: str | None, before) -> tuple[list[str], list[str]]:
    """(machine keys, generated blocks) of `text` that differ from `old` (the tool's part of a
    key; a block removed from `text` does not count)."""
    keys = sorted(set(machine_keys(page.meta) + (machine_keys(before.meta) if before else ())))
    now = {k: tool_part(k, page.meta.get(k)) for k in keys}
    was = {k: tool_part(k, before.meta.get(k)) for k in keys} if before else {k: None for k in keys}
    old_blocks = {n: markers.read(old, n) for n in markers.names(old)} if old is not None else {}
    return ([k for k in keys if now[k] != was[k]],
            [n for n in markers.names(text) if old_blocks.get(n, object()) != markers.read(text, n)])


def machine_differences(text: str, old: str | None) -> set[str] | None:
    """The machine parts of `text` that differ from `old` (`key <k>`, `block <name>`); None when
    a frontmatter is unreadable."""
    try:
        page, before = frontmatter.split(text), frontmatter.split(old) if old is not None else None
    except Exception:               # noqa: BLE001
        return None
    keys, blocks = _differences(text, page, old, before)
    return {f"key {k}" for k in keys} | {f"block {n}" for n in blocks}


def tool_written(repo: Path, git, rel: str, before: str, record: dict) -> bool:
    """`sn close --subject` asks this of a page outside the named subjects that the close changed
    (`before`: its text before the close): may the page be recorded as the tool's? Yes when the
    page was the tool's last write before (`record`), or when every machine part that differs
    from the HEAD now is one this close changed. A machine-part edit the close did not touch is
    not the tool's: no."""
    if record["parts"].get(rel) == tool_writes.sha(tool_writes.machine_parts(before)):
        return True
    proc = git.run("show", f"HEAD:{rel}", check=False)
    head = proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None
    after = safefs.read_text(repo, rel)
    now, changed = machine_differences(after, head), machine_differences(after, before)
    return now is not None and changed is not None and now <= changed


def _raster(rel: str) -> bool:
    return posixpath.splitext(rel)[1].lower() in RASTER


def _readme(rel: str) -> bool:
    """`references/<subject>/<book>/README.md`: the writer checks its table by hand."""
    return rel.count("/") == 3 and rel.endswith("/README.md")


def _raster_links(rel: str, text: str, old: str | None) -> list[str]:
    spans = [(text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 1) for start, end, _ in markers.spans(text)]
    before = {resolve(rel, link.target) for link in links(old or "") if link.image}
    out = []
    for link in links(text):
        target = resolve(rel, link.target)
        if not link.image or not target or not target.startswith("wiki/") or not _raster(target) or target in before:
            continue
        if any(start < link.line < end for start, end in spans):
            continue                    # inside a generated block: the tool's insertion
        out.append(f"{rel}: new raster image link {target} outside a figure block (a raster image "
                   "goes in through a commission and the reviewer's accept)")
    return out


def hand_edited_file(repo: Path, git, rel: str, record: dict | None = None) -> bool:
    """A tool-only file (a podcast receipt) that differs from the HEAD and is not the tool's last
    write – what the writer guard reports; a command that rewrites it stops on it."""
    if not safefs.is_file(repo, rel):
        return False
    record = record if record is not None else tool_writes.load(repo)
    if _tool_file(record, repo, rel):
        return False
    proc = git.run("show", f"HEAD:{rel}", check=False)
    return proc.returncode != 0 or proc.stdout != safefs.read_bytes(repo, rel)


def _tool_file(record: dict, repo: Path, rel: str) -> bool:
    """The file is exactly the tool's last write – or its deletion (recorded as null)."""
    return rel in record["files"] and record["files"][rel] == _sha(repo, rel)


def hand_edited(repo: Path, git, rel: str, record: dict | None = None) -> list[str]:
    """The machine parts of page `rel` that differ from the HEAD and are not the tool's last write
    (`key <k>`, `block <name>`; `frontmatter` when unreadable); [] for a missing page. A command
    that writes the page stops on these: recording its own write would make them look the tool's."""
    if not safefs.is_file(repo, rel):
        return []
    record = record if record is not None else tool_writes.load(repo)
    text = safefs.read_text(repo, rel)
    if record["parts"].get(rel) == tool_writes.sha(tool_writes.machine_parts(text)):
        return []
    proc = git.run("show", f"HEAD:{rel}", check=False)
    head = proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None
    found = machine_differences(text, head)
    return ["frontmatter"] if found is None else sorted(found)


def _sha(repo: Path, rel: str) -> str | None:
    return tool_writes.sha(safefs.read_bytes(repo, rel)) if safefs.is_file(repo, rel) else None
