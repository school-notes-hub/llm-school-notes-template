"""Nightly checks of embedded figures without a current independent verdict.

Legacy images get markers only in a private review view. Publication bytes and wiki
text stay untouched; a fingerprint of the original embedding binds the receipt.
"""

from dataclasses import replace
import hashlib

from ..figures import commissions, context, inputs, insert, review, migration_gate
from ..state import safefs
from ..wiki import frontmatter, pages, public
from . import relations, scope, topics


def targeted(repo, work, unit, items):
    selected = []
    for spec in discover(work, unit):
        page = spec["page"]
        old, new = topics.text(repo, unit["base"], page), safefs.read_text(work, page)
        lines = scope.changed(old, new)
        assigned = any(i.get("figure_id") == spec["id"] or
                       spec.get("asset") and i.get("file") == spec["asset"] for i in items)
        if spec.get("asset"):
            before = repo.run("show", f"{unit['base']}:{spec['asset']}", check=False)
            changed = before.returncode != 0 or not safefs.is_file(work, spec["asset"]) or before.stdout != safefs.read_bytes(work, spec["asset"])
            changed |= any(l.image and pages.resolve(page, l.target) == spec["asset"] and l.line in lines
                           for l in pages.links(new))
            assigned |= any(i.get("file") == page and any(
                l.image and pages.resolve(page, l.target) == spec["asset"] for l in pages.links(i.get("quote", "")))
                for i in items)
        else:
            changed = spec["source"] not in old
        if spec["kind"] == "banner":
            before, after = frontmatter.split(old).meta, frontmatter.split(new).meta
            changed |= any(before.get(k) != after.get(k) for k in ("title", "description"))
        if changed or assigned:
            selected.append(spec)
    return selected


def fingerprint(repo, spec):
    text = safefs.read_text(repo, spec["page"])
    if spec["kind"] == "banner":
        meta = frontmatter.split(text).meta
        embedding = {"title": meta.get("title", ""), "description": meta.get("description", "")}
    else:
        embedding = context.canonical(context.section(text, spec["anchor"])[0], spec["page"], spec)
    if spec.get("asset"):
        uses = context.usage_keys(repo, {"page": spec["page"]}, {"asset": spec["asset"]})
        own = [link for link in pages.links(text) if link.image and pages.resolve(spec["page"], link.target) == spec["asset"]]
        if not own:
            raise ValueError("image removed")
        image = hashlib.sha256(safefs.read_bytes(repo, spec["asset"])).hexdigest()
        alts = [link.text for link in own]
    else:
        if spec["source"] not in text:
            raise ValueError("Mermaid removed")
        image, alts, uses = spec["source"], [], []
    caption = ""
    if spec.get("commission"):
        caption = context.embedded_candidate(repo, spec["commission"], spec["candidate"]).get("caption", "")
    if spec["kind"] == "banner":
        return context.digest({"image": image, "embedding": embedding})
    return context.digest({"image": image, "embedding": embedding, "alts": alts, "caption": caption, "uses": uses})


