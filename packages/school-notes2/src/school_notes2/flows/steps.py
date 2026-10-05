"""`finish` steps 1–6 (plan 5.4): guard, results, machine fields, closures, evidence,
check, generation. Steps 5–6 also run after a rebase (G4) and for the MCP `check`."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..evidence import records
from ..git import workbranch
from ..log import now_iso
from ..mcp.redact import redact
from ..review import files as review_files
from ..review import index as review_index
from ..schemas import validate
from ..state.errors import BadWork, NeedsOwner
from ..state import safefs
from ..state.files import write_json
from ..state.phase import Task
from ..wiki.author import part as _llm_part
from ..wiki import check as wiki_check
from ..wiki import generate, guard, machine, public
from ..wiki.check_result import check_result, committed_image
from . import generation_receipts
from . import fetch as fetch_flow
from . import checks, journal, writer
from .context import Ctx

TOOL_WHOLE_FILES = ("tools/subjects.json", "publication/public.json", "docs/review/index.md")


class CheckFailed(BadWork):
    """The writer must fix check.json items (back to the writer, 8.2)."""

    def __init__(self, items: list[dict]):
        super().__init__(f"check found {len(items)} problem(s)", details={"items": items})
        self.items = items


@dataclass
class Prepared:
    result: dict
    question: bool
    new_owner: list[dict] = field(default_factory=list)


def base_of(task: Task) -> str:
    """What the run's changes are measured against: the recorded base, or – while the owner
    resolves a rebase conflict – HEAD, the new upstream the run is being replayed onto."""
    return "HEAD" if task.get("rebase") == "conflict" else task.get("base")


def changed_paths(ctx: Ctx, task: Task) -> list[str]:
    read = base_reader(ctx, task)
    return [c["path"] for c in workbranch.changed_files(ctx.worktree("notes"), base_of(task))
            if not safefs.is_file(ctx.notes_path, c["path"])
            or read(c["path"]) != safefs.read_bytes(ctx.notes_path, c["path"])]


def base_reader(ctx: Ctx, task: Task):
    def read(path):
        old = ctx.worktree("notes").run("show", f"{base_of(task)}:{path}", check=False)
        return old.stdout if old.returncode == 0 else None
    return read


def guard_step(ctx: Ctx, task: Task) -> None:
    """Step 1: the path guard, after the tool's own bytes were restored mechanically.
    Owner-class violations stop the run; others go back to the writer."""
    from . import protected
    protected.restore(ctx, task)
    wt = ctx.worktree("notes")
    base = base_of(task)
    changes = [guard.Change(c["path"], c["status"])
               for c in workbranch.changed_files(wt, base)]

    def base_content(path: str) -> bytes | None:
        proc = wt.run("show", f"{base}:{path}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    found = guard.run(guard.GuardInput(
        worktree=ctx.notes_path, changes=changes, base_content=base_content,
        tool_files=task.get("tool_writes", {}), tool_parts=task.get("tool_parts", {}),
        interactive=task.mode == "interactive",
        conflict_files=frozenset(task.get("conflict_files", [])),
        pending_write=task.get("learning_pending"),
        git_file=task.get("dot_git", "").encode("utf-8") or None))
    owner = [v for v in found if v.owner]
    if owner:
        raise NeedsOwner("path guard: " + "; ".join(f"{v.path}: {v.message}" for v in owner[:5]),
                         todo="inspect the worktree in `school-notes chat`")
    if found:  # The path guard protects (Maradjon): such output is unusable until fixed.
        raise CheckFailed([wiki_check.item(v.path, None, v.message, kind=wiki_check.BLOCKING) for v in found])


def merged_result(ctx: Ctx, task: Task) -> dict:
    """Step 2: the saved result-<k>.json files. A session's own result.json stands for the
    range it worked on (writing_k); in a session earlier ranges are optional (5.8)."""
    n = len(task.get("ranges"))
    if task.mode == "interactive":
        own = safefs.read_json(ctx.notes_path, f"{workbranch.WORKDIR}/result.json")
        if own is not None:
            validate("result", own)
            write_json(task.dir / f"result-{min(task.get('writing_k', n), n)}.json", own)
    if task.get("skip_writer"):
        return {"status": "done"}
    found = writer.results(task, required=task.mode != "interactive")
    if not found:
        if task.mode == "interactive" and not any(not p["duplicate_of"]
                                                  for p in task.get("pages", [])):
            return {"status": "done"}     # free editing in a session needs no result.json
        raise BadWork("no result.json for this run")
    result = writer.merge(found)
    if result["owner_notes"]:
        ctx.log.event("writer.owner_notes", notes=redact(result["owner_notes"]))
    return result


def content_steps(ctx: Ctx, task: Task) -> Prepared:
    """Steps 1–6. The writer's finished work is always applied and kept.

    A session gets every error back (CheckFailed). In cron, a blocking problem (a secret,
    unprocessable metadata) stops for the owner with the work kept; every other remaining
    error becomes an item for the next run and the run goes on."""
    problems = []
    try:
        guard_step(ctx, task)
    except CheckFailed as exc:
        problems += exc.items
    result = merged_result(ctx, task)
    repo = ctx.notes_path
    fetch = fetch_flow.fetch_json(task, len(task.get("ranges")), grade=ctx.student.grade, repo=ctx.notes_path,
                                  whole_run=True)
    listed = fetch["open_review_items"]
    from . import correction_calls
    fetch = correction_calls.successful_fetch(ctx, task, fetch)
    problems += wiki_check.errors(check_result(
        repo, result, fetch, {(i["file"], i["item_id"]) for i in listed},
        ctx.cfg.limits.review_closures_per_run, base_content=base_reader(ctx, task),
        generated=lambda rel: generation_receipts.rights(ctx)(rel)))
    problems += wiki_check.errors(check_items(ctx, task))
    if problems and task.mode == "interactive":
        raise CheckFailed(problems)
    stop = wiki_check.blocking(problems)
    if stop:
        raise NeedsOwner("unusable content remains after the writer's calls; the work is kept",
                         todo="fix the listed problems in `school-notes chat`", details={"items": stop[:20]})
    result, dropped = usable(ctx, task, result, fetch, listed)
    from ..reader import new_pages
    by, at = _writer_label(ctx), now_iso()
    parts = machine.write_lesson_notes(repo, result.get("notes", []), fetch,
                                       ctx.student.grade, by, at)
    parts += machine.stamp_generated(repo, sorted(llm_snapshot(ctx, task)), by, at)
    machine.add_subjects(repo, result.get("new_subjects", []), _drive_names(task))
    _record_writes(task, repo, whole=[], parts=parts)
    new_pages.record(ctx, task)  # Lesson type is supplied by machine.write_lesson_notes.
    outcome = review_files.apply_closure(repo, task.run_id, result.get("review_closure", []),
                                         listed, ctx.cfg.limits.owner_after_open,
                                         automatic=task.mode == "cron" and task.get("mode") == "fix")
    evidence = records.append(repo, records.from_writer(result.get("checks", [])),
                              run_id=task.run_id, checker=by, at=at, fetch_pages=fetch["pages"])
    _record_writes(task, repo, whole=outcome.written + evidence, parts=[])
    from . import licensing
    licensing.refresh(ctx, task, result, fetch["pages"])
    generation_receipts.refresh(ctx, task)
    generation_receipts.refresh_svgs(ctx, task)
    generate_all(ctx, task)
    if problems or dropped:
        from . import machine_findings
        machine_findings.record(ctx, task, problems)
        task.update(content_problems=checks.ordered(problems), dropped_result=dropped)
        ctx.log.event("finish.problems_to_items", errors=len(problems), dropped=len(dropped))
    return Prepared(result, result["status"] == "question", outcome.new_owner)


def usable(ctx: Ctx, task: Task, result: dict, fetch: dict, listed: list[dict]) -> tuple[dict, list[str]]:
    """Keep every valid part of the result; an invalid or unproven part is left out.

    An invalid closure leaves its item open. A `fixed` closure whose page text did not change
    (R6) leaves it open too, but counts as a repair attempt, so the attempt brake takes the
    item to the owner instead of parking it forever. Invalid evidence checks and new-subject
    entries are dropped and logged."""
    from ..review.relations import closure_problems, inventory
    repo, dropped = ctx.notes_path, []
    known = inventory(repo)["items"]
    open_keys = {(i["file"], i["item_id"]) for i in listed}
    read = base_reader(ctx, task)
    closures = []
    for c in result.get("review_closure", []):
        key = (c["file"], c["item_id"])
        problems = closure_problems(repo, c) if safefs.is_file(repo, c["file"]) else ["missing report"]
        if key not in open_keys or problems:
            dropped.append(f"review_closure {c['file']}#{c['item_id']}: " + "; ".join(problems or ["not assigned"]))
            continue
        page = known.get(c["file"] + "#" + c["item_id"], {}).get("file")
        if c["status"] == "fixed" and page and safefs.is_file(repo, page) and read(page) == safefs.read_bytes(repo, page):
            dropped.append(f"review_closure {c['file']}#{c['item_id']}: fixed without a text change; stays open")
            closures.append({"file": c["file"], "item_id": c["item_id"], "status": "open", "attempt": True,
                             "note": "fixed without a text change; stays open"})
            continue
        closures.append(c)
    seqs = {p["seq"] for p in fetch["pages"]}
    checks_ = [c for c in result.get("checks", []) if safefs.is_file(repo, c["page"]) and (
        int(c["image"]) in seqs if isinstance(c["image"], int) or str(c["image"]).isdigit()
        else committed_image(repo, str(c["image"])))]
    new = {p["subject"] for p in fetch["packages"] if p.get("new_subject")}
    subjects = [s for s in result.get("new_subjects") or [] if s["subject"] in new]
    dropped += [f"checks: {c['page']} {c['image']}" for c in result.get("checks", []) if c not in checks_]
    dropped += [f"new_subjects: {s['subject']}" for s in result.get("new_subjects") or [] if s not in subjects]
    if dropped:
        ctx.log.event("finish.result_dropped", "warning", items=dropped)
    return {**result, "review_closure": closures, "checks": checks_, "new_subjects": subjects}, dropped


def regenerate(ctx: Ctx, task: Task) -> None:
    """Steps 5–6 again on a rebased tree (G4). A remaining error becomes an item."""
    problems = wiki_check.errors(check_items(ctx, task))
    if problems and task.mode == "interactive":
        raise CheckFailed(problems)
    if wiki_check.blocking(problems):
        raise NeedsOwner("unusable content after the rebase; the work is kept",
                         todo="fix the listed problems in `school-notes chat`", details={"items": problems[:20]})
    if problems:
        from . import machine_findings
        machine_findings.record(ctx, task, problems)
    generate_all(ctx, task)
    from .review_phases import final_keys
    final_keys(ctx, task)


def check_items(ctx: Ctx, task: Task) -> list[dict]:
    """Only author changes incur content checks; an error that already existed on the
    page in the base does not block (it is a warning, never an item)."""
    from . import learning, inherited_check
    today = learning.observation_date(task)
    problems = learning.validate(ctx, task)
    paths = sorted(set(llm_snapshot(ctx, task)) | set(_linking_deleted(ctx, task)))
    items = inherited_check.classify(ctx, task, wiki_check.check_files(ctx.notes_path, paths, today=today))
    checks.tool_errors(ctx, task, items)
    return checks.identify(problems + items, ctx.notes_path)


def _linking_deleted(ctx: Ctx, task: Task) -> list[str]:
    """A page deleted or renamed by the writer is allowed; pages linking it are checked."""
    from ..wiki.pages import links, resolve, wiki_pages
    gone = {c["path"] for c in workbranch.changed_files(ctx.worktree("notes"), base_of(task))
            if c["status"] == "deleted" and c["path"].startswith("wiki/")}
    if not gone:
        return []
    return [rel for rel in sorted(wiki_pages(ctx.notes_path))
            if any(resolve(rel, link.target.split("#", 1)[0]) in gone
                   for link in links(safefs.read_text(ctx.notes_path, rel)))]


def check_changed(ctx: Ctx, task: Task, *, result: dict | None = None) -> None:
    """Step 5: the mechanical check of the run's changed files."""
    items = check_items(ctx, task)
    errors = wiki_check.errors(items)
    if errors:
        raise CheckFailed(errors)
    write_check_items(ctx, [i for i in items if i.get("severity") == "warning"])


