"""`sn close <t> [--subject a,b] [--check]` (plan 3.2, 3.3/7–9): the controller's close of a
learner after the writer and review passes. Mechanical only; it never decides in anyone's name
and writes no `decisions` record (plan 3.3/16).

Reads the hand-over folders `.school-notes/out/<subject>/` (role texts `jegyzetiro.md`,
`lektor.md`): the writer's `figures.json` [{id, page, route, replaces}] and `ujranezes.json`
[{id, page, anchor, asset}], the reviewer's `verdicts.json` and `recheck.json` keyed by figure
id ({verdict, observed, defects, text_mismatch, relates_to, new_evidence?}; the key is computed
here from the page's current text). Steps, subjects in name order, figures in listed order:

1. generation receipts (this learner's outputs in the host image ledger);
2. authorship receipts for the accepted SVGs of the drawn route (run id `helyi-<date>-<subject>`);
3. each accepted figure inserted by `figures.insert.insert` (a figure without an accept is
   not inserted: the controller has removed its marker);
4. each accepted recheck renews the verdict key of an inserted figure (same image, new text);
5. the machine blocks of every page (`banners.update`, `lesson_log.after_header`);
6. **STOP** (exit 2, nothing deleted) while an inserted figure's verdict is invalidated and no
   recheck `accept` renewed it – the figure must be looked at against the new text;
7. verdict bookkeeping, subject and home indexes, decisions overview, `public.json`;
8. the content check of `sn done` (the worktree is naturally not clean after a close).

`--check` runs the same on a private copy of the working copy and lists what would change;
the working copy itself is not touched."""

import filecmp
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..figures import commissions, context as fctx, insert
from ..flows import generation_receipts
from ..reader import verdicts as reader_verdicts
from ..state import safefs
from ..wiki import banners, decisions, generate, lesson_log, markers, public
from ..wiki.pages import read_page, relative, wiki_pages
from ..wiki.rights import SVG_RECEIPTS
from . import done
from .common import now_iso, today

OUT = ".school-notes/out"
LEDGER = "docs/evidence/image-generation/ledger.json"
OPEN_LARGE = "[Az ábra megnyitása nagy méretben]"
END = "<!-- /school-notes:generated -->"
STOP = 2


@dataclass
class Handoff:
    subject: str
    figures: list[dict]
    verdicts: dict
    rechecks: list[dict]
    recheck_verdicts: dict


def _json(repo: Path, rel: str, default):
    return safefs.read_json(repo, rel, default) if safefs.is_file(repo, rel) else default


def handoffs(repo: Path, subjects: list[str] | None) -> list[Handoff]:
    found = sorted(safefs.listdir(repo, OUT)) if safefs.is_dir(repo, OUT) else []
    if subjects:
        missing = sorted(set(subjects) - set(found))
        if missing:
            raise SystemExit(f"nincs átadás ezekhez: {', '.join(missing)} ({OUT}/<tantárgy>/)")
        found = [s for s in found if s in subjects]
    out = []
    for subject in found:
        base = f"{OUT}/{subject}"
        if not safefs.is_dir(repo, base):
            continue
        out.append(Handoff(subject, _json(repo, f"{base}/figures.json", []), _json(repo, f"{base}/verdicts.json", {}),
                           _json(repo, f"{base}/ujranezes.json", []), _json(repo, f"{base}/recheck.json", {})))
    return out


def accepted(verdicts: dict, fid: str) -> dict | None:
    value = verdicts.get(fid)
    return value if isinstance(value, dict) and value.get("verdict") == "accept" else None


def figure_verdict(fid: str, key: str, given: dict) -> dict:
    """The reviewer's verdict in the figure-review schema, with the key computed now."""
    verdict = {"id": fid, "key": key, "verdict": "accept", "observed": given["observed"],
               "defects": given.get("defects", []), "text_mismatch": given.get("text_mismatch", []),
               "relates_to": given.get("relates_to")}
    if given.get("new_evidence"):
        verdict["new_evidence"] = given["new_evidence"]
    return verdict


def receipt(model: str, verdict: dict) -> dict:
    return {"status": "reviewed", "model": model, "review": {"figures": [verdict], "owner_notes": []}}


def _write_if_changed(repo: Path, rel: str, text: str, changed: list[str]) -> None:
    if not safefs.is_file(repo, rel) or safefs.read_text(repo, rel) != text:
        safefs.write_text(repo, rel, text)
        changed.append(rel)


