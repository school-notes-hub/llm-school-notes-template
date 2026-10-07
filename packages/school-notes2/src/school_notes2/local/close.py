"""`sn close <t> [--subject a,b] [--check | --snapshot [--only id,…]]` (plan 3.2, 3.3/7–9):
the controller's close of a learner after the writer and review passes. Mechanical only; it
never decides in anyone's name, writes no `decisions` record (plan 3.3/16) and deletes no
figure verdict. The hand-over it reads is described in `handoff.py`.

**`--snapshot`** (before the reviewer starts, and with `--only <ids>` before the confirmation
pass, for the figures to confirm): the candidate preflight of every handed-over figure first (a
problem is a STOP, exit 2, nothing written); then `keys.json` – for each figure of
`figures.json` and `ujranezes.json` the verdict key of the content as it is now (image, alt,
caption, section text) – and `diff.patch` (the subject's `git diff` against HEAD with its new
files; the reviewer has no shell). An `accept` is valid only for the content it was given:
`sn close` inserts or renews a figure only while its current key equals the key in `keys.json`.

**Close**, subjects in name order, figures in listed order:

0. **STOP** (exit 2) before writing anything, listing every case: a writer-guard finding
   (`guard.py`); a preflight problem of an accepted figure; an accept whose content changed
   since the snapshot (or has no snapshot); a `replaces` in `figures.json` that differs from the
   commission's; an inserted figure that disappeared from its page (its verdict stays; the
   controller brings it to the owner); an `adatok.json` entry that cannot be written (a lesson
   page that is not there, a source page in no manifest, a check image that does not exist, a
   figure request without its marker or with a reused id);
1. generation receipts (this learner's outputs in the host image ledger);
2. authorship receipts for the accepted SVGs of the drawn route (run id `helyi-<date>-<subject>`);
3. each accepted figure inserted by `figures.insert.insert`; verifier: the owner's fixed reviewer;
4. each accepted recheck renews the verdict of an inserted figure, once, for the content seen;
5. the machine data (`machine_data.py`): lesson-log machine frontmatter, `generated` stamps,
   page evidence records, `docs/figure-requests.json` (each request is listed for the owner),
   draft tracking and the ⏳ notice, the banner and 📎 blocks of every page;
6. **STOP** (exit 2, nothing deleted) while an inserted figure's verdict is invalidated – the
   figure must be looked at against the new text;
7. reader-verdict bookkeeping (figure verdicts untouched), indexes, decisions overview,
   `public.json`, the tool-writes record the writer guard reads;
8. the content check of `sn done` for the whole learner (the worktree is naturally not clean).

With `--subject` the STOP checks look only at the named subjects (a stalled subject does not
block the others); `sn done` and `sn publish` stay strict for the whole learner. `--check`
runs the same on a private copy and lists what would change; the working copy is untouched."""

import filecmp
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..figures import insert
from ..sources import manifest
from ..state import safefs
from ..wiki import decisions, generate, public
from . import done, figure_close as figs, guard, machine_data, tool_writes
from .common import Refused, now_iso
from .handoff import OUT, accepted, handoffs, in_scope

STOP = 2
REVIEWER = figs.REVIEWER


def stop(out, title: str, lines: list[str]) -> int:
    out(title)
    for line in lines:
        out(f"  {line}")
    return STOP


