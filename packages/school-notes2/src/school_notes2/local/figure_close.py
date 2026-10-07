"""The figure part of `sn close`: preflight, the reviewed-content keys, insertion of an
accepted figure, renewal of an inserted figure's verdict, and the generation and SVG
authorship receipts. Nothing here decides: a figure goes in only with the reviewer's accept
for exactly the content seen (`keys.json`)."""

import hashlib
import re
from pathlib import Path

from ..figures import commissions, context as fctx, insert, preflight
from ..figures.review import is_error
from ..schemas import validate
from ..state import safefs
from ..wiki import markers, public
from ..wiki.pages import relative, sha256
from ..wiki.rights import SVG_RECEIPTS
from .common import today
from .handoff import Handoff, _json, accepted, in_scope

LEDGER = "docs/evidence/image-generation/ledger.json"

OPEN_LARGE = "[Az ábra megnyitása nagy méretben]"

END = "<!-- /school-notes:generated -->"

REVIEWER = "claude-opus-5-5/high"     # the owner's fixed reviewer (plan 0/2): Claude Opus 5.5, high


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


def ledger_rights(settings):
    """`generated(rel)` for the preflight: an output of this learner's host image ledger."""
    hashes = set(generation_outputs(settings))
    return lambda rel: ("generated", "host image ledger") if safefs.is_file(settings.worktree, rel) and \
        sha256(settings.worktree, rel) in hashes else None


def preflight_problems(local, repo: Path, fids: list[str]) -> list[str]:
    """`figures.preflight` for each figure, in the given order."""
    generated = ledger_rights(local.image_settings(repo))
    return [f"{fid}: {problem}" for fid in fids for problem in preflight.problems(repo, fid, generated=generated)]


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


def figure_blockers(repo: Path, found: list[Handoff], subjects: list[str] | None) -> list[str]:
    """The figure cases that stop the close before it writes (step 0)."""
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