def discover(repo, unit):
    result, assets = [], set()
    embedded = relations.related_pages(repo)
    evidence = [safefs.read_json(repo, p) for p in safefs.glob(repo, "docs/evidence/media", "docs/evidence/media/**/figure.json")]
    requested = {r.get("candidate", {}).get("asset") for r in evidence if r.get("license_request")}
    licensed = {a["path"]: a["sha256"] for a in public.read_existing(repo).get("assets", [])
                if a.get("rights") == "licensed" and a["path"] not in requested}
    for page in unit["pages"]:
        if not page.endswith(".md") or page.startswith("wiki/assets/"):
            continue
        text = safefs.read_text(repo, page)
        for link in pages.links(text):
            asset = pages.resolve(page, link.target)
            if not link.image or not asset or not asset.startswith("wiki/assets/") or asset in assets:
                continue
            if asset in licensed and pages.is_file(repo, asset) and pages.sha256(repo, asset) == licensed[asset]:
                continue
            primary = min(embedded.get(asset, {page}), key=lambda p: (commissions.topic(repo, p), p))
            if commissions.topic(repo, primary) != unit["topic"] or page != primary:
                continue
            assets.add(asset)
            position = sum(len(s) for s in text.splitlines(True)[:link.line - 1])
            heads = list(context.HEAD.finditer(pages.CODE_FENCE.sub("", frontmatter.split(text[:position]).body)))
            spec = {"page": page, "asset": asset, "alt": link.text or "Ábra",
                    "kind": "figure" if heads else "banner", "anchor": heads[-1][2] if heads else ""}
            record = next((r for r in evidence if r.get("commission", {}).get("page") == page
                           and r.get("candidate", {}).get("asset") == asset), None)
            if record:
                spec["commission"] = record["commission"]
                # Preparation resolves the live embedding and records malformed ones
                # as pending; discovery must not abort the other figures.
                spec["candidate"] = record["candidate"]
                spec["anchor"], spec["kind"] = record["commission"]["anchor"], record["commission"]["kind"]
            result.append(spec)
        for match in commissions.MERMAID.finditer(text):
            heads = list(context.HEAD.finditer(pages.CODE_FENCE.sub("", frontmatter.split(text[:match.start()]).body)))
            if heads:
                result.append({"page": page, "source": match[1], "kind": "figure", "anchor": heads[-1][2], "alt": "Ábra"})
    for spec in result:
        spec["id"] = spec.get("commission", {}).get("id") or "night-" + context.digest(spec)[:24]
    return [s for s in result if not migration_gate.concerns(repo, s)]


def valid(repo, spec, records):
    key = fingerprint(repo, spec)
    for record in records:
        if record.get("role") != "figure-review":
            continue
        if record.get("night_spec") and record["key"] == key:
            return True
        brief, candidate = record.get("commission", {}), record.get("candidate", {})
        if record.get("file") != spec["page"] or (spec.get("asset") and candidate.get("asset") != spec["asset"]):
            continue
        if not spec.get("asset") and candidate.get("mermaid") != hashlib.sha256(spec["source"].encode()).hexdigest():
            continue
        try:
            if context.verdict_key(repo, brief, candidate) == record["key"]:
                return True
        except (ValueError, OSError):
            pass
    return False


def run(repo, unit, folder, configured, render, log, *, view_folder=None, selected=None):
    folder.mkdir(parents=True, exist_ok=True)
    saved = safefs.read_json(folder, "night-figures.json")
    if saved is not None:
        return saved
    records = safefs.read_json(repo, insert.VERDICTS, [])
    specs = []
    for spec in discover(repo, unit) if selected is None else selected:
        if migration_gate.concerns(repo, spec):
            continue
        try:
            if valid(repo, spec, records):
                continue
        except (ValueError, OSError):
            pass  # The per-figure preparation records missing bytes/context as pending.
        specs.append(spec)
    if not specs:
        return {"records": [], "findings": [], "notes": [], "pending": [], "checked": []}
    view = view_folder or folder / "figure-view"
    prepare_view(repo, view)
    briefs = [_adapt(view, spec) for spec in specs]
    configured = replace(configured, task_dir=folder)
    result = {"records": [], "findings": [], "notes": [], "pending": [], "checked": []}
    by_id = {s["id"]: s for s in specs}
    for name, batch in inputs.batches(view, briefs):
        receipt = review.run_batch(view, batch, name, configured, render=render, log=log)
        _merge(repo, unit, name, batch, receipt, by_id, result)
    safefs.write_json(folder, "night-figures.json", result)
    return result


def prepare_view(repo, view):
    view.mkdir(parents=True, exist_ok=True)
    if safefs.read_json(view, "snapshot.json") is not None:
        return
    for prefix in ("wiki", "docs", "sources", "publication"):
        for path in safefs.walk_files(repo, prefix):
            safefs.link_or_copy(repo, view, path)
    safefs.write_json(view, "snapshot.json", {"ready": True})


