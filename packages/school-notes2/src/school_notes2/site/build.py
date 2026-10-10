"""Public site build from a commit (plan 5.10, G5): render, browser check, check-public.

The build reads the commit's own tree (`git archive`), never the worktree, and leaves out
`sources/` and `references/`. The output in `<task>/build/` is exactly what the publish step
later copies to gh-pages.
"""

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..git.run import Git
from ..log import Log, Timer
from ..state.errors import BadWork, NeedsOwner, Transient
from ..state.files import read_json, write_json

PRIVATE_TOP = ("sources", "references")
BUILD_INPUTS = ("wiki", "publication")
CONFIG = "publication/public.json"
PAGE_ERROR = "study-site-page-error "
RENDER_EXIT_PAGE = 3


@dataclass(frozen=True)
class Renderer:
    """Where the study-site lives and what it needs on this machine."""

    study_site: Path          # packages/study-site of the installed release
    browser: Path             # Chromium executable for Mermaid, PDFs and the browser check
    pdf_cache: Path           # state/pdf-cache/<learner>/ (private, outside every repo)
    node: str = "node"
    python: str = "python3"
    build_s: int = 1800
    browser_check_s: int = 900
    check_public_s: int = 300


@dataclass(frozen=True)
class BuildRecord:
    commit: str
    output: Path              # <task>/build; the site itself is output/"site"
    duration_s: float
    pages: int


class BuildContentError(BadWork):
    """The renderer, browser check or check-public found a problem the writer must fix.

    `problems` has the check.json shape: [{file, line, message}].
    """

    def __init__(self, problems: list[dict]):
        super().__init__(f"public build: {len(problems)} content problem(s)",
                         details={"problems": problems})
        self.problems = problems


def existing(task_dir: Path, commit: str) -> BuildRecord | None:
    """The finished build of `commit` in this task, if any (G5 runs once per commit)."""
    record = read_json(task_dir / "build" / "build.json")
    if not record or record.get("commit") != commit:
        return None
    return BuildRecord(commit, task_dir / "build", record["duration_s"], record["pages"])


def build(git: Git, commit: str, task_dir: Path, renderer: Renderer, *, changed: list[str] | None,
          log: Log, browser_filter=None, keep_log: Path | None = None) -> BuildRecord:
    """Build and check the public site of `commit` into `<task>/build`.

    `changed` lists the wiki paths changed since the last publish; the browser check visits
    those pages and their indexes. None means "check every page" (first publish). On a failure
    the steps' `render.log` is copied to `keep_log` (the task folder may be a temporary one) and
    a step failure names that file (sn 0.4.2).
    """
    found = existing(task_dir, commit)
    if found:
        return found
    out = task_dir / "build"
    src = task_dir / "build-src"
    for stale in (out, src):
        shutil.rmtree(stale, ignore_errors=True)
    t = Timer()
    try:
        with t:
            extract(git, commit, src)
            dates = last_updated(git, commit)
            write_json(task_dir / "last-updated.json", dates)
            _render(renderer, src, out, task_dir / "last-updated.json", log)
            payload = read_json(out / "payload.json")
            only = None if changed is None or deleted(changed, src) else pages_to_check(changed, [p["path"] for p in payload["pages"]])
            try:
                _browser_check(renderer, out, payload, only)
            except BuildContentError as exc:
                problems = browser_filter(exc.problems) if browser_filter else exc.problems
                if problems:
                    raise BuildContentError(problems) from None
            _check_public(renderer, out, payload)
    except Exception as exc:
        log.event("site.build", "error", target=commit[:12], duration_s=t.s,
                  error_class=getattr(exc, "kind", type(exc).__name__))
        kept = _keep_log(task_dir / "render.log", keep_log, commit)
        if kept and isinstance(exc, Transient):
            raise Transient(f"{exc.message}\nteljes napló: {kept}", todo=exc.todo, details=exc.details) from exc
        raise
    shutil.rmtree(src, ignore_errors=True)
    record = {"commit": commit, "duration_s": round(t.s, 1), "pages": len(payload["pages"])}
    write_json(out / "build.json", record)  # written last: marks the build complete
    log.event("site.build", target=commit[:12], duration_s=t.s, pages=len(payload["pages"]),
              checked=len(only) if only is not None else len(payload["pages"]))
    return BuildRecord(commit, out, t.s, len(payload["pages"]))


def extract(git: Git, commit: str, dest: Path) -> int:
    """Unpack only what the site is built from (wiki/, publication/); never sources/ or
    references/, and never the large private evidence files (memory on a small VM)."""
    pathspec = ["--", *BUILD_INPUTS]
    data = git.run("archive", "--format=tar", commit, *pathspec, timeout=300).stdout
    count = 0
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar:
            parts = Path(member.name).parts
            if not parts or parts[0] in PRIVATE_TOP or not member.isfile():
                continue
            if member.name.startswith("/") or ".." in parts:
                raise NeedsOwner(f"unsafe path in the commit: {member.name}",
                                 todo="inspect the commit; Git should never hold such a path")
            target = dest / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            count += 1
    return count


