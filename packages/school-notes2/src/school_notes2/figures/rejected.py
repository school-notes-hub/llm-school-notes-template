"""Nightly figure defects enter the same writer queue as run-time figure defects."""

import hashlib

from ..state import safefs
from ..wiki import markers
from ..wiki.pages import links, resolve
from . import commissions, pending, migration_gate


def request(spec, brief, verdict, key):
    fid = "retry-" + hashlib.sha256((spec["id"] + key).encode()).hexdigest()[:32]
    brief = {**brief, "id": fid}
    if spec.get("asset"):
        brief.update(replaces=spec["asset"], decision_reason={
            "code": "c", "text": "A független ábraellenőr javítást kért."})
    defects = verdict["defects"] + verdict["text_mismatch"]
    if not defects:
        defects = [{"location": spec["id"], "observed": verdict["observed"], "expected": "Helyes ábra"}]
    if not brief["anchor"]:
        brief["anchor"] = "Fejléc"
    if not brief["avoid_misreading"]:
        brief["avoid_misreading"] = "\n".join(d["observed"] for d in defects)
    return {"spec": spec, "key": key, "commission": brief, "defects": defects}


def apply(repo, entries):
    if migration_gate.blocked(repo):
        return []
    from ..review import night_figures
    written = []
    for entry in sorted(entries, key=lambda e: e["commission"]["id"]):
        spec, brief = entry["spec"], entry["commission"]
        try:
            if night_figures.fingerprint(repo, spec) != entry["key"]:
                continue
        except (ValueError, OSError):
            continue
        page, fid = brief["page"], brief["id"]
        text = safefs.read_text(repo, page)
        if not any(m[1] == fid for m in commissions.MARKER.finditer(text)):
            if spec.get("asset"):
                link = next(l for l in links(text) if l.image and resolve(page, l.target) == spec["asset"])
                offset = sum(len(line) for line in text.splitlines(True)[:link.line - 1])
            else:
                offset = next(m.start() for m in commissions.MERMAID.finditer(text) if m[1] == spec["source"])
            offset = next((m.start() for m in markers.BLOCK.finditer(text) if m.start() <= offset < m.end()), offset)
            kind = "image" if brief["kind"] in ("banner", "infographic") else "figure"
            safefs.write_text(repo, page, text[:offset] + f"<!-- {kind}: {fid} -->\n\n" + text[offset:])
        # No writer attempt happened in a nightly review. Replays preserve counters.
        previous = next((e for e in pending.load(repo) if e["commission"]["id"] == fid), None)
        pending.record(repo, previous["commission"] if previous else brief, "nightly",
                       previous["defects"] if previous else entry["defects"], attempted=False)
        written += [page, pending.PATH, migration_gate.MARK]
    return sorted(set(written))
