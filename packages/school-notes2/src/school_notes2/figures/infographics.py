"""A writer decision per assigned topic, bound to its normalized teaching content."""

import hashlib
import json
import re
from difflib import SequenceMatcher

import yaml

from ..review import relations
from ..state import safefs
from ..wiki import author, frontmatter
from ..wiki.check import item
from . import commissions, pending

PATH = "docs/review/infographic-decisions.json"
RESULT = ".school-notes/result.json"


def content(repo, page):
    text = commissions.MARKER.sub("", author.part(safefs.read_text(repo, page)))
    body = frontmatter.split(text).body
    return {"headings": sorted(set(re.findall(r"^## (.+)$", body, re.M))),
            "words": body.split()}


def content_key(repo, page):
    return hashlib.sha256(json.dumps(content(repo, page), ensure_ascii=False).encode()).hexdigest()


def changed(saved, current):
    if not saved:
        return True
    previous = saved.get("content")
    if previous is None:  # Older receipts lack a baseline; do not invent a material change.
        return False
    if previous["headings"] != current["headings"]:
        return True
    words = current["words"]
    matched = sum(b.size for b in SequenceMatcher(None, previous["words"], words, autojunk=False).get_matching_blocks())
    return bool(words) and (len(words) - matched) / len(words) >= .30


def assigned(repo, fetch):
    known = relations.inventory(repo)["items"]
    embedded = relations.related_pages(repo)
    pages = set()
    if fetch.get("mode") not in ("fix", "repair"):
        from ..wiki.pages import wiki_pages
        subjects = {p["subject"] for p in fetch.get("packages", [])}
        pages.update(p for p in wiki_pages(repo) if p.split("/")[1] in subjects)
    for entry in fetch.get("open_review_items", []):
        page = known.get(entry["file"] + "#" + entry["item_id"], {}).get("file")
        if page:
            pages.update(embedded.get(page, {page}))
    pages.update(e["commission"]["page"] for e in fetch.get("pending_figures", []))
    pages.update(e["page"] for e in fetch.get("pending_images", []))
    for target in fetch.get("repair_targets", []):
        pages.add(target["page"])
        pages.update(target.get("related", []))
    pages = {p for p in pages if p.startswith("wiki/") and p.endswith(".md") and safefs.is_file(repo, p)}
    topics = set()
    for page in sorted(pages):
        try:
            topic = commissions.topic(repo, page)
            if frontmatter.split(safefs.read_text(repo, topic)).meta.get("type") == "topic":
                topics.add(topic)
        except (ValueError, yaml.YAMLError):
            continue  # The metadata check returns the malformed page to the writer.
    return sorted(topics)


def needed(repo, pages, run_id=None):
    saved = safefs.read_json(repo, PATH, {})
    return [p for p in sorted(set(pages))
            if (not run_id or saved.get(p, {}).get("run_id") != run_id)
            and changed(saved.get(p), content(repo, p))]


def check(repo, result, fetch):
    decisions = result.get("infographic_decisions", [])
    enforce = "infographic_pages" in fetch and fetch.get("mode") in ("fix", "repair")
    pages = assigned(repo, fetch) if decisions or enforce else []
    declared = [d["page"] for d in decisions]
    out = []
    inherited = {e["commission"]["id"] for e in fetch.get("pending_figures", [])}
    inherited.update(e["commission"]["id"] for e in pending.load(repo))
    new = set(fetch.get("infographic_commissions", []))
    new.update(f["id"] for f in result.get("figures", []) if f["kind"] == "infographic" and f["id"] not in inherited)
    if len(new) > 2:
        out.append(item(RESULT, None, "infographic_decisions: at most 2 new infographic commissions per run"))
    if len(declared) != len(set(declared)):
        out.append(item(RESULT, None, "infographic_decisions: duplicate page"))
    required = needed(repo, pages, fetch.get("infographic_run_id", fetch.get("run_id"))) if fetch.get("mode") in ("fix", "repair") else []
    missing = set(required) - set(declared) if "infographic_pages" in fetch and result.get("status") != "question" else set()
    for page in sorted(missing):
        out.append(item(RESULT, None, f"infographic_decisions: missing decision for {page}"))
    for decision in decisions:
        page = decision["page"]
        if page not in pages:
            out.append(item(RESULT, None, f"infographic_decisions: unassigned topic {page}"))
        if "figure_id" in decision:
            matching = [f for f in result.get("figures", []) if f["id"] == decision["figure_id"]
                        and f["page"] == page and f["kind"] == "infographic"]
            if not matching:
                out.append(item(RESULT, None, f"infographic_decisions: {page} needs its infographic commission in figures"))
            elif commissions.candidate(repo, commissions.read(repo, decision["figure_id"]))["state"] == "no-figure":
                out.append(item(RESULT, None, f"infographic_decisions: {page} requested infographic cannot be no-figure"))
    return out


