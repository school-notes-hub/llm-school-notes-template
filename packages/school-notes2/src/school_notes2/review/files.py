"""Review files `docs/review/<date>-review.md` (plan 4.7): the tool writes every one of them.

The frontmatter (`reviewer`, `range`, `items`, `status`) is machine-only. The body is written
once from review.json and never rewritten; closures are appended as `## Végrehajtva (<run>)`.
"""

from copy import deepcopy
from functools import lru_cache
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..state import safefs
from ..wiki import frontmatter as fm
from . import attempts, relations

REVIEW_DIR = Path("docs/review")
OPEN, OWNER, FIXED, DISAGREE = "open", "owner", "fixed", "disagree"
WORDS = {"fixed": "javítva", "disagree": "nem ért egyet", "open": "nyitva",
         "untouched": "nem érintett", "question": "nyitott kérdés", "settled": "rendezett"}
DONE_HEADING = re.compile(r"^## Végrehajtva \((?P<run>[^)]+)\)$", re.M)
DONE_LINE = re.compile(r"^\* (?P<item>R\d+) – (?P<word>javítva|nem ért egyet|nyitva|nem érintett)",
                       re.M)
ITEM_NUM = re.compile(r"R(\d+)")
# The items as they were before this run's section: lets a repeated finish of the same,
# still uncommitted run replace its own section instead of skipping a corrected result.
BEFORE = re.compile(r"^<!-- school-notes:before (?P<items>\{.*\}) -->$", re.M)


class ClosureError(ValueError):
    """A closure names a file or item that does not exist or is not open."""


@dataclass
class ClosureOutcome:
    written: list[str] = field(default_factory=list)       # repo paths the tool changed
    new_owner: list[dict] = field(default_factory=list)    # [{file, item_id}] e-mail once


def compute_status(items: dict) -> str:
    return "open" if any(v in (OPEN, OWNER) for v in items.values()) else "closed"


def next_path(repo: Path, date: str) -> Path:
    """`<date>-review.md`, then `-2`, `-3` for further reviews on the same day."""
    base = repo / REVIEW_DIR
    candidate, n = base / f"{date}-review.md", 2
    while safefs.exists(repo, _rel(repo, candidate)):
        candidate, n = base / f"{date}-review-{n}.md", n + 1
    return candidate


def _rel(repo: Path, path: Path) -> str:
    return safefs.rel_of(repo, path)


def _read(repo: Path, path: Path) -> str:
    """Review files live in the worktree: never read through a planted symlink (7.6)."""
    return safefs.read_text(repo, _rel(repo, path))


def _write(repo: Path, path: Path, text: str) -> None:
    safefs.write_text(repo, _rel(repo, path), text)


def _location(finding: dict) -> str:
    line = finding.get("line")
    return f"{finding['file']}:{line}" if line else finding["file"]


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def render_body(date: str, review: dict, frm: str, to: str) -> str:
    verdict = "rendben" if review["verdict"] == "ok" else "javítást kér"
    out = [f"# Review – {date}", "",
           f"Tartomány: `{frm[:12]}..{to[:12]}`. Értékelés: {verdict}.", ""]
    if review["findings"]:
        out += ["## Megállapítások", ""]
    previous_topic = None
    for f in review["findings"]:
        if f.get("topic") and f["topic"] != previous_topic:
            previous_topic = f["topic"]
            out += [f"## Témakör: {previous_topic}", ""]
        out += [f"### {f['id']} – {_location(f)}", "", f"**Probléma:** {f['problem']}", ""]
        if f.get("suggestion"):
            out += [f"**Javaslat:** {f['suggestion']}", ""]
    for topic in review.get("topics", []):
        if not topic["findings"]:
            out += [f"## Témakör: {topic['topic']}", "",
                    f"{topic['mode']}: {topic['status']}.", ""]
    if review.get("figures"):
        out += ["## Ábrák", ""]
    for fig in review.get("figures", []):
        out += [f"### {fig['file']} ({fig['page']})", "", f"**Ítélet:** {fig['verdict']}", "",
                f"**Megfigyelés:** {fig['observed']}", ""]
        if fig.get("description"):
            out += [f"**Leírás:** {fig['description']}", ""]
    if review.get("family_questions"):
        out += ["## Családi kérdések", ""] + [f"* {_one_line(q)}" for q in review["family_questions"]] + [""]
    if review.get("owner_notes"):
        out += ["## Tulajdonosi észrevételek", ""] + [f"* {_one_line(n)}" for n in review["owner_notes"]] + [""]
    return "\n".join(out)


def _with_frontmatter(body: str, reviewer: str, frm: str, to: str, items: dict) -> str:
    values = {"reviewer": reviewer, "range": {"from": frm, "to": to}, "items": items,
              "status": compute_status(items), "repair_policy": 1}
    return fm.set_keys("\n" + body, values)


def write_review(repo: Path, date: str, review: dict, reviewer: str, frm: str, to: str, *,
                 path: Path | None = None, known: dict | None = None, write=None) -> Path:
    """A new review file from a validated review.json; returns its path."""
    from ..reader.report import advice_notes
    findings, notes = advice_notes(review["findings"], review.get("owner_notes", []))
    review = {**review, "findings": findings, "owner_notes": notes}
    if not review["findings"]:
        review["verdict"] = "ok"
    ids = [f["id"] for f in review["findings"]]
    if len(set(ids)) != len(ids):
        raise ValueError("review.json: duplicate finding ids")
    path = path or next_path(repo, date)
    known = relations.inventory(repo) if known is None else known
    active, pending, items, records = [], [], {}, {}
    for f in sorted(review["findings"], key=lambda f: _num(f["id"])):
        status, unlocated = relations.route(f, known)
        if status == "pending":
            pending.append(f)
            continue
        chain = max(f.get("chain", 0), relations.chain(f, known))
        active.append(f)
        items[f["id"]] = status
        records[f["id"]] = {"file": f["file"], "round": 1, "chain": chain,
                            **attempts.inherited(f, known),
                            "origin": f.get("origin", "nightly"), "category": f.get("category"), "severity": "hiba",
                            "relates_to": f.get("relates_to"), "unlocated": unlocated or f.get("unlocated", False),
                            **{k: f[k] for k in ("quote", "hit_id", "figure_id", "outside_assignment") if k in f}}
    body = render_body(date, {**review, "findings": active}, frm, to)
    if pending:
        body += "\n## Függő (nyitott kérdésre vár)\n\n" + "\n".join(
            f"* {_one_line(f['file'])}: {_one_line(f['problem'])}" for f in pending) + "\n"
    text = _with_frontmatter(body, reviewer, frm, to, items)
    output = fm.set_keys(text, {"item_details": records})
    if write is None:
        _write(repo, path, output)
    else:
        write(repo, _rel(repo, path), output)
    return path


def write_timeout_report(repo: Path, date: str, commit: str, parent: str, reviewer: str,
                         run_id: str) -> Path:
    """`--discard review`: the commit is closed as not reviewed (plan 5.6/6)."""
    path = next_path(repo, date)
    body = (f"# Review – {date}\n\nNem átnézve: időtúllépés. A `{commit}` commit két egymást "
            f"követő éjszakán is kifutott a review időkorlátjából; a tulajdonos eldobta "
            f"(futás: {run_id}).\n")
    _write(repo, path, _with_frontmatter(body, reviewer, parent, commit, {}))
    return path


def _num(item_id: str) -> int:
    return int(ITEM_NUM.fullmatch(item_id).group(1))


@lru_cache(maxsize=4096)
def _parsed_report(text):
    # Content keys cannot go stale on a rebase or a same-size rewrite.
    return fm.split(text)


def parse_report(text):
    # Callers may mutate their document; never expose the cached object itself.
    return deepcopy(_parsed_report(text))


def read_report(repo: Path, path: Path):
    try:
        return parse_report(_read(repo, path))
    except (ValueError, OSError):
        return None


def read_items(repo: Path, path: Path) -> dict | None:
    """The `items` map of a v2 review file; None for files without it (v1 files, index)."""
    page = read_report(repo, path)
    items = page.meta.get("items") if page else None
    return items if isinstance(items, dict) else None


def review_files(repo: Path) -> list[Path]:
    return [repo / rel for rel in safefs.glob(repo, REVIEW_DIR, f"{REVIEW_DIR}/**/*.md")
            if not rel.endswith("/index.md")]


def open_items(repo: Path, mode: str) -> list[dict]:
    """fetch.json `open_review_items`: cron leaves out `owner` items, interactive keeps them."""
    wanted = (OPEN,) if mode == "cron" else (OPEN, OWNER)
    found = []
    for path in review_files(repo):
        page = read_report(repo, path)
        if page is None or not isinstance(page.meta.get("items"), dict):
            continue
        items = page.meta["items"]
        rel = path.relative_to(repo).as_posix()
        for i in sorted(items, key=_num):
            detail = relations.details(page, i)
            if items[i] in wanted:
                found.append({"file": rel, "item_id": i, "key": f"{rel}#{i}", "status": items[i],
                              "round": detail["round"], "chain": detail["chain"]})
    return found


def open_counts(text: str) -> dict[str, int]:
    """How many times each item stayed open or untouched across all Végrehajtva sections."""
    counts: dict[str, int] = {}
    for section in DONE_HEADING.split(text)[2::2]:
        for m in DONE_LINE.finditer(section):
            if m.group("word") in (WORDS["open"], WORDS["untouched"]):
                counts[m.group("item")] = counts.get(m.group("item"), 0) + 1
    return counts


