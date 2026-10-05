"""Merge trusted topic receipts; apply closure/chain rules on the final report tree."""

import re

from ..reader import notice_migration, notices, report, verdicts
from ..reader.units import page_key
from ..state import safefs
from ..wiki import frontmatter, public
from . import attempts, figure_waiting, files, relations, scope, topics, warnings


def chain(repo, head, finding, *, fix_touched=False):
    """Locate the quote at H, then inspect every covered line's last author commit."""
    quote = finding.get("quote", "")
    text = topics.text(repo, head, finding["file"])
    matches = _matches(quote, text)
    if len(matches) != 1:
        text, quote = _plain(text), _plain(quote)
        matches = _matches(quote, text)
    if len(matches) != 1:
        return {**finding, "line": None, "unlocated": True, "chain": int(fix_touched)}
    match = matches[0]
    first = text[:match.start()].count("\n") + 1
    last = text[:match.end()].count("\n") + 1
    proc = repo.run("blame", "--line-porcelain", "-L", f"{first},{last}", head, "--", finding["file"], check=False)
    commits = sorted(set(re.findall(r"^([0-9a-f]{40}) \d+ \d+", proc.stdout.decode(), re.M)))
    return {**finding, "line": first, "unlocated": False,
            "chain": int(any(topics.is_fix(repo, c) for c in commits))}


def _matches(quote, text):
    pattern = r"\s+".join(re.escape(w) for w in quote.split())
    return list(re.finditer(pattern, text)) if pattern else []


def _plain(text):
    """Remove inline Markdown without changing line numbers used by blame."""
    text = re.sub(r"!?\[([^]\n]+)\]\([^\n)]*\)", r"\1", text)
    text = re.sub(r"\[\^[^]\n]+\]", "", text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+.!$-])", r"\1", text)
    return re.sub(r"[*_`$]", "", text)


def assemble(task, repo, work):
    findings, notes, sections = [], [], []
    for entry in task.get("topic_results", []):
        unit, receipt = entry["unit"], entry["receipt"]
        section = {"topic": unit["topic"], "mode": unit["mode"], "status": receipt["status"],
                   "duration_s": receipt.get("duration_s", 0), "findings": []}
        if receipt["status"] == "reviewed":
            value = receipt["review"]
            fix_touched = unit["mode"] == "targeted" or any(topics.is_fix(repo, c) for c in unit["commits"])
            own = list(value["findings"])
            # Generate list findings without changing the pinned worktree's verdict store.
            by_id = {h["id"]: h for h in entry["input"]["hits"]}
            for hit in value["hits"]:
                if hit["verdict"] == "hiba" and not hit.get("covered_by"):
                    row = by_id[hit["hit_id"]]
                    lines = topics.text(repo, task.get("H"), row["file"]).splitlines()
                    f = {"file": row["file"], "quote": lines[row["line"] - 1], "problem": hit["reason"],
                         "category": "forráskötött", "relates_to": None, "hit_id": row["id"]}
                    own.append(f)
            own += entry.get("figure_findings", [])
            if unit["mode"] == "targeted":
                own, outside = scope.partition(own, lambda p: topics.text(repo, unit["base"], p),
                                               lambda p: topics.text(repo, task.get("H"), p), unit["assigned_pages"])
                notes += outside
            own, notes, _ = report.prepare(work, own, notes)
            own = [chain(repo, task.get("H"), f, fix_touched=fix_touched) for f in own]
            for f in sorted(own, key=lambda f: (f["file"], f.get("line") or 0, f["problem"], f.get("quote", ""))):
                f = {**f, "id": f"R{len(findings) + 1}", "topic": unit["topic"]}
                findings.append(f)
                section["findings"].append(f["id"])
            notes += value.get("owner_notes", []) + entry.get("figure_notes", [])
        sections.append(section)
    value = {"verdict": "changes" if findings else "ok", "findings": findings,
             "owner_notes": notes, "topics": sections}
    safefs.write_json(task.dir, "review.json", value)
    return value


def complete(entry):
    return entry.get("receipt", {}).get("status") == "reviewed" and not entry.get("figure_pending")


def state(task):
    done = {r["topic"]: r["commit"] for r in task.get("nightly_state", {}).get("done_topics", [])}
    for entry in task.get("topic_results", []):
        if complete(entry):
            done[entry["unit"]["topic"]] = task.get("H")
    return topics.validated({
        "done_topics": [] if task.get("all_topics_done", False) else [
            {"topic": t, "commit": done[t]} for t in sorted(done)],
        "blocked_topics": sorted(task.get("blocked_topics", []), key=lambda r: r["topic"]),
        "failed_topics": sorted(task.get("failed_topics", []), key=lambda r: r["topic"])})


def apply(task, work, ident, *, log=None, git=None):
    """Replayed on each fresh main during atomic close; keys remain bound to H."""
    written, owners, notes, answers = [], [], [], []
    for entry in task.get("topic_results", []):
        if entry["receipt"]["status"] != "reviewed":
            continue
        unit, receipt = entry["unit"], entry["receipt"]
        model, value = receipt["model"], receipt["review"]
        current = [p for p in value["pages"] if safefs.is_file(work, p["file"])
                   and page_key(work, p["file"]) == unit["keys"][p["file"]]]
        if current:
            verdicts.record(work, current, unit["keys"], model, ident.at)
        originals = {i["key"]: i for i in entry["input"]["items"]}
        answers += [(originals[item["key"]], item) for item in value["items"]]
        hits = entry["input"]["hits"]
        if hits:
            warnings.record(work, hits, [{**h, "id": h["hit_id"]} for h in value["hits"]])
            written.append(warnings.PATH)
        from . import night_figures
        written += night_figures.apply(work, entry.get("figure_records", []), ident.at)
    paths, owners = apply_items(work, answers)
    written += paths
    written += _finish_apply(task, work, notes, log=log, git=git)
    return sorted(set(written)), owners, notes


def _finish_apply(task, work, notes, *, log=None, git=None):
    written = []
    written += figure_waiting.apply(work,
        [p for e in task.get("topic_results", []) for p in e.get("figure_pending", [])],
        [s for e in task.get("topic_results", []) for s in e.get("figure_checked", [])])
    from ..figures import rejected
    written += rejected.apply(work, [r for e in task.get("topic_results", []) for r in e.get("figure_retries", [])], log=log)
    safefs.write_json(work, topics.STATE, state(task))
    if not safefs.is_file(work, verdicts.PATH):
        safefs.write_json(work, verdicts.PATH, [])
    verdicts.invalidate(work)
    touched = {p for u in task.get("units", []) for p in u["assigned_pages"]}
    written += notice_migration.refresh(work, git=git)
    written += notices.refresh(work, sorted(touched))
    try:
        public.write(work, public.either(public.render_rights(work), public.media_receipt_rights(work)))
        written.append("publication/public.json")
    except public.PublicError as exc:
        notes.append(f"A public.json újraépítése sikertelen: {exc}")
    written += [topics.STATE, verdicts.PATH]
    return written


def apply_item(work, original, answer):
    paths, owners = apply_items(work, [(original, answer)])
    return (paths[0] if paths else None), (owners[0] if owners else None)


def apply_items(work, answers):
    """Read and rewrite each report once; later answers see the preceding mutation."""
    grouped, written, owners = {}, [], []
    for original, answer in answers:
        rel, item_id = answer["key"].rsplit("#", 1)
        grouped.setdefault(rel, []).append((item_id, original, answer))
    for rel, entries in sorted(grouped.items()):
        if not safefs.is_file(work, rel):
            continue
        text = safefs.read_text(work, rel)
        page = files.parse_report(text)
        changed = False
        for item_id, original, answer in sorted(entries, key=lambda e: (e[0], e[2]["verdict"], e[2]["answer"])):
            detail = relations.details(page, item_id)
            if page.meta.get("items", {}).get(item_id) != original["status"]:
                continue  # Concurrent owner/writer closure wins.
            verdict = answer["verdict"]
            if verdict in ("accept", "keep"):
                if detail.get("response"):
                    continue
                if original["status"] != "disagree" or detail["round"] != 1 or not answer["answer"].strip():
                    raise files.ClosureError("only an unanswered round-1 disagreement accepts a response")
                detail["response"] = {"verdict": verdict, "answer": answer["answer"]}
                if verdict == "keep":
                    page.meta["items"][item_id], detail["round"] = attempts.failed_status(detail), 2
                page.body = page.body.rstrip() + f"\n\n## Válasz ({item_id})\n\n{verdict}: {' '.join(answer['answer'].split())}\n"
            else:
                if original["status"] == "fixed" and detail.get("recheck"):
                    continue
                detail["recheck" if original["status"] == "fixed" else "nightly"] = {
                    "verdict": verdict, "answer": answer["answer"]}
                if verdict == "not-ok":
                    detail["chain"] = max(detail["chain"], int(original.get("fix_commit", False)))
                    page.meta["items"][item_id] = attempts.failed_status(detail)
                    if page.meta["items"][item_id] == "owner":
                        owners.append({"file": rel, "item_id": item_id, "reason": answer["answer"]})
            page.meta.setdefault("item_details", {})[item_id] = detail
            changed = True
        if changed:
            safefs.write_text(work, rel, frontmatter.set_keys(page, {
                "items": page.meta["items"], "item_details": page.meta["item_details"],
                "status": files.compute_status(page.meta["items"])}))
            written.append(rel)
    return written, owners
