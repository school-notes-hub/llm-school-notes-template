"""Calls into tools/learning_image.py of the installed release.

The OpenRouter key is read from the secrets file at call time and given only to the
child's environment, never on argv (plan 7.2).
"""

import importlib.util
import json
import re
import subprocess
import tempfile
from functools import cache
from pathlib import Path

from ..state import safefs
from .settings import ImageSettings


class ExecutorError(RuntimeError):
    """learning_image.py refused or failed; the message is its own (no secrets)."""


class ExecutorTimeout(ExecutorError):
    pass


def read_key(key_file: Path) -> str:
    """The key file holds the bare key, or is a dotenv file (the ops `.env`) with an
    `OPENROUTER_API_KEY=...` entry among others (quoted or multi-line values included)."""
    from ..local.keys import parse_env
    text = key_file.read_text(encoding="utf-8")
    values = parse_env(text)
    if values.get("OPENROUTER_API_KEY"):
        return values["OPENROUTER_API_KEY"]
    if values:
        raise ExecutorError("OpenRouter key missing in the secrets file")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, value = line.split("=", 1)
            if name.strip() == "OPENROUTER_API_KEY":
                return value.strip().strip("\"'")
            continue
        return line
    raise ExecutorError("OpenRouter key missing in the secrets file")


def call(settings: ImageSettings, command: str, args: list[str], target: str,
         with_key: bool = False, files: dict[str, str] | None = None) -> dict:
    """Run one learning_image.py command; `files` are written next to the config first.

    learning_image.py never sees the worktree: its inputs are staged into a private copy
    with safefs, and what it writes there is copied back with safefs to the allowed places."""
    with tempfile.TemporaryDirectory(prefix="li-", dir=_scratch(settings)) as tmp:
        folder = Path(tmp)
        stage = folder / "repo"
        stage.mkdir()
        job = _job_of(args)
        inputs = stage_inputs(settings.worktree, stage, job) if job else {}
        config = settings.write_executor_config(folder, target, stage)
        for name, text in (files or {}).items():
            (folder / name).write_text(text, encoding="utf-8")
        argv = [settings.python, str(settings.script), "--config", str(config), command,
                *[a.replace("{tmp}", tmp) for a in args]]
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C.UTF-8", "HOME": tmp}
        if with_key:
            env["OPENROUTER_API_KEY"] = read_key(settings.key_file)
        try:
            proc = subprocess.run(argv, env=env, capture_output=True, text=True,
                                  timeout=settings.timeout_s, cwd=tmp)
        except subprocess.TimeoutExpired:
            raise ExecutorTimeout(f"learning_image {command} timed out") from None
        if proc.returncode != 0:
            raise ExecutorError(_error_text(proc.stderr))
        if job:
            copy_back(settings.worktree, stage, job, inputs)
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def _job_of(args: list[str]) -> dict | None:
    """The job file named by `--job` (it lives in the host plans folder, not the worktree)."""
    if "--job" not in args:
        return None
    return json.loads(Path(args[args.index("--job") + 1]).read_text(encoding="utf-8"))


def is_job_asset(rel: str, job_id: str) -> bool:
    """The job's own published image: wiki/assets/…/<id>.<ext> or <id>-r<n>.<ext>, exactly
    (a prefix match would let job `x-a` overwrite `x-ab`)."""
    stem = Path(rel).stem
    return rel.startswith("wiki/assets/") and re.fullmatch(re.escape(job_id) + r"(-r\d+)?", stem) is not None


def stage_inputs(worktree: Path, stage: Path, job: dict) -> dict[str, bytes]:
    """Copy the job's target, sources and existing assets from the worktree (safefs: no link
    is followed), so learning_image.py's own checks (stale source, existing destination)
    see the real state. A missing file is left out."""
    staged = {}
    assets = [rel for rel in safefs.walk_files(worktree, "wiki/assets")
              if is_job_asset(rel, job["id"])]
    for rel in dict.fromkeys([job["target"], *(s["path"] for s in job.get("sources", [])),
                              *assets]):
        try:
            data = safefs.read_bytes(worktree, rel)
        except FileNotFoundError:
            continue
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        staged[rel] = data
    return staged


def copy_back(worktree: Path, stage: Path, job: dict, inputs: dict[str, bytes]) -> list[str]:
    """Copy learning_image.py's outputs into the worktree: only the job's receipt folder and
    its published asset. Everything is validated first and written only then, so a refused
    output never leaves half the receipts behind."""
    receipts = f"docs/evidence/media/{job['id']}/"
    outputs = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file() and not p.is_symlink()):
        rel = path.relative_to(stage).as_posix()
        data = path.read_bytes()
        if inputs.get(rel) == data:
            continue
        asset = is_job_asset(rel, job["id"])
        if not (rel.startswith(receipts) or asset):
            raise ExecutorError(f"learning_image wrote an unexpected file: {rel}")
        if asset and safefs.is_file(worktree, rel) and safefs.read_bytes(worktree, rel) != data:
            raise ExecutorError("Destination exists with different bytes")
        outputs.append((rel, data))
    for rel, data in outputs:
        safefs.write_bytes(worktree, rel, data)
    return [rel for rel, _ in outputs]


def ensure_ledger(settings: ImageSettings, target: str) -> None:
    """Initialize this school year's ledger once (learning_image never resets one)."""
    if not (settings.state_dir / "ledger.json").is_file():
        call(settings, "init-state", [], target)


def _scratch(settings: ImageSettings) -> Path:
    settings.plans_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return settings.plans_dir


def _error_text(stderr: str) -> str:
    for line in reversed(stderr.strip().splitlines()):
        try:
            return str(json.loads(line).get("error", ""))[:500]
        except (json.JSONDecodeError, AttributeError):
            continue
    return "learning_image failed without a structured error"


@cache
def module(script: Path):
    """learning_image.py loaded in-process for its pure encoders (no network)."""
    spec = importlib.util.spec_from_file_location("learning_image_release", script)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded
