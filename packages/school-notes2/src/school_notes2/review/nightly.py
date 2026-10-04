"""Nightly review, tool side of preparation (plan 5.6/1–3, 6.9/1).

Two Git objects are passed in: `repo` is the bare clone (fetch, rev-list, diff, push) and
`wt` is the review worktree (its own linked gitdir plus --work-tree, for switch/commit).
The LLM launch is not here; the orchestrator runs the reviewer between prepare and close.
"""

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from ..git import repos
from ..git.run import Git, with_retries
from ..schemas import validate
from ..state import phase
from ..state.errors import BadWork, NeedsOwner, Transient
from ..sources.order import natural_key
from ..state import safefs
from ..state.files import read_json, write_bytes, write_json, write_text
from ..wiki import markers
from . import relations

DIFF_PATHS = ("wiki", "docs/review", "docs/evidence/pages")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
RASTER_EXT = IMAGE_EXT - {".svg"}
MARKER_REF = "refs/remotes/origin/claude-reviewed"
MAIN_REF = "refs/remotes/origin/main"
ACTIVE = ("reviewed", "closing", "pushing")

Rasterize = Callable[[list[Path], Path], list[Path]]


@dataclass
class Range:
    base: str                 # origin/claude-reviewed
    head: str                 # H = origin/main
    end: str                  # T: the last commit taken (H, or earlier when a limit cut)
    commits: list[str]
    patch: str
    images: list[dict] = field(default_factory=list)


def fetch(repo: Git, timeout: float) -> None:
    """Fetch main and the marker explicitly; a missing marker is the owner's step (6.9/4)."""
    def step():
        try:
            repos.fetch(repo, timeout, repos.MAIN_SPEC, repos.REVIEWED_SPEC)
        except (Transient, NeedsOwner) as exc:
            if "couldn't find remote ref" in str(exc):
                raise NeedsOwner("claude-reviewed marker not created yet on origin",
                                 todo="create it once at the cut-over (plan 6.9/4)") from None
            raise
    with_retries(step, log=repo.log)


def rev(repo: Git, ref: str) -> str:
    """The commit SHA of `ref`, or "" when the ref does not exist."""
    proc = repo.run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return proc.stdout.decode().strip() if proc.returncode == 0 else ""


def changed(repo: Git, a: str, b: str, paths: tuple[str, ...]) -> list[tuple[str, str]]:
    """[(status, path)] between two commits, renames off (6.3)."""
    raw = repo.out("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-status",
                   "-z", a, b, "--", *paths)
    parts = raw.split("\0")
    return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def blob(repo: Git, commit: str, path: str) -> bytes:
    return repo.run("cat-file", "blob", f"{commit}:{path}").stdout


def _text(data: bytes, path: str) -> list[str] | None:
    if PurePosixPath(path).suffix.lower() in IMAGE_EXT or b"\0" in data:
        return None
    text = data.decode("utf-8", "replace")
    return (markers.empty_all(text) if path.endswith(".md") else text).splitlines(keepends=True)


def build_patch(repo: Git, a: str, b: str) -> str:
    """Unified diff of the reviewed paths with generated blocks emptied (plan 5.6/3)."""
    out = []
    for status, path in changed(repo, a, b, DIFF_PATHS):
        old = blob(repo, a, path) if status != "A" else b""
        new = blob(repo, b, path) if status != "D" else b""
        old_lines, new_lines = _text(old, path), _text(new, path)
        if old_lines is None or new_lines is None:
            out.append(f"Binary file {path} ({status})\n")
            continue
        diff = list(difflib.unified_diff(old_lines, new_lines,
                                         "/dev/null" if status == "A" else f"a/{path}",
                                         "/dev/null" if status == "D" else f"b/{path}"))
        out.append("".join(line if line.endswith("\n") else line + "\n" for line in diff))
    return "".join(out)


def images(repo: Git, a: str, b: str) -> list[dict]:
    """New source images and new/changed figures, in natural path order (4.3)."""
    found = []
    for status, path in changed(repo, a, b, ("sources", "wiki/assets")):
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in IMAGE_EXT or status == "D":
            continue
        if path.startswith("sources/") and status != "A":
            continue
        found.append({"path": path, "kind": "source" if path.startswith("sources/") else "figure"})
    return sorted(found, key=lambda img: natural_key(img["path"]))     # 4.3: 2 before 10


def select(repo: Git, *, fetch_timeout: float) -> Range | None:
    """Pin the entire range. D60's image/diff and D85's commit caps are removed."""
    fetch(repo, fetch_timeout)
    base, head = rev(repo, MARKER_REF), rev(repo, MAIN_REF)
    if not base:
        raise NeedsOwner("claude-reviewed marker missing", todo="create it once (plan 6.9/4)")
    if not repo.ok("merge-base", "--is-ancestor", base, head):
        raise NeedsOwner("origin/claude-reviewed is not an ancestor of origin/main",
                         todo="check the claude-reviewed branch on GitHub")
    commits = repo.out("rev-list", "--reverse", "--topo-order", f"{base}..{head}").split()
    return Range(base, head, head, commits, "") if commits else None