def record(ctx, task, result):
    from ..flows import journal
    journal.settle(ctx, task)
    remember(task, result, ctx.notes_path)
    previous = safefs.read_json(ctx.notes_path, PATH, {})
    saved = dict(previous)
    for decision in result.get("infographic_decisions", []):
        page = decision["page"]
        saved[page] = {**decision, "key": content_key(ctx.notes_path, page),
                       "content": content(ctx.notes_path, page),
                       "run_id": task.get("correction_parent", task.run_id)}
    if saved != previous:
        journal.write(ctx, task, PATH, json.dumps(dict(sorted(saved.items())), ensure_ascii=False, indent=2) + "\n", whole=True)


def remember(task, result, repo):
    inherited = {e["commission"]["id"] for e in task.get("pending_figures", [])}
    inherited.update(e["commission"]["id"] for e in pending.load(repo))
    ids = set(task.get("infographic_commissions", []))
    ids.update(f["id"] for f in result.get("figures", []) if f["kind"] == "infographic" and f["id"] not in inherited)
    task.update(infographic_commissions=sorted(ids))


def generation_gate(ctx, task, plan_id, repair_note=None):
    """Reserve remaining pending attempts before admitting a new generated figure."""
    from ..images import budget, generate, plans
    try:
        brief = commissions.read(ctx.notes_path, plan_id)
    except (ValueError, OSError):
        return None  # The generator returns the actionable commission error.
    inherited = {e["commission"]["id"] for e in task.get("pending_figures", [])}
    inherited.update(e["commission"]["id"] for e in pending.load(ctx.notes_path))
    if plan_id in inherited:
        return None
    ids = set(task.get("infographic_commissions", []))
    if brief["kind"] == "infographic" and plan_id not in ids and len(ids) >= 2:
        return {"state": "disabled", "message": "Futásonként legfeljebb két új infografika-megbízás készülhet."}
    settings = ctx.image_settings()
    ledger = settings.ledger()
    job = ledger.get("jobs", {}).get(plans.job_id(settings.learner, plan_id), {})
    if job.get("accepted") or (generate.awaiting_review(job or {"attempts": []}) and not repair_note):
        if brief["kind"] == "infographic":
            task.update(infographic_commissions=sorted(ids | {plan_id}))
        return None  # Retrieving an existing image spends nothing.
    reserved = 0
    for entry in task.get("pending_figures", []):
        commission = entry["commission"]
        if not pending.generated(ctx.notes_path, commission):
            continue
        job = ledger.get("jobs", {}).get(plans.job_id(settings.learner, commission["id"]), {})
        if job.get("accepted") or generate.awaiting_review(job or {"attempts": []}):
            continue
        reserved += max(0, settings.max_attempts - generate.attempts_used(job or {"attempts": []}))
    amount = (reserved + 1) * settings.reservation_usd
    if not budget.budget_left(ledger, settings.today(), settings.daily_usd, amount, settings.monthly_usd):
        return {"state": "budget-exhausted", "message": "A képkeretben a függő ábrák elsőbbséget kapnak."}
    if brief["kind"] == "infographic":
        task.update(infographic_commissions=sorted(ids | {plan_id}))
    return None
