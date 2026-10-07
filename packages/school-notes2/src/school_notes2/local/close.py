"""`sn close <t> [--subject a,b] [--check | --snapshot [--only id,…]]` (plan 3.2, 3.3/7–9):
the controller's close of a learner after the writer and review passes. Mechanical only; it
never decides in anyone's name, writes no `decisions` record (plan 3.3/16) and deletes no
figure verdict.

Hand-over folders `.school-notes/out/<subject>/` (role texts `jegyzetiro.md`, `lektor.md`):
the writer's `figures.json` [{id, page, route, replaces}] and `ujranezes.json`
[{id, page, anchor, asset}]; the reviewer's `verdicts.json` and `recheck.json` keyed by figure
id ({verdict, observed, defects, text_mismatch, relates_to, new_evidence?}); and two files the
controller makes with `--snapshot` (below): `keys.json` and `diff.patch`.

**`--snapshot`** (before the reviewer starts, and with `--only <ids>` before the confirmation
pass, for the figures to confirm): writes `keys.json` – for each figure of `figures.json` and
`ujranezes.json` the verdict key of the content as it is now (image, alt, caption, section
text) – and `diff.patch` (the subject's `git diff` against HEAD with its new files; the
reviewer has no shell). An `accept` is valid only for the content it was given: `sn close`
inserts or renews a figure only while its current key equals the key in `keys.json`.

**Close**, subjects in name order, figures in listed order:

0. **STOP** (exit 2) before writing anything, listing every case: an accept whose content
   changed since the snapshot (or has no snapshot); a `replaces` in `figures.json` that differs
   from the commission's; an inserted figure that disappeared from its page (its verdict
   stays; the controller brings it to the owner);
1. generation receipts (this learner's outputs in the host image ledger);
2. authorship receipts for the accepted SVGs of the drawn route (run id `helyi-<date>-<subject>`);
3. each accepted figure inserted by `figures.insert.insert` (a figure without an accept is
   not inserted: the controller has removed its marker); verifier: the owner's fixed reviewer;
4. each accepted recheck renews the verdict of an inserted figure, once, for the content seen;
5. the machine blocks of every page (`banners.update`, `lesson_log.after_header`);
6. **STOP** (exit 2, nothing deleted) while an inserted figure's verdict is invalidated – the
   figure must be looked at against the new text;
7. reader-verdict bookkeeping (figure verdicts untouched), indexes, decisions overview,
   `public.json`;
8. the content check of `sn done` for the whole learner (the worktree is naturally not clean).

With `--subject` the STOP checks look only at the named subjects (a stalled subject does not
block the others); `sn done` and `sn publish` stay strict for the whole learner. `--check`
runs the same on a private copy and lists what would change; the working copy is untouched."""

import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..figures import commissions, context as fctx, insert
from ..figures.review import is_error
from ..schemas import validate
from ..state import safefs
from ..wiki import banners, decisions, generate, lesson_log, markers, public
from ..wiki.author import page_key
from ..wiki.pages import read_page, relative, wiki_pages
from ..wiki.rights import SVG_RECEIPTS
from . import done
from .common import Refused, now_iso, today

OUT = ".school-notes/out"
LEDGER = "docs/evidence/image-generation/ledger.json"
OPEN_LARGE = "[Az ábra megnyitása nagy méretben]"
END = "<!-- /school-notes:generated -->"
STOP = 2
REVIEWER = "claude-opus-5-5/high"     # the owner's fixed reviewer (plan 0/2): Claude Opus 5.5, high


@dataclass
class Handoff:
    subject: str
    figures: list[dict]
    verdicts: dict
    rechecks: list[dict]
    recheck_verdicts: dict
    keys: dict


def _json(repo: Path, rel: str, default):
    return safefs.read_json(repo, rel, default) if safefs.is_file(repo, rel) else default


def handoffs(repo: Path, subjects: list[str] | None) -> list[Handoff]:
    found = sorted(safefs.listdir(repo, OUT)) if safefs.is_dir(repo, OUT) else []
    if subjects:
        missing = sorted(set(subjects) - set(found))
        if missing:
            raise Refused(f"nincs átadás ezekhez: {', '.join(missing)} ({OUT}/<tantárgy>/)")
        found = [s for s in found if s in subjects]
    out = []
    for subject in found:
        base = f"{OUT}/{subject}"
        if not safefs.is_dir(repo, base):
            continue
        out.append(Handoff(subject, _json(repo, f"{base}/figures.json", []), _json(repo, f"{base}/verdicts.json", {}),
                           _json(repo, f"{base}/ujranezes.json", []), _json(repo, f"{base}/recheck.json", {}),
                           _json(repo, f"{base}/keys.json", {})))
    return out