def _merge(repo, unit, name, batch, receipt, by_id, result):
    result["notes"] += receipt.get("review", {}).get("owner_notes", [])
    for verdict in receipt.get("review", {}).get("figures", []):
        spec = by_id[verdict["id"]]
        result["checked"].append(spec)
        key = fingerprint(repo, spec)
        if verdict["verdict"] == "accept":
            result["records"].append({"role": "figure-review", "file": spec["page"], "id": spec["id"],
                                      "key": key, "verdict": "accept", "model": receipt["model"],
                                      "night_spec": spec, "observed": verdict["observed"]})
        else:
            from ..figures import rejected
            brief = next(b for b in batch if b["id"] == verdict["id"])
            result.setdefault("retries", []).append(rejected.request(spec, brief, verdict, key))
    if receipt["status"] != "reviewed" or receipt.get("failed"):
        result["notes"].append(f"Hiányzó ábraítélet: {unit['topic']} ({name}).")
        judged = {v["id"] for v in receipt.get("review", {}).get("figures", [])}
        for brief in batch:
            if brief["id"] not in judged:
                result["pending"].append({"spec": by_id[brief["id"]],
                                           "reason": receipt.get("reason", "Hiányzó ábraítélet.")})


def _adapt(view, spec):
    fid, page = spec["id"], spec["page"]
    if spec.get("commission"):
        safefs.write_json(view, f".school-notes/figures/{fid}/figure.json", spec["candidate"])
        return spec["commission"]
    brief = {"id": fid, "page": page, "kind": spec["kind"], "anchor": spec["anchor"],
             "purpose": "A meglévő ábra független ellenőrzése.", "must_show": [], "avoid_misreading": "",
             "taught_conventions": [], "text_complete_without_figure": True}
    candidate = {"state": "candidate", "alt": spec["alt"], "caption": "", "form": "embedded",
                 "tool": "nightly", "elements": [], "visible_text": [], "attempt": 1}
    text = safefs.read_text(view, page)
    marker = f"<!-- figure: {fid} -->\n"
    if spec.get("asset"):
        candidate["asset"] = spec["asset"]
        if spec["asset"].endswith(".svg"):
            candidate["source"] = spec["asset"]
        link = next(l for l in pages.links(text) if l.image and pages.resolve(page, l.target) == spec["asset"])
        lines = text.splitlines(True)
        if marker.strip() not in text:
            lines.insert(link.line - 1, marker)
        text = "".join(lines)
    else:
        candidate["mermaid"] = hashlib.sha256(spec["source"].encode()).hexdigest()
        match = next(m for m in commissions.MERMAID.finditer(text) if m[1] == spec["source"])
        if marker.strip() not in text:
            text = text[:match.start()] + marker + text[match.start():]
    safefs.write_text(view, page, text)
    safefs.write_json(view, f".school-notes/figures/{fid}/figure.json", candidate)
    return brief


def apply(repo, records, at):
    records = [r for r in records if not migration_gate.concerns(repo, r.get("night_spec", r))]
    existing = safefs.read_json(repo, insert.VERDICTS, [])
    for record in records:
        try:
            if fingerprint(repo, record["night_spec"]) != record["key"]:
                continue
        except (ValueError, OSError):
            continue
        existing = [r for r in existing if (r.get("role"), r.get("id")) != ("figure-review", record["id"])]
        existing.append({**record, "at": at})
        safefs.write_json(repo, f"docs/evidence/media/{record['id']}/nightly.json", {**record, "at": at})
    safefs.write_json(repo, insert.VERDICTS, sorted(existing, key=lambda r: (r["file"], r["key"], r["role"])))
    return [insert.VERDICTS] + [f"docs/evidence/media/{r['id']}/nightly.json" for r in records
                               if safefs.is_file(repo, f"docs/evidence/media/{r['id']}/nightly.json")]