def generate_all(ctx: Ctx, task: Task) -> None:
    """Step 6: indexes, public.json and the review index."""
    repo = ctx.notes_path
    from . import learning
    learning.refresh(ctx, task)
    from ..figures import licenses
    licenses.preflight(repo)
    indexes = generate.write_indexes(repo)
    # Recorded at once: if a later step stops the run, the next check must still know that
    # these generated blocks are the tool's own writes.
    _record_writes(task, repo, whole=[], parts=indexes)
    write_public(ctx, task)
    review_index.update(repo)
    _record_writes(task, repo, whole=list(TOOL_WHOLE_FILES), parts=indexes)


def write_public(ctx: Ctx, task: Task) -> None:
    """publication/public.json from the pages as they are now; every later page write
    (e.g. the final ⏳ notices) must call it again, or the site build sees a stale hash.

    A refused asset (no rights record, a source copy) goes back to a session; in cron it
    becomes an item for the next run, public.json stays as it was and G5 holds the release."""
    repo = ctx.notes_path
    try:
        value = public.build(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                                public.writer_svg_rights(repo)))
        text = public.dumps(value)
        if not safefs.is_file(repo, "publication/public.json") or safefs.read_text(repo, "publication/public.json") != text:
            journal.write(ctx, task, "publication/public.json", text, whole=True)
        if task.get("public_problems"):
            task.update(public_problems=None)
    except public.PublicError as exc:
        problems = [wiki_check.item(p, None, exc.reason) for p in exc.paths]
        checks.tool_errors(ctx, task, problems)
        if task.mode == "interactive":
            raise CheckFailed(problems)
        from . import machine_findings
        machine_findings.record(ctx, task, problems)
        task.update(public_problems=checks.ordered(problems))
        ctx.log.event("finish.public_held", "warning", problems=problems[:20])