def _done_section(run_id: str, entries: list[tuple[str, str, str]], before: dict) -> str:
    lines = [f"## Végrehajtva ({run_id})", "",
             f"<!-- school-notes:before {json.dumps(before, sort_keys=True)} -->", ""]
    for item, status, note in entries:
        word = WORDS[status]
        lines.append(f"* {item} – {word}: {_one_line(note)}" if note else f"* {item} – {word}")
    return "\n".join(lines) + "\n"


def _without_own_section(body: str, items: dict, run_id: str) -> tuple[str, dict]:
    """Drop this run's earlier section and restore the items it changed (a rerun)."""
    heading = next((m for m in DONE_HEADING.finditer(body) if m.group("run") == run_id), None)
    if heading is None:
        return body, items
    nxt = re.compile(r"^## ", re.M).search(body, heading.end())
    end = nxt.start() if nxt else len(body)
    section = body[heading.start():end]
    before = BEFORE.search(section)
    if before is None:
        raise ClosureError(f"run {run_id} already closed items in this file without a "
                           "recorded previous state; it cannot be applied twice")
    restored = dict(items)
    restored.update(json.loads(before.group("items")))
    return (body[:heading.start()].rstrip("\n") + "\n" + body[end:]).rstrip("\n") + "\n", restored


def _apply_one(repo: Path, path: Path, run_id: str, closures: dict, listed: list[str],
               owner_after: int, automatic: bool) -> list[str]:
    """Update one file; returns its newly-owner items. Repeating it for the same run
    replaces that run's section (the closures may have changed since)."""
    text = _read(repo, path)
    page = fm.split(text)
    body, items = _without_own_section(page.body, dict(page.meta["items"]), run_id)
    for item_id, c in closures.items():
        problems = relations.closure_problems(repo, c, page=page)
        if problems:
            raise ClosureError("; ".join(problems))
        if item_id not in items:
            raise ClosureError(f"{path.name}: no item {item_id}")
        if items[item_id] not in (OPEN, OWNER):
            raise ClosureError(f"{path.name}: {item_id} is not open ({items[item_id]})")
    touched = sorted(set(closures) | set(listed), key=_num)
    before = {i: items[i] for i in touched if i in items}
    entries = []
    details = dict(page.meta.get("item_details", {}))
    for item_id in touched:
        c = closures.get(item_id)
        status = c["status"] if c else "untouched"
        note = c.get("note", "") if c else ""
        if c:
            note = " ".join(filter(None, [note, c.get("question_id"), c.get("decision_id")]))
        entries.append((item_id, status, note))
        record = dict(details.get(item_id, relations.details(page, item_id)))
        if automatic and item_id in before:
            attempts.record(record, run_id)
        details[item_id] = record
        if status in (FIXED, DISAGREE, "question", "settled"):
            items[item_id] = status
            record.pop("recheck", None)
            details[item_id] = record
    body = body.rstrip("\n") + "\n\n" + _done_section(run_id, entries, before)
    counts = open_counts(body)
    new_owner = [i for i, s in items.items() if s == OPEN and (
        attempts.failed_status(details[i]) == OWNER if "repair_attempts" in details.get(i, {})
        else counts.get(i, 0) >= owner_after)]
    for item_id in new_owner:
        items[item_id] = OWNER
    new_text = fm.set_keys(f"---\n{page.raw_meta}\n---\n{body}",
                           {"items": items, "item_details": details, "status": compute_status(items)})
    if new_text != text:
        _write(repo, path, new_text)
    return new_owner


def apply_closure(repo: Path, run_id: str, closures: list[dict], listed: list[dict],
                  owner_after: int = 5, *, automatic: bool = False) -> ClosureOutcome:
    """Apply the merged `review_closure` and the fetch.json item list (plan 4.7, 5.7)."""
    by_file: dict[str, dict] = {}
    for c in closures:
        by_file.setdefault(c["file"], {})[c["item_id"]] = c
    listed_by_file: dict[str, list[str]] = {}
    for item in listed:
        listed_by_file.setdefault(item["file"], []).append(item["item_id"])
    outcome = ClosureOutcome()
    for rel in sorted(set(by_file) | set(listed_by_file)):
        path = repo / rel
        if not rel.startswith("docs/review/") or not safefs.is_file(repo, rel) \
                or read_items(repo, path) is None:
            raise ClosureError(f"{rel}: not a review file with items")
        owners = _apply_one(repo, path, run_id, by_file.get(rel, {}), listed_by_file.get(rel, []),
                            owner_after, automatic)
        outcome.written.append(rel)
        outcome.new_owner += [{"file": rel, "item_id": i} for i in owners]
    return outcome