def in_scope(page: str, subjects: list[str] | None) -> bool:
    parts = page.split("/")
    return not subjects or (len(parts) > 2 and parts[0] == "wiki" and parts[1] in subjects)


def accepted(verdicts: dict, fid: str) -> dict | None:
    value = verdicts.get(fid)
    return value if isinstance(value, dict) and value.get("verdict") == "accept" else None


def figure_verdict(fid: str, key: str, given: dict) -> dict:
    """The reviewer's verdict in the figure-review schema, with the key of the reviewed content."""
    verdict = {"id": fid, "key": key, "verdict": "accept", "observed": given["observed"],
               "defects": given.get("defects", []), "text_mismatch": given.get("text_mismatch", []),
               "relates_to": given.get("relates_to")}
    if given.get("new_evidence"):
        verdict["new_evidence"] = given["new_evidence"]
    return verdict


def receipt(verdict: dict) -> dict:
    return {"status": "reviewed", "model": REVIEWER, "review": {"figures": [verdict], "owner_notes": []}}


def _write_if_changed(repo: Path, rel: str, text: str, changed: list[str]) -> None:
    if not safefs.is_file(repo, rel) or safefs.read_text(repo, rel) != text:
        safefs.write_text(repo, rel, text)
        changed.append(rel)


def generation_outputs(settings) -> list[str]:
    """The sha256 of every image (and preview) the host ledger records for this learner."""
    return sorted({a[key] for entry in settings.ledger()["jobs"].values()
                   if entry["learner"] == settings.learner
                   for a in entry["attempts"] if a.get("state") in ("generated", "accepted", "rejected")
                   for key in ("sha256", "preview_sha256") if a.get(key)})


def generation_ledger(local, repo: Path, changed: list[str]) -> None:
    hashes = generation_outputs(local.image_settings(repo))
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


def new_key(repo: Path, fid: str) -> str:
    """The current key of a figure not inserted yet (commission, candidate, marker)."""
    brief = commissions.read(repo, fid)
    return fctx.verdict_key(repo, brief, commissions.candidate(repo, brief))


def inserted_key(repo: Path, fid: str) -> tuple[dict, str]:
    """(evidence, current key) of an inserted figure, from its evidence record."""
    evidence = safefs.read_json(repo, f"docs/evidence/media/{fid}/figure.json")
    return evidence, fctx.verdict_key(repo, evidence["commission"], evidence["candidate"])


def is_inserted(repo: Path, page: str, fid: str) -> bool:
    return markers.read(safefs.read_text(repo, page), f"figure-{fid}") is not None


def recorded_key(repo: Path, fid: str, page: str) -> str | None:
    return next((r.get("key") for r in safefs.read_json(repo, insert.VERDICTS, [])
                 if r.get("role") == "figure-review" and r.get("id") == fid and r.get("file") == page), None)


def blockers(repo: Path, found: list[Handoff], subjects: list[str] | None) -> list[str]:
    """Everything that stops the close before it writes (step 0)."""
    out = []
    for h in found:
        for fig in h.figures:
            fid = fig["id"]
            if not accepted(h.verdicts, fid):
                continue
            brief = commissions.read(repo, fid)
            if (fig.get("replaces") or None) != (brief.get("replaces") or None):
                out.append(f"{h.subject}/{fid}: a figures.json replaces mezője ({fig.get('replaces')}) "
                           f"eltér a megbízásétól ({brief.get('replaces')})")
            if brief["page"] != fig["page"]:
                out.append(f"{h.subject}/{fid}: a figures.json lapja ({fig['page']}) eltér a megbízásétól ({brief['page']})")
            if is_inserted(repo, brief["page"], fid):
                continue
            if h.keys.get(fid) != new_key(repo, fid):
                out.append(f"{h.subject}/{fid}: az accept nem erre a változatra szól (változott a lektor "
                           "pillanatképe óta, vagy nincs pillanatkép) – megerősítés kell")
        for item in h.rechecks:
            fid = item["id"]
            if not accepted(h.recheck_verdicts, fid):
                continue
            _, current = inserted_key(repo, fid)
            if recorded_key(repo, fid, item["page"]) == current:
                continue                                    # renewed already, nothing changed since
            if h.keys.get(fid) != current:
                out.append(f"{h.subject}/{fid}: az újranézési accept nem erre a szövegre szól – megerősítés kell")
    for record in safefs.read_json(repo, insert.VERDICTS, []):
        if (record.get("role") == "figure-review" and not record.get("night_spec")
                and in_scope(record["file"], subjects) and insert.removed(repo, record)):
            out.append(f"{record['file']}#{record['id']}: beillesztett ábra eltűnt a lapról "
                       "(az ítélete megmarad; a tulajdonos dönt)")
    return out