def write_check_items(ctx: Ctx, items: list[dict]) -> None:
    items = checks.identify(items, ctx.notes_path)
    validate("check", items)
    safefs.write_json(ctx.notes_path, f"{workbranch.WORKDIR}/check.json", items)


def is_llm_writable(rel: str) -> bool:
    """wiki/ pages may be edited by the writer after the tool wrote them, so the guard checks
    only their machine parts; everything else the tool writes is pinned as a whole file."""
    return rel.startswith("wiki/") and not rel.startswith("wiki/assets/")


def rerecord(ctx: Ctx, task: Task, merged: list[str]) -> None:
    """After Git merged files during a conflicted rebase (6.7): the tool's earlier writes and
    the cleanly merged files are recorded as they are now, so only the owner's resolution of
    the conflicting files is judged by the guard."""
    known = set(task.get("tool_writes", {})) | set(task.get("tool_parts", {})) | set(merged)
    present = [rel for rel in sorted(known) if safefs.is_file(ctx.notes_path, rel)]
    record_tool_files(task, ctx.notes_path, present)


def record_tool_files(task: Task, repo: Path, written: list[str]) -> None:
    """Record the tool's own writes for the path guard (5.4/1)."""
    whole = [r for r in written if not is_llm_writable(r)]
    parts = [r for r in written if is_llm_writable(r)]
    _record_writes(task, repo, whole=whole, parts=parts)