def last_updated(git: Git, commit: str) -> dict[str, str]:
    """Per wiki Markdown file: the date of its last commit; the home page gets the latest."""
    out = git.out("log", "--format=@%cI", "--name-only", "--no-renames", commit, "--", "wiki",
                  timeout=300)
    dates: dict[str, str] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("@"):
            current = line[1:]
        elif line.endswith(".md") and line not in dates:
            dates[line] = current
    if dates:
        dates["wiki/index.md"] = max(dates.values(), key=lambda d: datetime.fromisoformat(d))
    return dates


def deleted(changed: list[str], src: Path) -> bool:
    """A wiki page or image that is gone: any unchanged page may link it, so every page is
    checked (a mechanical rule, no link search here)."""
    return any(p.startswith("wiki/") and not (src / p).is_file() for p in changed)


def pages_to_check(changed: list[str], pages: list[str]) -> list[str]:
    """Changed pages plus their subject index and the home page, limited to built pages."""
    wanted = set()
    for path in changed:
        if not (path.startswith("wiki/") and path.endswith(".md")):
            continue
        wanted.add(path)
        parts = path.split("/")
        if len(parts) >= 3:
            wanted.add(f"wiki/{parts[1]}/index.md")
        wanted.add("wiki/index.md")
    return [p for p in pages if p in wanted]


def _run(argv: list[str], *, cwd: Path, timeout: int, log_file: Path, what: str
         ) -> subprocess.CompletedProcess:
    """Run a renderer step; its full output goes to a file in the task, never the main log."""
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout,
                              env=_env(), text=True)
    except subprocess.TimeoutExpired:
        raise Transient(f"{what} timed out after {timeout}s") from None
    with open(log_file, "a", encoding="utf-8") as stream:
        stream.write(f"$ {' '.join(argv[:3])} …\n{proc.stdout}\n{proc.stderr}\n")
    return proc


def _env() -> dict:
    keep = ("PATH", "HOME", "LANG", "FONTCONFIG_FILE", "XDG_CACHE_HOME")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    return env


# The renderer's report of its PDF step (counts from `lib/pdf.mjs`, time from `cli.mjs`): one
# timed line in the JSONL log.
PDF_TIME = re.compile(r"^PDF time: ([\d.]+) s( failed)?$", re.M)
PDF_COUNTS = re.compile(r"^PDFs: (\d+) generated, (\d+) reused$", re.M)


def _render(r: Renderer, src: Path, out: Path, dates: Path, log: Log | None = None) -> None:
    argv = [r.node, str(r.study_site / "cli.mjs"), "build", "--repo", str(src),
            "--config", str(src / CONFIG), "--output", str(out), "--browser", str(r.browser),
            "--pdf-cache", str(r.pdf_cache), "--last-updated", str(dates)]
    proc = _run(argv, cwd=r.study_site, timeout=r.build_s, log_file=out.parent / "render.log",
                what="site render")
    timed, counts = PDF_TIME.search(proc.stdout or ""), PDF_COUNTS.search(proc.stdout or "")
    if timed and log is not None:
        made, reused = (int(counts[1]), int(counts[2])) if counts else (0, 0)
        failed = {"error_class": "bad_work" if proc.returncode == RENDER_EXIT_PAGE else "transient"} if timed[2] else {}
        log.event("site.pdf", "error" if timed[2] else "ok", target=f"{made + reused} pdf", duration_s=float(timed[1]),
                  generated=made, reused=reused, **failed)
    if proc.returncode == RENDER_EXIT_PAGE:
        problems = [_page_problem(line) for line in proc.stderr.splitlines()
                    if line.startswith(PAGE_ERROR)]
        raise BuildContentError(problems or [{"file": CONFIG, "line": None,
                                              "message": "rendering failed on a page"}])
    if proc.returncode != 0:
        raise _step_failed("site render", proc)


def _keep_log(log: Path, keep: Path | None, commit: str) -> Path | None:
    """The failed build's `render.log` at `keep` (one fixed file per learner, the last failure),
    headed by the commit; None when there is nothing to keep or nowhere to keep it."""
    if keep is None or not log.is_file():
        return None
    keep.parent.mkdir(parents=True, exist_ok=True)
    tmp = keep.with_name(keep.name + ".part")
    tmp.write_text(f"# sn publish build of {commit}\n" + log.read_text(encoding="utf-8", errors="replace"),
                   encoding="utf-8")
    tmp.replace(keep)
    return keep


ERROR_LINE = re.compile(r"^(?:[A-Z]\w*)?Error\b")


