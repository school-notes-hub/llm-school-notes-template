"""Merge reader/list/figure findings without duplicating pass-one findings."""

import re
import json

from ..review.severity import is_error
from ..review import attempts, files, relations
from ..state import safefs
from ..wiki import frontmatter


def locate(repo, finding):
    """The reviewer names the line; the tool only checks that it exists (T4)."""
    path, n = finding["file"], finding.get("line")
    lines = safefs.read_text(repo, path).splitlines() if path.endswith((".md", ".svg")) and safefs.is_file(repo, path) else []
    valid = isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(lines)
    return {**finding, "line": n if valid else None, "unlocated": not valid}


def prepare(repo, findings, notes, pages=()):
    """Advice goes to owner notes; a page with only advice is ok (also on replay)."""
    from ..figures import migration_gate
    findings = [figure_quote(repo, f) for f in findings]
    findings = [f for f in findings if not migration_gate.concerns(repo, f)]
    advice = [f for f in findings if not is_error(f)]
    findings = [f for f in findings if is_error(f)]
    pages = [{**p, "verdict": "ok"} if not any(f["file"] == p["file"] for f in findings) else p for p in pages]
    _, notes = advice_notes(advice, notes)
    return findings, notes, pages


def write(repo, path, findings, notes, model, base, at, *, write=None):
    """Write findings already routed by prepare; no second partition on replay."""
    if safefs.is_file(repo, path):
        return path
    located = [locate(repo, f) for f in findings]
    ordered = sorted(located, key=lambda f: (f["file"], f.get("line") or 0, f.get("origin", ""),
                                             f.get("quote", ""), f["problem"], f.get("id", ""),
                                             json.dumps(f, sort_keys=True, ensure_ascii=False)))
    review = {"verdict": "changes" if ordered else "ok", "owner_notes": notes,
              "findings": [{**f, "id": f"R{n}"} for n, f in enumerate(ordered, 1)]}
    files.write_review(repo, at[:10], review, model, base, base, path=repo / path, write=write)
    return path


def reopen(repo, key, answer):
    rel, item_id = key.rsplit("#", 1)
    text = safefs.read_text(repo, rel)
    page = frontmatter.split(text)
    details = dict(page.meta.get("item_details", {}))
    record = relations.details(text, item_id)
    if record.get("recheck") == {"verdict": "not-ok", "answer": answer}:
        return rel
    record.update(origin="recheck", recheck={"verdict": "not-ok", "answer": answer})
    details[item_id] = record
    items = {**page.meta["items"], item_id: attempts.failed_status(record)}
    safefs.write_text(repo, rel, frontmatter.set_keys(text, {
        "items": items, "item_details": details, "status": files.compute_status(items)}))
    return rel


def append(repo, path, findings, notes, label, *, write=safefs.write_text):
    """One run report, replay-safe supplements for P5 and exhausted figures."""
    findings, notes = advice_notes(findings, notes)
    text = safefs.read_text(repo, path)
    page = frontmatter.split(text)
    labels = page.meta.get("supplements", [])
    if label in labels:
        return path
    known = relations.inventory(repo)
    items, details = dict(page.meta["items"]), dict(page.meta.get("item_details", {}))
    number = max((int(k[1:]) for k in items), default=0)
    body = []
    for finding in sorted((locate(repo, f) for f in findings),
                          key=lambda f: (f["file"], f.get("line") or 0, f["problem"], json.dumps(f, sort_keys=True, ensure_ascii=False))):
        status, unlocated = relations.route(finding, known)
        if status == "pending":
            body += ["## Függő (nyitott kérdésre vár)", "", finding["problem"], ""]
            continue
        number += 1
        key = f"R{number}"
        chain = max(finding.get("chain", 0), relations.chain(finding, known))
        items[key] = finding.get("owner_status", status)
        details[key] = {"file": finding["file"], "round": 1, "chain": chain,
                        **attempts.inherited(finding, known),
                        "origin": finding["origin"], "category": finding["category"], "severity": "hiba",
                        "relates_to": finding.get("relates_to"),
                        "unlocated": unlocated or finding["unlocated"],
                        **{k: finding[k] for k in ("quote", "hit_id", "figure_id", "outside_assignment") if k in finding}}
        body += [f"### {key} – {finding['file']}", "", f"**Probléma:** {finding['problem']}", "",
                 f"**Javaslat:** {finding.get('suggestion', '')}", ""]
    if notes:
        body += ["## Tulajdonosi észrevételek", ""] + ["* " + " ".join(n.split()) for n in notes]
    output = text.rstrip() + "\n\n" + "\n".join(body) + "\n"
    write(repo, path, frontmatter.set_keys(output, {
        "items": items, "item_details": details, "status": files.compute_status(items),
        "supplements": sorted(labels + [label])}))
    return path


def figure_quote(repo, finding):
    from ..figures import commissions
    quote = finding.get("quote", "")
    match = re.search(r"(?:reader-preview/)([a-z0-9-]+)\.png", quote)
    if not match:
        return finding
    fid = match[1]
    found = commissions.markers(repo).get(fid, [])
    if len(found) != 1 or found[0][0] != finding["file"]:
        return finding
    text = safefs.read_text(repo, finding["file"])
    marker = next(m[0] for m in commissions.MARKER.finditer(text) if m[1] == fid)
    return {**finding, "quote": marker, "figure_id": fid, "unlocated": False}


def advice_notes(findings, notes):
    notes = list(notes)
    for f in sorted(findings, key=lambda f: (f.get("file", ""), f.get("quote", ""), f.get("problem", ""), f.get("suggestion", ""))):
        if f.get("severity", "hiba") == "javaslat":
            notes.append(f"{f['file']}: {f['problem']}" + (f" → {f['suggestion']}" if f.get("suggestion") else ""))
    return [f for f in findings if is_error(f)], list(dict.fromkeys(notes))
