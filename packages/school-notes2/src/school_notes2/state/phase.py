"""Task folders and phase.json (plan 4.11, 8.2): the only run state besides Git."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..log import TZ, now_iso
from ..schemas import validate
from .files import read_json, write_json

SCHEMA = 1
NOTES_PHASES = ("downloading", "downloaded", "moved", "prepared", "writing", "finishing",
                "figures", "inspecting", "correcting", "rechecking", "review_ready",
                "waiting_quota", "committed", "built", "pushing", "pushed", "done")
REVIEW_PHASES = ("prepared", "reviewing", "waiting_quota", "reviewed", "closing", "pushing", "done")
PUBLISH_PHASES = ("prepared", "built", "pushing", "done")


def new_run_id(prefix: str = "") -> str:
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}{stamp}-{secrets.token_hex(2)}"


@dataclass
class Task:
    """One task folder: tasks/<student>/<run_id>/ with phase.json inside."""

    dir: Path
    data: dict

    @property
    def run_id(self) -> str:
        return self.data["run_id"]

    @property
    def phase(self) -> str:
        return self.data["phase"]

    @property
    def kind(self) -> str:
        return self.data["kind"]

    @property
    def mode(self) -> str:
        return self.data["mode"]

    @property
    def path(self) -> Path:
        return self.dir / "phase.json"

    def reload(self) -> None:
        """Take over what another holder of this run wrote meanwhile (the MCP handlers load
        and save the run themselves, e.g. the tool's own writes on image acceptance)."""
        fresh = load(self.dir)
        if fresh is not None:
            self.data = fresh.data

    def save(self) -> None:
        self.data["updated"] = now_iso()
        validate("phase", self.data)
        write_json(self.path, self.data)

    def set_phase(self, phase: str, **fields) -> None:
        """Record the phase BEFORE the external action it names (8.2)."""
        self.data["phase"] = phase
        self.data["data"].update(fields)
        self.save()

    def update(self, **fields) -> None:
        self.data["data"].update(fields)
        self.save()

    def get(self, key: str, default=None):
        return self.data["data"].get(key, default)

    @property
    def open(self) -> bool:
        return self.phase != "done" and not self.data.get("closed")

    def mark_needs_owner(self, reason: str, todo: str, error_class: str) -> None:
        self.data["needs_owner"] = {"reason": reason, "todo": todo, "class": error_class,
                                    "at": now_iso()}
        self.save()

    def clear_needs_owner(self) -> None:
        if self.data.get("needs_owner"):
            self.data["data"]["completion_generation"] = self.get("completion_generation", 0) + 1
            # The next run mail reports only the resumed segment (owner, 2026-10-05).
            self.data["data"]["resumed_at"] = now_iso()
            self.data["data"]["active_at_resume"] = self.get("active_seconds", 0)
        self.data["needs_owner"] = None
        self.data["retries"] = 0
        self.data["llm_failures"] = 0
        self.save()

    def record_error(self, error_class: str, message: str) -> None:
        self.data["last_error"] = {"class": error_class, "message": message[:500], "at": now_iso()}
        self.save()


def tasks_dir(root: Path, student: str) -> Path:
    return root / "tasks" / student


def create(root: Path, student: str, kind: str, mode: str, phase: str,
           run_id: str | None = None) -> Task:
    run_id = run_id or new_run_id("review-" if kind == "review" else
                                  "publish-" if kind == "publish" else "")
    folder = tasks_dir(root, student) / run_id
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    data = {"schema": SCHEMA, "kind": kind, "mode": mode, "student": student, "run_id": run_id,
            "phase": phase, "created": now_iso(), "updated": now_iso(), "data": {},
            "retries": 0, "llm_failures": 0, "finish_task": None, "needs_owner": None,
            "last_error": None}
    if kind == "notes":
        data["data"]["infographic_policy"] = True
    task = Task(folder, data)
    task.save()
    return task


def load(folder: Path) -> Task | None:
    data = read_json(folder / "phase.json")
    if data is None:
        return None
    if data.get("schema", 0) > SCHEMA:
        raise RuntimeError(f"{folder}: phase.json schema {data['schema']} is newer than this tool")
    validate("phase", data)
    return Task(folder, data)


def all_tasks(root: Path, student: str) -> list[Task]:
    base = tasks_dir(root, student)
    if not base.is_dir():
        return []
    found = (load(p) for p in sorted(base.iterdir()) if p.is_dir())
    return [t for t in found if t is not None]


def open_task(root: Path, student: str, kind: str) -> Task | None:
    """The open task of a kind; there is at most one per learner and kind."""
    candidates = [t for t in all_tasks(root, student) if t.kind == kind and t.open]
    if len(candidates) > 1:
        raise RuntimeError(f"{student}: more than one open {kind} task: "
                           + ", ".join(t.run_id for t in candidates))
    return candidates[0] if candidates else None
