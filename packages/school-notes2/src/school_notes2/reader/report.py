"""Merge reader/list/figure findings without duplicating pass-one findings."""

import re

from ..review import files, generated, relations, warnings
from ..state import safefs
from ..wiki import frontmatter


def locate(repo, finding):
    quote = " ".join(finding.get("quote", "").split())
    path = finding["file"]
    text = safefs.read_text(repo, path) if path.endswith((".md", ".svg")) and safefs.is_file(repo, path) else ""
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    matches = list(re.finditer(pattern, text)) if quote else []
    match = matches[0] if len(matches) == 1 and not finding.get("unlocated") else None
    return {**finding, "line": text[:match.start()].count("\n") + 1 if match else None,
            "unlocated": not bool(match)}


def list_findings(repo, hits, output):
    decisions = [{**h, "id": h["hit_id"]} for h in output]
    # The warning store's content keys apply to source_ref findings only.
    source = [h for h in hits if "line_hash" in h]
    selected = {h["id"] for h in source}
    if source:
        warnings.record(repo, source, [d for d in decisions if d["id"] in selected])
    by_id = {h["id"]: h for h in hits}
    result = []
    for decision in decisions:
        if decision["verdict"] != "hiba" or decision.get("covered_by"):
            continue
        hit = by_id[decision["id"]]
        lines = safefs.read_text(repo, hit["file"]).splitlines()
        n = hit.get("line") or 1
        result.append({"file": hit["file"], "quote": lines[n - 1] if n <= len(lines) else "",
                       "problem": decision["reason"], "suggestion": "", "category": "forráskötött",
                       "origin": "list", "relates_to": None, "hit_id": hit["id"]})
    return result


def prepare(repo, findings, notes, pages=()):
    """Route once before report writing and page verdict decisions (also on replay)."""
    from ..figures import migration_gate
    findings = [figure_quote(repo, f) for f in findings]
    findings = [f for f in findings if not migration_gate.concerns(repo, f)]
    kept, notes, literals = generated.partition(repo, findings, notes)
    return kept, notes, generated.page_verdicts(pages, findings, literals)


def write(repo, path, findings, notes, model, base, at):
    """Write findings already routed by prepare; no second partition on replay."""
    if safefs.is_file(repo, path):
        return path
    located = [locate(repo, f) for f in findings]
    ordered = sorted(located, key=lambda f: (f["file"], f.get("line") or 0, f.get("origin", ""),
                                             f.get("quote", ""), f["problem"], f.get("id", "")))
    review = {"verdict": "changes" if ordered else "ok", "owner_notes": notes,
              "findings": [{**f, "id": f"R{n}"} for n, f in enumerate(ordered, 1)]}
    files.write_review(repo, at[:10], review, model, base, base, path=repo / path)
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
    items = {**page.meta["items"], item_id: "open"}
    safefs.write_text(repo, rel, frontmatter.set_keys(text, {
        "items": items, "item_details": details, "status": files.compute_status(items)}))
    return rel


def append(repo, path, findings, notes, label):
    """One run report, replay-safe supplements for P5 and exhausted figures."""
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
                          key=lambda f: (f["file"], f.get("line") or 0, f["problem"])):
        status, unlocated = relations.route(finding, known)
        if status == "pending":
            body += ["## Függő (nyitott kérdésre vár)", "", finding["problem"], ""]
            continue
        number += 1
        key = f"R{number}"
        chain = max(finding.get("chain", 0), relations.chain(finding, known))
        items[key] = "owner" if chain else status
        details[key] = {"file": finding["file"], "round": 1, "chain": chain,
                        "origin": finding["origin"], "category": finding["category"],
                        "relates_to": finding.get("relates_to"),
                        "unlocated": unlocated or finding["unlocated"],
                        **{k: finding[k] for k in ("quote", "hit_id", "figure_id", "outside_assignment") if k in finding}}
        body += [f"### {key} – {finding['file']}", "", f"**Probléma:** {finding['problem']}", "",
                 f"**Javaslat:** {finding.get('suggestion', '')}", ""]
    if notes:
        body += ["## Tulajdonosi észrevételek", ""] + ["* " + " ".join(n.split()) for n in notes]
    output = text.rstrip() + "\n\n" + "\n".join(body) + "\n"
    safefs.write_text(repo, path, frontmatter.set_keys(output, {
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
