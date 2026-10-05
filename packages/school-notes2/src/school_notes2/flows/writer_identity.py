"""Content-bound writer output identity, retained across checks and finish retries."""

import hashlib
import json

from ..state import safefs


def remember(ctx, task, k, result, *, previously_counted=False):
    from .steps import _llm_hash
    digest = hashlib.sha256(json.dumps([task.get("writer_invocation", 0), k, result], sort_keys=True, ensure_ascii=False).encode())
    for prefix in ("wiki", "docs", "publication", "tools", ".school-notes/figures"):
        for path in sorted(safefs.walk_files(ctx.notes_path, prefix)):
            digest.update(path.encode() + b"\0")
            digest.update(_llm_hash(path, safefs.read_bytes(ctx.notes_path, path)).encode())
    key = digest.hexdigest()
    fields = {"writer_output_key": key}
    if previously_counted:
        fields["counted_bad_outputs"] = sorted(set(task.get("counted_bad_outputs", [])) | {key})
    task.update(**fields)


def ensure(ctx, task):
    if task.get("writer_output_key"):
        return
    results = [(k, safefs.read_json(task.dir, f"result-{k}.json"))
               for k in range(1, len(task.get("ranges", [])) + 1)]
    found = [(k, result) for k, result in results if result is not None]
    if found:
        # Pre-upgrade tasks have a counted error but no output receipt. Reusing
        # their saved results is not evidence of another writer failure.
        counted = bool(task.data["llm_failures"] and (task.data.get("last_error") or {}).get("class") == "bad_work")
        remember(ctx, task, found[-1][0], found, previously_counted=counted)