def close(local, repo: Path, subjects: list[str] | None, out=print) -> int:
    at = now_iso()
    git = local.git()
    found = handoffs(repo, subjects)
    pages = manifest.pages(repo)
    tracked, untracked = guard.changes(git)
    current = {*(r for r, s in tracked.items() if s != "D"), *untracked}
    changed_pages = sorted(p for p in current if p.startswith("wiki/") and p.endswith(".md"))
    new_pages = [p for p in changed_pages if p in untracked or tracked.get(p) == "A"]
    stops = [f"író-őr: {v}" for v in guard.violations(repo, git, subjects)]
    inserting = [(h, f) for h in found for f in h.figures if accepted(h.verdicts, f["id"])]
    stops += figs.verdict_problems(found)
    stops += [f"előellenőrzés: {p}" for p in figs.preflight_problems(
        local, repo, [f["id"] for _, f in inserting if not figs.is_inserted(repo, f["page"], f["id"])])]
    by_subject = {h.subject: h for h in found}
    direct = [(rel.split("/")[1], svg) for rel in changed_pages if in_scope(rel, subjects)
              for svg in figs.direct_svgs(repo, [rel], {p for p in current if p.endswith(".svg")})]
    stops += [f"előellenőrzés: {p}" for p in figs.direct_svg_problems(repo, sorted({svg for _, svg in direct}))]
    stops += figs.figure_blockers(repo, found, subjects)
    data_problems, new_requests = machine_data.check(repo, found, pages, new_pages, subjects)
    stops += data_problems
    if stops:
        return stop(out, "STOP (nem írtam semmit):", stops)
    head_generated = {p: _head_generated(git, p) for p in changed_pages}
    changed: list[str] = []
    warnings: list[str] = []
    try:
        for h in found:
            for f in h.figures:
                if not accepted(h.verdicts, f["id"]):
                    out(f"nincs accept, nem illesztem be: {h.subject}/{f['id']}")
        figs.generation_ledger(local, repo, changed)
        figs.svg_receipts(repo, [(h.subject, f) for h, f in inserting], changed, direct=sorted(set(direct)),
                          pass_ids={s: machine_data.pass_id(h) for s, h in by_subject.items()})
        for h, fig in inserting:
            if figs.insert_one(repo, fig, h.verdicts[fig["id"]], h.keys.get(fig["id"], ""), at):
                changed.append(fig["page"])
                out(f"beillesztve: {h.subject}/{fig['id']}")
        for h in found:
            for item in h.rechecks:
                given = accepted(h.recheck_verdicts, item["id"])
                if given and figs.renew_one(repo, item["id"], item["page"], given, h.keys.get(item["id"], ""), at):
                    out(f"ítélet megújítva (újranézés): {h.subject}/{item['id']}")
        machine_data.write(local, repo, found, changed_pages, head_generated, new_requests, at, changed, out)
        machine_data.draft_notices(repo, changed, warnings, subjects)
        skipped = machine_data.machine_blocks(repo, changed, warnings, subjects)
        stale = [r for r in insert.invalidated(repo) if in_scope(r["file"], subjects)]
        if stale:
            return stop(out, "STOP: beillesztett ábra ítélete érvénytelenedett, és nincs rá érvényes újranézési "
                             "accept (az ábrát az új szöveggel össze kell vetni; semmit nem töröltem):",
                        [f"{r['file']}#{r['id']}" for r in stale])
        machine_data.reader_bookkeeping(repo)
        generate.write_indexes(repo)
        figs._write_if_changed(repo, decisions.OVERVIEW, decisions.overview(repo, skip=skipped), changed)
        public.write(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                         public.writer_svg_rights(repo)))
    finally:
        # Every page as the tool left it, also after an interruption: the guard then knows the
        # tool's own writes (step 0 has made sure no hand edit was among them).
        tool_writes.record(repo, parts=[p for p in safefs.walk_files(repo, "wiki")
                                        if p.endswith(".md") and (not subjects or guard.in_subjects(p, subjects))])
    for line in warnings:
        out(f"figyelmeztetés: {line}")
    return done.report(repo, out)


def _head_generated(git, rel: str):
    from ..wiki import frontmatter
    proc = git.run("show", f"HEAD:{rel}", check=False)
    if proc.returncode != 0:
        return None
    try:
        return frontmatter.split(proc.stdout.decode("utf-8", "replace")).meta.get("generated")
    except Exception:           # noqa: BLE001 - an unreadable old page: treat as unstamped
        return None


def snapshot(local, subjects: list[str] | None, only: list[str] | None, out=print) -> int:
    """`--snapshot`: preflight, then keys.json and diff.patch for the reviewer (module text)."""
    repo = local.repo
    found = handoffs(repo, subjects)
    if not found:
        raise Refused(f"nincs átadás ({OUT}/<tantárgy>/)")
    wanted_new = [f["id"] for h in found for f in h.figures if not only or f["id"] in only]
    problems = figs.preflight_problems(local, repo, [f for f in wanted_new])
    if problems:
        return stop(out, "STOP: az ábra nem mehet a lektorhoz (előellenőrzés; nem írtam semmit):", problems)
    unreadable = []
    for h in found:
        keys = dict(h.keys) if only else {}
        wanted = [(f["id"], False) for f in h.figures] + [(r["id"], True) for r in h.rechecks]
        for fid, inserted in wanted:
            if only and fid not in only:
                continue
            state = None if inserted else figs.candidate_state(repo, fid)
            if state in ("failed", "no-figure"):
                out(f"nem megy a lektorhoz ({state}): {h.subject}/{fid}")
                continue
            try:
                keys[fid] = figs.inserted_key(repo, fid)[1] if inserted else figs.new_key(repo, fid)
            except (ValueError, OSError, KeyError) as exc:
                unreadable.append(f"{h.subject}/{fid}: {exc}")
        base = f"{OUT}/{h.subject}"
        safefs.write_text(repo, f"{base}/keys.json", json.dumps(dict(sorted(keys.items())), indent=1) + "\n")
        safefs.write_text(repo, f"{base}/diff.patch", diff_patch(local, h.subject))
        out(f"pillanatkép: {base}/keys.json ({len(keys)} ábra), {base}/diff.patch")
    for line in unreadable:
        out(f"  nem számolható: {line}")
    local.record("close", "snapshot", subjects=[h.subject for h in found], only=only or "all")
    return 1 if unreadable else 0


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
    """Paths (relative, sorted) that differ between two trees, `SKIP` and the ignored working
    folder `.school-notes/` (hand-overs, the tool-writes record) left out."""
    def files(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if (p.is_file() or p.is_symlink()) and p.relative_to(root).parts[0] not in (*SKIP, ".school-notes")}

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