def insert_one(repo: Path, fig: dict, given: dict, key: str, at: str) -> bool:
    """Insert one accepted figure with the reviewed key; False when it is already inserted."""
    fid = fig["id"]
    brief = commissions.read(repo, fid)
    if is_inserted(repo, brief["page"], fid):
        return False        # already inserted; a stale verdict of it is the STOP rule's case
    candidate = commissions.candidate(repo, brief)
    if brief.get("replaces"):
        old = relative(brief["page"], brief["replaces"])
        new = relative(brief["page"], candidate["asset"])
        text = safefs.read_text(repo, brief["page"])
        if f"{OPEN_LARGE}({old})" in text:
            safefs.write_text(repo, brief["page"], text.replace(f"{OPEN_LARGE}({old})", f"{OPEN_LARGE}(<{new}>)"))
    insert.insert(repo, brief, receipt(figure_verdict(fid, key, given)), at=at)
    return True


def renew_one(repo: Path, fid: str, page: str, given: dict, key: str, at: str) -> bool:
    """A recheck accept renews the verdict of an inserted figure for the content the reviewer
    saw (`key`, equal to the current key): the evidence record first, `verdicts.json` last, so an
    interrupted renewal is simply done again. The page is not written."""
    _drop_old_marker(repo, page, fid)
    evidence, current = inserted_key(repo, fid)
    if recorded_key(repo, fid, page) == current:
        return False
    if key != current:
        raise ValueError(f"{fid}: the recheck was given other content")
    verdict = figure_verdict(fid, key, given)
    validate("figure-review", {"figures": [verdict], "owner_notes": []})
    if any(is_error(d) for d in verdict["defects"] + verdict["text_mismatch"]):
        raise ValueError(f"{fid}: an accept cannot contain a hiba")
    safefs.write_json(repo, f"docs/evidence/media/{fid}/figure.json",
                      {**evidence, "verdict": verdict, "verifier": REVIEWER, "at": at})
    insert._record_verdict(repo, evidence["commission"], evidence["candidate"], verdict, REVIEWER, at)
    return True


def _drop_old_marker(repo: Path, page: str, fid: str) -> None:
    """sn 0.1.0 put a temporary `<!-- figure: id -->` right after the inserted block during a
    renewal; an interrupted run could leave it there. Removed when found in exactly that place."""
    text = safefs.read_text(repo, page)
    pattern = re.compile(r"(<!-- school-notes:generated figure-" + re.escape(fid) + r" -->.*?"
                         + re.escape(END) + r")\n\n<!-- figure: " + re.escape(fid) + r" -->", re.S)
    fixed = pattern.sub(r"\1", text)
    if fixed != text:
        safefs.write_text(repo, page, fixed)