def generation_ledger(local, repo: Path, changed: list[str]) -> None:
    hashes = generation_receipts.outputs(local.image_settings(repo))
    if hashes:
        _write_if_changed(repo, LEDGER, public.dumps({"rights": "generated", "outputs": hashes}), changed)


def svg_receipts(repo: Path, items: list[tuple[str, dict]], changed: list[str]) -> None:
    data = _json(repo, SVG_RECEIPTS, {"rights": "authored", "svgs": []})
    entries = {(e["path"], e["sha256"]): e for e in data.get("svgs", [])}
    for subject, fig in items:
        asset = commissions.candidate(repo, commissions.read(repo, fig["id"])).get("asset", "")
        if asset.endswith(".svg"):
            sha = hashlib.sha256(safefs.read_bytes(repo, asset)).hexdigest()
            entries.setdefault((asset, sha), {"path": asset, "sha256": sha, "run_id": f"helyi-{today()}-{subject}"})
    if entries:
        _write_if_changed(repo, SVG_RECEIPTS,
                          public.dumps({"rights": "authored", "svgs": [entries[k] for k in sorted(entries)]}), changed)


def insert_one(repo: Path, fig: dict, given: dict, model: str, at: str) -> bool:
    """Insert one accepted figure; False when it is already inserted."""
    fid = fig["id"]
    brief = commissions.read(repo, fid)
    if brief["page"] != fig["page"]:
        raise ValueError(f"{fid}: figures.json names {fig['page']}, the commission {brief['page']}")
    if markers.read(safefs.read_text(repo, brief["page"]), f"figure-{fid}") is not None:
        return False        # already inserted; a stale verdict of it is the STOP rule's case
    candidate = commissions.candidate(repo, brief)
    if brief.get("replaces"):
        old = relative(brief["page"], brief["replaces"])
        new = relative(brief["page"], candidate["asset"])
        text = safefs.read_text(repo, brief["page"])
        if f"{OPEN_LARGE}({old})" in text:
            safefs.write_text(repo, brief["page"], text.replace(f"{OPEN_LARGE}({old})", f"{OPEN_LARGE}(<{new}>)"))
    verdict = figure_verdict(fid, fctx.verdict_key(repo, brief, candidate), given)
    insert.insert(repo, brief, receipt(model, verdict), at=at)
    return True


def renew_one(repo: Path, fid: str, given: dict, model: str, at: str) -> bool:
    """A recheck accept: the inserted figure's verdict key is computed from the new text.
    The commission and candidate come from the figure's evidence; the image is unchanged."""
    evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json")
    brief, candidate = evidence["commission"], evidence["candidate"]
    if evidence["verdict"]["key"] == fctx.verdict_key(repo, brief, candidate):
        return False
    safefs.write_json(repo, f".school-notes/figures/{fid}.json", brief)
    safefs.write_json(repo, f".school-notes/figures/{fid}/figure.json", candidate)
    page, marker = brief["page"], f"<!-- figure: {fid} -->"
    # insert.insert checks a marker on the page; the inserted block stands for it, so a marker
    # is put right after the block for the call and taken away again.
    text = safefs.read_text(repo, page)
    start = text.index(f"<!-- school-notes:generated figure-{fid} -->")
    end = text.index(END, start) + len(END)
    safefs.write_text(repo, page, text[:end] + "\n\n" + marker + text[end:])
    try:
        verdict = figure_verdict(fid, fctx.verdict_key(repo, brief, candidate), given)
        insert.insert(repo, brief, receipt(model, verdict), at=at)
    finally:
        text = safefs.read_text(repo, page)
        safefs.write_text(repo, page, text.replace("\n\n" + marker, "", 1))
    return True


def machine_blocks(repo: Path, changed: list[str], warnings: list[str]) -> set[str]:
    """Banner and lesson-log source blocks of every page; an unreadable page is skipped
    (its problem stays for the content check)."""
    skipped = set()
    for rel in sorted(wiki_pages(repo)):
        old = safefs.read_text(repo, rel)
        try:
            meta = read_page(repo, rel).meta
            new = banners.update(repo, rel, old)
            if lesson_log.is_lesson(rel, meta):
                new = lesson_log.after_header(new, lesson_log.BLOCK, lesson_log.source_line(meta))
        except (ValueError, OSError, yaml.YAMLError) as exc:
            warnings.append(f"{rel}: gépi blokk kihagyva: {str(exc)[:160]}")
            skipped.add(rel)
            continue
        if new != old:
            safefs.write_text(repo, rel, new)
            changed.append(rel)
    return skipped