def error_line(text: str) -> str:
    """The renderer's own error line from its stderr: the last `…Error: …` line (a Node stack's
    head), else the last line that is not a stack frame."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    errors = [line for line in lines if ERROR_LINE.match(line)]
    rest = [line for line in lines if not line.startswith("at ")]
    found = errors[-1] if errors else rest[-1] if rest else ""
    return found[:400]


def _step_failed(what: str, proc: subprocess.CompletedProcess) -> Transient:
    line = error_line(proc.stderr)
    todo = ("nézd meg a teljes naplót" if "Changed input" not in line else
            "a publication/public.json egy lapjának hash-e régi (a lap változott): futtasd az sn close-t "
            "(az írja újra), commitold, majd újra az sn publish-t")
    return Transient(f"{what} failed (rc={proc.returncode})" + (f": {line}" if line else ""), todo=todo)


def _page_problem(line: str) -> dict:
    data = json.loads(line[len(PAGE_ERROR):])
    return {"file": data["file"], "line": None, "message": "public build: " + data["message"]}


def _browser_check(r: Renderer, out: Path, payload: dict, only: list[str] | None) -> None:
    if only == []:
        return
    report = out / "browser-report.json"
    argv = [r.node, str(r.study_site / "check-browser.mjs"), "", str(out / "payload.json"),
            str(r.browser), str(report), ""]
    if only is not None:
        write_json(out / "browser-only.json", only)
        argv.append(str(out / "browser-only.json"))
    with _serve(r, out, payload["base"]) as origin:
        argv[2] = origin
        proc = _run(argv, cwd=r.study_site, timeout=r.browser_check_s,
                    log_file=out.parent / "render.log", what="browser check")
    data = read_json(report)
    if proc.returncode != 0 and not (data and data.get("errors")):
        raise _step_failed("browser check", proc)
    problems = _browser_problems(data["errors"]) if data else []
    if problems:
        raise BuildContentError(problems)


def _browser_problems(errors: list[dict]) -> list[dict]:
    """One problem per page; errors without a page (search, print) name the config file."""
    seen = {}
    for err in errors:
        file = err.get("path") or CONFIG
        kinds = [k for k in ("brokenImages", "missingAnchors", "duplicates") if err.get(k)]
        if err.get("overflow"):
            kinds.append(f"overflow at {err.get('width')}px")
        if err.get("h1", 1) != 1:
            kinds.append("not exactly one H1")
        what = ", ".join(kinds) or err.get("error") or "browser check failed"
        problem = {"file": file, "line": None, "message": f"public build: {what}"}
        if err.get("link"):
            problem["message"] += ": " + err["link"]
            if err.get("target"):
                problem.update(kind="browser-link", target=err["target"])
        seen[(file, problem["message"])] = problem
    return [seen[key] for key in sorted(seen)]


def _check_public(r: Renderer, out: Path, payload: dict) -> None:
    argv = [r.python, str(r.study_site / "check-public.py"), str(out)]
    proc = _run(argv, cwd=r.study_site, timeout=r.check_public_s,
                log_file=out.parent / "render.log", what="check-public")
    data = read_json(out / "privacy-report.json")
    if proc.returncode == 0:
        return
    if not data or not data.get("errors"):
        raise _step_failed("check-public", proc)
    routes = {p["url"]: p["path"] for p in payload["pages"]}
    problems = []
    for err in data["errors"]:
        file = _page_of(err["file"], payload["base"], routes) or f"(public output) {err['file']}"
        problems.append({"file": file, "line": None,
                         "message": f"public output matches forbidden pattern {err['pattern']!r}"})
    raise BuildContentError(problems)


def _page_of(site_file: str, base: str, routes: dict[str, str]) -> str | None:
    if not site_file.endswith("index.html"):
        return None
    url = base + site_file[: -len("index.html")]
    return routes.get(url)


class _serve:
    """`node cli.mjs serve` on a free localhost port for the browser check."""

    def __init__(self, r: Renderer, out: Path, base: str):
        self.argv = [r.node, str(r.study_site / "cli.mjs"), "serve", "--directory",
                     str(out / "site"), "--base", base, "--port", "0"]
        self.cwd = r.study_site
        self.base = base

    def __enter__(self) -> str:
        self.proc = subprocess.Popen(self.argv, cwd=self.cwd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, env=_env())
        deadline = time.monotonic() + 30
        line = ""
        while time.monotonic() < deadline and "http://" not in line:
            line = self.proc.stdout.readline()
            if not line and self.proc.poll() is not None:
                break
        if "http://" not in line:
            self.proc.kill()
            raise Transient("local preview server did not start")
        # The server prints "Local preview: <origin><base>".
        return line.split("Local preview: ", 1)[1].strip().removesuffix(self.base)

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return False