def _record_writes(task: Task, repo: Path, *, whole: list[str], parts: list[str]) -> None:
    files = dict(task.get("tool_writes", {}))
    for rel in whole:
        if safefs.is_file(repo, rel):
            files[rel] = hashlib.sha256(safefs.read_bytes(repo, rel)).hexdigest()
    tool_parts = dict(task.get("tool_parts", {}))
    for rel in parts:
        if safefs.is_file(repo, rel):
            tool_parts[rel] = guard.parts_hash(safefs.read_text(repo, rel))
    hashes = dict(task.get("tool_hashes", {}))
    for rel in sorted(set(whole + parts)):
        if safefs.is_file(repo, rel):
            hashes[rel] = hashlib.sha256(safefs.read_bytes(repo, rel)).hexdigest()
    from . import protected
    originals = protected.remember(task, repo, whole + parts)
    task.update(tool_writes=files, tool_parts=tool_parts, tool_hashes=hashes, tool_originals=originals)


def _writer_label(ctx: Ctx) -> str:
    role, _ = ctx.cfg.role("writer")
    return f"{role.model}/{role.effort}"


def _drive_names(task: Task) -> dict[str, str]:
    """A new subject's display name is its Drive subject folder (e.g. "Történelem"), never the
    package folder (e.g. "2026-10-03"); the slug is the last resort."""
    subjects = {i["package"]["name"]: i["package"].get("subject_name")
                for i in task.get("selected", []) if isinstance(i.get("package"), dict)}
    return {p["subject"]: subjects.get(p["drive_folder"]) or p["subject"]
            for p in task.get("packages", [])}


def llm_snapshot(ctx: Ctx, task: Task) -> dict:
    """The writer's own changes, as hashes without the tool's parts (5.4/9 race guard).

    A file whose LLM-written part equals the base is left out, so the tool's own writes
    (machine keys, generated blocks, whole tool files) never look like an edit."""
    wt = ctx.worktree("notes")
    base = base_of(task)
    out = {}
    for rel in changed_paths(ctx, task):
        if rel in task.get("tool_writes", {}):
            continue
        path = ctx.notes_path / rel
        now = _llm_hash(rel, safefs.read_bytes(ctx.notes_path, rel)) \
            if safefs.is_file(ctx.notes_path, rel) else None
        old = wt.run("show", f"{base}:{rel}", check=False)
        if old.returncode == 0 and now == _llm_hash(rel, old.stdout):
            continue
        out[rel] = now
    return out


def _llm_hash(rel: str, data: bytes) -> str:
    data = data.replace(b"\r\n", b"\n").rstrip(b"\n")   # the check's own auto-fixes
    if rel.endswith(".md"):
        data = _llm_part(data.decode("utf-8", "replace")).encode("utf-8").rstrip(b"\n")
    return hashlib.sha256(data).hexdigest()