def write_input(repo: Git, wt: Git, rng: Range, in_dir: Path, rasterize: Rasterize) -> None:
    """Review worktree at T; diff.patch, the images and images.json into the input folder."""
    wt.run("switch", "--detach", "--discard-changes", rng.end)
    out_dir = in_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(in_dir / "diff.patch", rng.patch, 0o644)
    listing, svgs = [], []
    for n, img in enumerate(rng.images, start=1):
        name = f"{n:03d}-{PurePosixPath(img['path']).name}"
        if PurePosixPath(img["path"]).suffix.lower() in RASTER_EXT:
            write_bytes(out_dir / name, blob(repo, rng.end, img["path"]), 0o644)
            listing.append({**img, "file": f"images/{name}"})
        else:
            svg = in_dir / "svg" / name
            write_bytes(svg, blob(repo, rng.end, img["path"]), 0o644)
            svgs.append(svg)
            listing.append({**img, "file": f"images/{Path(name).with_suffix('.png').name}"})
    if svgs:
        rasterize(svgs, out_dir)  # network-less container (plan 5.6/3), never on the host
    write_json(in_dir / "images.json", listing, 0o644)
    write_json(in_dir / "relations.json", relations.reviewer_inventory(wt.work_tree), 0o644)


def prepare(root: Path, student: str, repo: Git, wt: Git, *, fetch_timeout: float,
            rasterize: Rasterize, max_agents: int = 3):
    rng = select(repo, fetch_timeout=fetch_timeout)
    if rng is None:
        return None
    task = phase.create(root, student, "review", "cron", "prepared")
    task.update(base=rng.base, H=rng.head, T=rng.head, commits=rng.commits,
                topic_review=True, max_agents=max_agents)
    resume_prepared(task, repo, wt, rasterize)
    return task


def resume_prepared(task: phase.Task, repo: Git, wt: Git, rasterize: Rasterize) -> None:
    """Recover the pinned tree even after a partial report was committed."""
    wt.run("switch", "--detach", "--discard-changes", task.get("H"))
    if task.get("topic_review"):
        from . import topics
        if task.get("units") is None:
            state = topics.read_state(repo, task.get("H"))
            grouped, skipped = topics.plan(repo, wt.work_tree, task.get("base"), task.get("H"), state)
            task.update(units=grouped, nightly_state=state, skipped_topics=skipped,
                        blocked_topics=state.get("blocked_topics", []), input_ready=True)
        return
    base, end = task.get("base"), task.get("T")
    rng = Range(base, task.get("H"), end, task.get("commits"), build_patch(repo, base, end),
                images(repo, base, end))
    write_input(repo, wt, rng, task.dir / "in", rasterize)
    task.update(input_ready=True)


def _page_exists(worktree: Path, page: str) -> bool:
    try:
        return safefs.is_file(worktree, page)
    except safefs.UnsafePath:
        return False


def record_review(task: phase.Task, review: dict, worktree: Path | None = None) -> None:
    """A valid review.json closes the LLM part; from here on no LLM call is needed.

    Figures that name no existing wiki page or no reviewed image cannot become evidence:
    they are dropped (listed in the task as `dropped_figures`) instead of failing the close
    every night. The image may be the input name (`images/003-x.png`) or a repo path."""
    validate("review", review)
    known = relations.inventory(worktree) if worktree is not None else {"pages": {}, "items": {}}
    for finding in review["findings"]:
        page = known["pages"].get(finding["file"], {})
        if finding.get("relates_to") in page.get("decisions", []) and not finding.get("new_evidence", "").strip():
            raise BadWork(f"review.json: {finding['id']}: a decision reference requires new_evidence")
    responses, dropped_responses = relations.valid_responses(review.get("responses", []), known)
    kept, dropped = _valid_figures(task, review.get("figures") or [], worktree)
    review = {**review, "figures": kept, "responses": responses}
    write_json(task.dir / "review.json", review)
    task.set_phase("reviewed", dropped_figures=dropped, dropped_responses=dropped_responses)


def _valid_figures(task: phase.Task, figures: list[dict], worktree: Path | None):
    listing = read_json(task.dir / "in" / "images.json", []) or []
    by_input = {img["file"]: img["path"] for img in listing}
    reviewed = {img["path"] for img in listing}
    kept, dropped = [], []
    for fig in figures:
        path = by_input.get(fig["file"], fig["file"])
        page = fig["page"]
        page_ok = (page.startswith("wiki/") and page.endswith(".md") and ".." not in page
                   and (worktree is None or _page_exists(worktree, page)))
        if page_ok and path in reviewed:
            kept.append({**fig, "file": path})
        else:
            dropped.append({"file": fig["file"], "page": page})
    return kept, dropped


def pending_close(tasks: list[phase.Task]) -> phase.Task | None:
    """An earlier review whose review.json is valid but whose closing did not finish."""
    for task in tasks:
        if task.kind == "review" and task.open and task.phase in ACTIVE:
            return task
    return None


def load_review(task: phase.Task) -> dict:
    review = json.loads((task.dir / "review.json").read_text(encoding="utf-8"))
    if task.get("topic_review"):
        return review  # Tool-assembled from separately validated topic receipts.
    # Already saved reports from the previous contract remain resumable.
    legacy = {**review, "findings": [{"relates_to": None, **{
        k: v for k, v in f.items() if k not in ("origin", "chain", "unlocated")}}
        for f in review["findings"]]}
    legacy.pop("family_questions", None)
    validate("review", legacy)
    return {**legacy, **({"family_questions": review["family_questions"]}
                       if "family_questions" in review else {})}