def close(local, repo: Path, subjects: list[str] | None, out=print) -> int:
    role, _ = local.cfg.role("reviewer")
    model, at = f"{role.model}/{role.effort}", now_iso()
    found = handoffs(repo, subjects)
    changed: list[str] = []
    warnings: list[str] = []
    inserting = [(h.subject, f) for h in found for f in h.figures if accepted(h.verdicts, f["id"])]
    for h in found:
        for f in h.figures:
            if not accepted(h.verdicts, f["id"]):
                out(f"nincs accept, nem illesztem be: {h.subject}/{f['id']}")
    generation_ledger(local, repo, changed)
    svg_receipts(repo, inserting, changed)
    for subject, fig in inserting:
        given = next(h.verdicts for h in found if h.subject == subject)[fig["id"]]
        if insert_one(repo, fig, given, model, at):
            out(f"beillesztve: {subject}/{fig['id']}")
    for h in found:
        for item in h.rechecks:
            given = accepted(h.recheck_verdicts, item["id"])
            if given and renew_one(repo, item["id"], given, model, at):
                out(f"ítélet megújítva (újranézés): {h.subject}/{item['id']}")
    skipped = machine_blocks(repo, changed, warnings)
    stale = insert.invalidated(repo)
    if stale:
        out("STOP: beillesztett ábra ítélete érvénytelenedett, és nincs rá újranézési accept "
            "(az ábrát az új szöveggel össze kell vetni; semmit nem töröltem):")
        for record in stale:
            out(f"  {record['file']}#{record['id']}")
        return STOP
    reader_verdicts.invalidate(repo)
    generate.write_indexes(repo)
    overview = decisions.overview(repo, skip=skipped)
    _write_if_changed(repo, decisions.OVERVIEW, overview, changed)
    public.write(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                     public.writer_svg_rights(repo)))
    for line in warnings:
        out(f"figyelmeztetés: {line}")
    return done.report(repo, out)


SKIP = (".git", ".venv", "node_modules")     # never read or written by a close


def private_copy(repo: Path, dest: Path) -> None:
    """A copy to close in: `sources/` and `references/` (never written by a close) as hard
    links, everything else (except `SKIP`) as real files."""
    dest.mkdir(parents=True)
    for entry in sorted(os.listdir(repo)):
        if entry in SKIP:
            continue
        src = repo / entry
        if entry in ("sources", "references") and src.is_dir():
            subprocess.run(["cp", "-al", str(src), str(dest / entry)], check=True)
        elif src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dest / entry, symlinks=True)
        else:
            shutil.copy2(src, dest / entry, follow_symlinks=False)


def differences(a: Path, b: Path) -> list[str]:
    """Paths (relative, sorted) that differ between two trees, `SKIP` left out."""
    def files(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if (p.is_file() or p.is_symlink()) and p.relative_to(root).parts[0] not in SKIP}

    def same(rel: str) -> bool:
        x, y = a / rel, b / rel
        if x.is_symlink() or y.is_symlink():
            return x.is_symlink() and y.is_symlink() and os.readlink(x) == os.readlink(y)
        return os.path.samefile(x, y) or filecmp.cmp(x, y)

    left, right = files(a), files(b)
    return sorted((left ^ right) | {p for p in left & right if not same(p)})


def run(local, subjects: list[str] | None, check: bool, out=print) -> int:
    if not check:
        code = close(local, local.repo, subjects, out)
        local.record("close", {0: "ok", 1: "open", STOP: "stop"}.get(code, "error"),
                     subjects=subjects or "all")
        return code
    with tempfile.TemporaryDirectory(prefix=f"sn-close-{local.name}-") as tmp:
        copy = Path(tmp) / "repo"
        private_copy(local.repo, copy)
        code = close(local, copy, subjects, out)
        changes = differences(local.repo, copy)
    out(f"--check: a lezárás {len(changes)} fájlt változtatna")
    for rel in changes:
        out(f"  {rel}")
    local.record("close", "checked", changed=len(changes), code=code)
    return code
