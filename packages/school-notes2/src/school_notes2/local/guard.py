"""The writer guard: what changed in the working copy since HEAD that no writer may change.
Read-only; run by `sn done` and by `sn close` before it writes (a finding there is a STOP).

From `git diff HEAD` and the untracked files (ignored files are not looked at):

* a tracked file under `sources/` or `references/` changed or deleted; a new file there that no
  source manifest (`sn fetch`) and no tool record (`sn book`) names with its current bytes;
* a symlink, a non-regular file or a dotfile under `wiki/`;
* an existing `decisions` entry of a wiki page removed or changed (compared byte for byte; a
  new entry is the writer's, under the rules for answered questions);
* a machine frontmatter key or a generated block that is neither the HEAD version nor the
  tool's own last write (`tool_writes`); removing a whole generated block is the writer's choice;
* a new raster image link outside a generated block, or changed bytes of a committed raster
  image: a raster image goes in only through a commission and the reviewer's accept.

Each finding is one line: `<path>: <what>`, in path order."""

import posixpath
import stat
from pathlib import Path

from ..sources import manifest
from ..state import safefs
from ..wiki import frontmatter, markers
from ..wiki.machine import machine_keys
from ..wiki.pages import links, resolve
from . import tool_writes


def changes(git) -> tuple[dict[str, str], list[str]]:
    """({path: status M/A/D/T} against HEAD, untracked paths), both from git."""
    tracked = {}
    fields = git.out("diff", "--name-status", "--no-renames", "-z", "HEAD").split("\0")
    for status, path in zip(fields[0::2], fields[1::2]):
        if path:
            tracked[path] = status[:1]
    untracked = [p for p in git.out("ls-files", "--others", "--exclude-standard", "-z").split("\0") if p]
    return tracked, sorted(untracked)


def violations(repo: Path, git) -> list[str]:
    tracked, untracked = changes(git)

    def base(rel: str) -> str | None:
        proc = git.run("show", f"HEAD:{rel}", check=False)
        return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None

    record = tool_writes.load(repo)
    known = manifest.written(repo)
    out = []
    for rel, status in sorted(tracked.items()):
        if rel.startswith("sources/") or (rel.startswith("references/") and (
                status == "D" or record["files"].get(rel) != _sha(repo, rel))):
            out.append(f"{rel}: a committed source changed or was deleted ({status})")
    for rel in untracked:
        if rel.startswith("sources/") and rel not in known:
            out.append(f"{rel}: new file under sources/ that no source manifest names")
        elif rel.startswith("sources/") and known[rel] is not None and known[rel] != _sha(repo, rel):
            out.append(f"{rel}: differs from its source manifest")
        elif rel.startswith("references/") and record["files"].get(rel) != _sha(repo, rel):
            out.append(f"{rel}: new file under references/ that sn book did not write")
    for rel in sorted({*(r for r, s in tracked.items() if s != "D"), *untracked}):
        if not rel.startswith("wiki/"):
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
            out += _page(repo, rel, base(rel), record)
        elif rel.startswith("wiki/assets/") and not rel.endswith(".svg") and tracked.get(rel) == "M":
            out.append(f"{rel}: the bytes of a committed image changed (a replacement is a new file "
                       "with `replaces`)")
    return out


def _page(repo: Path, rel: str, old: str | None, record: dict) -> list[str]:
    text = safefs.read_text(repo, rel)
    out = []
    try:
        page, before = frontmatter.split(text), frontmatter.split(old) if old is not None else None
    except Exception:               # noqa: BLE001 - unreadable frontmatter: the page check reports it
        return []
    if before is not None:
        now_entries = _decision_entries(page)
        for entry in _decision_entries(before):
            if entry not in now_entries:
                out.append(f"{rel}: an existing `decisions` entry was removed or changed")
                break
    parts = tool_writes.machine_parts(text)
    if record["parts"].get(rel) != tool_writes.sha(parts):
        keys = sorted(set(machine_keys(page.meta) + (machine_keys(before.meta) if before else ())))
        now = {k: page.meta.get(k) for k in keys}
        was = {k: before.meta.get(k) for k in keys} if before else {k: None for k in keys}
        if now != was:
            out.append(f"{rel}: a machine frontmatter key was written by hand "
                       f"({', '.join(k for k in keys if now[k] != was[k])})")
        old_blocks = {n: markers.read(old, n) for n in markers.names(old)} if old is not None else {}
        for name in markers.names(text):
            if old_blocks.get(name, object()) != markers.read(text, name):
                out.append(f"{rel}: the generated block `{name}` was written by hand")
    out += _raster_links(rel, text, old)
    return out


def _decision_entries(page) -> list[str]:
    """The raw text of each `decisions` list item (byte comparison, no YAML round trip)."""
    chunk = next((c for key, c in frontmatter.blocks(page.raw_meta) if key == "decisions"), "") \
        if page.has_fm else ""
    items, current = [], None
    for line in chunk.splitlines()[1:]:
        if line.lstrip().startswith("- ") and (current is None or len(line) - len(line.lstrip()) <= current[0]):
            current = [len(line) - len(line.lstrip()), line]
            items.append(current)
        elif current is not None:
            current[1] += "\n" + line
    return [text.rstrip() for _, text in items]


def _raster_links(rel: str, text: str, old: str | None) -> list[str]:
    spans = [(text.count("\n", 0, start) + 1, text.count("\n", 0, end) + 1) for start, end, _ in markers.spans(text)]
    before = {resolve(rel, link.target) for link in links(old or "") if link.image}
    out = []
    for link in links(text):
        target = resolve(rel, link.target)
        if (not link.image or not target or not target.startswith("wiki/")
                or posixpath.splitext(target)[1].lower() == ".svg" or target in before):
            continue
        if any(start < link.line < end for start, end in spans):
            continue                    # inside a generated block: the tool's insertion
        out.append(f"{rel}: new raster image link {target} outside a figure block (a raster image "
                   "goes in through a commission and the reviewer's accept)")
    return out


def _sha(repo: Path, rel: str) -> str | None:
    return tool_writes.sha(safefs.read_bytes(repo, rel)) if safefs.is_file(repo, rel) else None