def reader_bookkeeping(repo: Path) -> None:
    """`reader.verdicts.invalidate` without its figure part: a reader verdict of a changed page
    becomes history, one of a deleted page goes; figure verdicts are never touched here."""
    records = safefs.read_json(repo, insert.VERDICTS, [])
    kept, changed = [], False
    for r in records:
        if r.get("role") in ("reader", "reader-history") and not safefs.is_file(repo, r["file"]):
            changed = True
            continue
        if r.get("role") == "reader" and page_key(repo, r["file"]) != r.get("key", ""):
            r, changed = {**r, "role": "reader-history"}, True
        kept.append(r)
    if changed:
        safefs.write_json(repo, insert.VERDICTS, kept)


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
    at = now_iso()
    found = handoffs(repo, subjects)
    stops = blockers(repo, found, subjects)
    if stops:
        out("STOP (nem írtam semmit):")
        for line in stops:
            out(f"  {line}")
        return STOP
    changed: list[str] = []
    warnings: list[str] = []
    inserting = [(h, f) for h in found for f in h.figures if accepted(h.verdicts, f["id"])]
    for h in found:
        for f in h.figures:
            if not accepted(h.verdicts, f["id"]):
                out(f"nincs accept, nem illesztem be: {h.subject}/{f['id']}")
    generation_ledger(local, repo, changed)
    svg_receipts(repo, [(h.subject, f) for h, f in inserting], changed)
    for h, fig in inserting:
        if insert_one(repo, fig, h.verdicts[fig["id"]], h.keys.get(fig["id"], ""), at):
            out(f"beillesztve: {h.subject}/{fig['id']}")
    for h in found:
        for item in h.rechecks:
            given = accepted(h.recheck_verdicts, item["id"])
            if given and renew_one(repo, item["id"], item["page"], given, h.keys.get(item["id"], ""), at):
                out(f"ítélet megújítva (újranézés): {h.subject}/{item['id']}")
    skipped = machine_blocks(repo, changed, warnings)
    stale = [r for r in insert.invalidated(repo) if in_scope(r["file"], subjects)]
    if stale:
        out("STOP: beillesztett ábra ítélete érvénytelenedett, és nincs rá érvényes újranézési accept "
            "(az ábrát az új szöveggel össze kell vetni; semmit nem töröltem):")
        for record in stale:
            out(f"  {record['file']}#{record['id']}")
        return STOP
    reader_bookkeeping(repo)
    generate.write_indexes(repo)
    overview = decisions.overview(repo, skip=skipped)
    _write_if_changed(repo, decisions.OVERVIEW, overview, changed)
    public.write(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                     public.writer_svg_rights(repo)))
    for line in warnings:
        out(f"figyelmeztetés: {line}")
    return done.report(repo, out)


def snapshot(local, subjects: list[str] | None, only: list[str] | None, out=print) -> int:
    """`--snapshot`: keys.json and diff.patch for the reviewer (see the module text)."""
    repo = local.repo
    found = handoffs(repo, subjects)
    if not found:
        raise Refused(f"nincs átadás ({OUT}/<tantárgy>/)")
    problems = []
    for h in found:
        keys = dict(h.keys) if only else {}
        wanted = [(f["id"], False) for f in h.figures] + [(r["id"], True) for r in h.rechecks]
        for fid, inserted in wanted:
            if only and fid not in only:
                continue
            try:
                keys[fid] = inserted_key(repo, fid)[1] if inserted else new_key(repo, fid)
            except (ValueError, OSError, KeyError) as exc:
                problems.append(f"{h.subject}/{fid}: {exc}")
        base = f"{OUT}/{h.subject}"
        safefs.write_text(repo, f"{base}/keys.json", json.dumps(dict(sorted(keys.items())), indent=1) + "\n")
        safefs.write_text(repo, f"{base}/diff.patch", diff_patch(local, h.subject))
        out(f"pillanatkép: {base}/keys.json ({len(keys)} ábra), {base}/diff.patch")
    for line in problems:
        out(f"  nem számolható: {line}")
    local.record("close", "snapshot", subjects=[h.subject for h in found], only=only or "all")
    return 1 if problems else 0


def diff_patch(local, subject: str) -> str:
    """The subject's changes against HEAD (text pages, assets, its evidence) with new files."""
    paths = [f"wiki/{subject}", f"wiki/assets/{subject}", f":(glob)docs/evidence/**/*{subject}*"]
    git = local.git()
    text = git.out("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", *paths, check=False)
    for rel in sorted(git.out("ls-files", "--others", "--exclude-standard", "--", *paths).splitlines()):
        text += git.out("diff", "--no-ext-diff", "--no-index", "--", "/dev/null", rel, check=False)
    return text


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


def run(local, subjects: list[str] | None, check: bool = False, out=print, *,
        snapshot_only: list[str] | None = None, take_snapshot: bool = False) -> int:
    if take_snapshot:
        return snapshot(local, subjects, snapshot_only, out)
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
