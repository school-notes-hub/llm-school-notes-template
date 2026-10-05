"""Restore only tool-owned bytes, from recorded originals, without editing prose."""

import hashlib
from pathlib import Path

import yaml

from ..state import safefs
from ..wiki import frontmatter, guard, markers
from ..wiki.machine import machine_keys


def remember(task, repo, paths):
    saved = dict(task.get("tool_originals", {}))
    for path in sorted(set(paths)):
        if safefs.is_file(repo, path):
            data = safefs.read_bytes(repo, path)
            digest = hashlib.sha256(data).hexdigest()
            rel = "tool-originals/" + digest
            safefs.write_bytes(task.dir, rel, data)
            saved[path] = str(task.dir / rel)
    return saved


def original(ctx, task, path):
    saved = task.get("tool_originals", {}).get(path)
    if saved and Path(saved).is_file():
        return Path(saved).read_bytes()
    # Pre-upgrade tasks already have a durable before tree. Prefer it to Git
    # only if it proves the tool's latest write, not an older generation.
    expected = task.get("tool_writes", {}).get(path)
    parts = task.get("tool_parts", {}).get(path)
    roots = [Path(task.get("correction_before"))] if task.get("correction_before") else []
    for root in roots:
        if safefs.is_file(root, path):
            data = safefs.read_bytes(root, path)
            if not expected and not parts or expected == hashlib.sha256(data).hexdigest() or (
                    parts and parts == guard.parts_hash(data.decode("utf-8", "replace"))):
                return data
    from . import steps
    return steps.base_reader(ctx, task)(path)


def restore(ctx, task):
    from . import steps
    if safefs.exists(ctx.notes_path, ".git"):
        paths = steps.changed_paths(ctx, task)
    else:
        roots = [Path(task.get("correction_before"))] if task.get("correction_before") else []
        paths = sorted(set(task.get("tool_originals", {})) | {
            p for root in roots for p in safefs.walk_files(root)})
    restored = []
    for path in sorted(paths):
        if path.startswith(".school-notes/") or path in task.get("conflict_files", []) or (
                task.get("learning_pending") or {}).get("path") == path:
            continue
        whole = path in task.get("tool_writes", {}) or not (
            path.startswith("wiki/") or task.mode == "interactive" and (
                path.startswith("references/") or path == "docs/licenses.json"))
        if not whole and not path.endswith(".md"):
            continue
        current = safefs.read_bytes(ctx.notes_path, path) if safefs.is_file(ctx.notes_path, path) else None
        if current is not None:
            expected = task.get("tool_writes" if whole else "tool_parts", {}).get(path)
            actual = hashlib.sha256(current).hexdigest() if whole else guard.parts_hash(current.decode("utf-8", "replace"))
            if expected and actual == expected and (whole or task.mode == "interactive" or
                                                    not _decisions_changed(current, steps.base_reader(ctx, task)(path))):
                continue
        old = original(ctx, task, path)
        fixed = old if whole else restore_parts(current, old)
        if not whole and task.mode != "interactive" and fixed is not None:
            # Cron never changes an owner decision: the base's `decisions` come back (#13).
            fixed = restore_decisions(fixed, steps.base_reader(ctx, task)(path))
        if fixed != current:
            if fixed is None:
                safefs.unlink(ctx.notes_path, path)
            else:
                safefs.write_bytes(ctx.notes_path, path, fixed)
            restored.append(path)
    if restored:
        ctx.log.event("writer.protected_restored", pages=restored)
    return restored


def restore_parts(current, old):
    if current is None:  # A removed page is a writer check error; do not undo it.
        return current
    try:
        text = current.decode("utf-8")
        source = (old or b"").decode("utf-8")
        markers.check(text)
        previous, page = frontmatter.split(source), frontmatter.split(text)
    except (ValueError, yaml.YAMLError):
        return current  # Ambiguous boundaries require the writer, never guessing.
    keys = set(machine_keys(previous.meta)) | set(machine_keys(page.meta))
    originals = {k: chunk for k, chunk in frontmatter.blocks(previous.raw_meta) if k in keys}
    chunks, seen = [], set()
    for key, chunk in frontmatter.blocks(page.raw_meta) if page.has_fm else []:
        if key not in keys:
            chunks.append(chunk)
        elif key in originals:
            chunks.append(originals[key])
            seen.add(key)
    chunks += [chunk for k, chunk in originals.items() if k not in seen]
    if any(previous.meta.get(k) != page.meta.get(k) for k in keys):
        text = "---\n" + "\n".join(chunks) + "\n---\n" + page.body
    # A block keeps the writer's position; only its bytes come back. A removed block is
    # not re-placed by the tool (its position is author text): the guard asks the writer.
    blocks = {m['name']: m[0] for m in markers.BLOCK.finditer(source)}
    text = markers.BLOCK.sub(lambda match: blocks.get(match['name'], ""), text)
    return text.encode()


def _decisions_changed(current, base):
    from ..wiki import decisions
    try:
        return decisions.snapshot(current) != decisions.snapshot(base)
    except (ValueError, UnicodeError, yaml.YAMLError):
        return False  # The guard reports unreadable frontmatter.


def restore_decisions(current, base):
    """Put the base's `decisions` frontmatter chunk back, byte for byte."""
    if current is None or not _decisions_changed(current, base):
        return current
    try:
        page = frontmatter.split(current.decode("utf-8"))
        old = frontmatter.split((base or b"").decode("utf-8"))
    except (ValueError, UnicodeError, yaml.YAMLError):
        return current
    original = dict(frontmatter.blocks(old.raw_meta)) if old.has_fm else {}
    chunks = [original["decisions"] if key == "decisions" and "decisions" in original else chunk
              for key, chunk in (frontmatter.blocks(page.raw_meta) if page.has_fm else [])
              if key != "decisions" or "decisions" in original]
    if "decisions" in original and not any(key == "decisions" for key, _ in frontmatter.blocks(page.raw_meta)):
        chunks.append(original["decisions"])
    return ("---\n" + "\n".join(chunks) + "\n---\n" + page.body).encode()
