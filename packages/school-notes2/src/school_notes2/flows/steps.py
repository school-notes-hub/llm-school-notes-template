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
from ..wiki import order as wiki_order
from ..wiki.check_result import check_result
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
    return [c["path"] for c in workbranch.changed_files(ctx.worktree("notes"), base_of(task))]


def base_reader(ctx: Ctx, task: Task):
    def read(path):
        old = ctx.worktree("notes").run("show", f"{base_of(task)}:{path}", check=False)
        return old.stdout if old.returncode == 0 else None
    return read


def guard_step(ctx: Ctx, task: Task) -> None:
    """Step 1: the path guard. Owner-class violations stop the run; others go back."""
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
    if found:
        # A legacy YAML error can also prevent the guard's machine-field comparison.
        # Classify it before sending an unrepairable violation back to the writer.
        from . import learning
        try:
            learning.validate(ctx, task)
        except CheckFailed:
            pass  # New metadata defects are reported by the content check itself.
        raise CheckFailed([wiki_check.item(v.path, None, v.message) for v in found])


def order_step(ctx: Ctx, task: Task) -> list[dict]:
    """Cron runs keep the order of existing chapters, lessons, topics and pages;
    an interactive session may re-order on purpose."""
    if task.mode == "interactive":
        return []
    wt = ctx.worktree("notes")
    out = []
    for rel in changed_paths(ctx, task):
        if not (rel.startswith("wiki/") and rel.endswith(".md")) or not safefs.is_file(
                ctx.notes_path, rel):
            continue
        old = wt.run("show", f"{base_of(task)}:{rel}", check=False)
        if old.returncode != 0:
            continue
        new = safefs.read_text(ctx.notes_path, rel)
        out += [wiki_check.item(rel, None, m) for m in
                wiki_order.problems(rel, old.stdout.decode("utf-8", "replace"), new)]
    return out


def merged_result(ctx: Ctx, task: Task) -> dict:
    """Step 2: the saved result-<k>.json files. A session's own result.json stands for the
    range it worked on (writing_k); in a session earlier ranges are optional (5.8)."""
    n = len(task.get("ranges"))
    if task.mode == "interactive":
        own = safefs.read_json(ctx.notes_path, f"{workbranch.WORKDIR}/result.json")
        if own is not None:
            validate("result", own)
            problems = checks.accounting(task, own)
            if problems:
                raise CheckFailed(problems)
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
    """Steps 1–6. Raises CheckFailed (back to the writer) or NeedsOwner.

    Closures and evidence are written only after the check passed, so a run sent back to
    the writer never leaves a stale closure (both writers replace their own run's part)."""
    guard_step(ctx, task)
    from . import learning
    learning.validate(ctx, task)
    reordered = order_step(ctx, task)
    if reordered:
        raise CheckFailed(reordered)
    result = merged_result(ctx, task)
    repo = ctx.notes_path
    fetch = fetch_flow.fetch_json(task, len(task.get("ranges")), grade=ctx.student.grade, repo=ctx.notes_path,
                                  whole_run=True)
    listed = fetch["open_review_items"]
    problems = check_result(repo, result, fetch, {(i["file"], i["item_id"]) for i in listed},
                            ctx.cfg.limits.review_closures_per_run, base_content=base_reader(ctx, task),
                            generated=lambda rel: generation_receipts.rights(ctx)(rel))
    if wiki_check.errors(problems):
        raise CheckFailed(problems)
    check_changed(ctx, task, result=result)  # Validate author text before any tool stamp.
    by, at = _writer_label(ctx), now_iso()
    parts = machine.write_lesson_notes(repo, result.get("notes", []), fetch,
                                       ctx.student.grade, by, at)
    parts += machine.stamp_generated(repo, changed_paths(ctx, task), by, at)
    machine.add_subjects(repo, result.get("new_subjects", []), _drive_names(task))
    _record_writes(task, repo, whole=[], parts=parts)
    check_changed(ctx, task, result=result)
    outcome = review_files.apply_closure(repo, task.run_id, result.get("review_closure", []),
                                         listed, ctx.cfg.limits.owner_after_open)
    evidence = records.append(repo, records.from_writer(result.get("checks", [])),
                              run_id=task.run_id, checker=by, at=at, fetch_pages=fetch["pages"])
    _record_writes(task, repo, whole=outcome.written + evidence, parts=[])
    from . import licensing
    licensing.refresh(ctx, task, result, fetch["pages"])
    generation_receipts.refresh(ctx, task)
    generate_all(ctx, task)
    return Prepared(result, result["status"] == "question", outcome.new_owner)


def regenerate(ctx: Ctx, task: Task) -> None:
    """Steps 5–6 again on a rebased tree (G4)."""
    check_changed(ctx, task)
    generate_all(ctx, task)
    from .review_phases import final_keys
    final_keys(ctx, task)


def check_items(ctx: Ctx, task: Task) -> list[dict]:
    """Only author changes incur content checks; generated parts cannot widen the scope."""
    from . import learning
    today = learning.observation_date(task)
    learning.validate(ctx, task)
    paths = sorted(llm_snapshot(ctx, task))
    from ..repair import check as repair_check
    items = repair_check.problems(ctx, task, paths)
    inherited = repair_check.inherited_learning_problems(ctx, task, paths)
    items += [i for i in wiki_check.check_files(ctx.notes_path, paths, today=today)
              if (i["file"], i["message"]) not in inherited]
    checks.tool_errors(ctx, task, items)
    return checks.identify(items + checks.source_warnings(ctx, task, changed_paths(ctx, task)), ctx.notes_path)


def check_changed(ctx: Ctx, task: Task, *, result: dict | None = None) -> None:
    """Step 5: the mechanical check of the run's changed files."""
    items = check_items(ctx, task)
    errors = wiki_check.errors(items)
    if errors:
        raise CheckFailed(errors)
    if result is None:
        result = writer.merge(writer.results(task, required=False))
    write_check_items(ctx, checks.after_writer(ctx, task, result, items))


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
    (e.g. the final ⏳ notices) must call it again, or the site build sees a stale hash."""
    repo = ctx.notes_path
    try:
        value = public.build(repo, public.either(public.render_rights(repo),
                                                public.media_receipt_rights(repo)))
        text = public.dumps(value)
        if not safefs.is_file(repo, "publication/public.json") or safefs.read_text(repo, "publication/public.json") != text:
            journal.write(ctx, task, "publication/public.json", text, whole=True)
    except public.PublicError as exc:
        problems = [wiki_check.item(p, None, exc.reason) for p in exc.paths]
        checks.tool_errors(ctx, task, problems)
        raise CheckFailed(problems)


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
    task.update(tool_writes=files, tool_parts=tool_parts, tool_hashes=hashes)


def _writer_label(ctx: Ctx) -> str:
    role, _ = ctx.cfg.role("writer")
    return f"{role.model}/{role.effort}"


def _drive_names(task: Task) -> dict[str, str]:
    return {p["subject"]: p["drive_folder"] for p in task.get("packages", [])}


def llm_snapshot(ctx: Ctx, task: Task) -> dict:
    """The writer's own changes, as hashes without the tool's parts (5.4/9 race guard).

    A file whose LLM-written part equals the base is left out, so the tool's own writes
    (machine keys, generated blocks, whole tool files) never look like an edit."""
    wt = ctx.worktree("notes")
    base = base_of(task)
    out = {}
    for c in workbranch.changed_files(wt, base):
        rel = c["path"]
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
