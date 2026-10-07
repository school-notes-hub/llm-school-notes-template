"""Plain parameters of the image wrapper; the orchestrator fills them from the config."""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..log import TZ
from ..state.files import write_json


def school_year(day: date) -> str:
    """The ledger's request_id: one ledger per school year (September to August)."""
    start = day.year if day.month >= 9 else day.year - 1
    return f"school-year-{start}-{start + 1}"


def budapest_today() -> date:
    return datetime.now(TZ).date()


@dataclass(frozen=True)
class ImageSettings:
    learner: str
    worktree: Path            # the learner's notes worktree (/work in the container)
    script: Path              # tools/learning_image.py of the installed release
    state_root: Path          # state/images/ (one ledger folder per school year below)
    plans_root: Path          # state/image-plans/ (kept plans, per learner below)
    lock_path: Path           # state/images.lock, shared by all learners
    key_file: Path            # secrets/openrouter.key
    max_total_usd: Decimal    # school-year safety cap over all learners
    learner_max_usd: Decimal  # school-year safety cap per learner
    monthly_usd: Decimal = Decimal("10")
    reservation_usd: Decimal = Decimal("0.05")
    max_attempts: int = 3
    timeout_s: int = 600
    lock_timeout_s: int = 600
    python: str = sys.executable
    today: Callable[[], date] = field(default=budapest_today)

    @property
    def request_id(self) -> str:
        return school_year(self.today())

    def previous_year(self) -> "ImageSettings":
        """The same settings on the previous school year's ledger."""
        start = int(self.request_id.split("-")[2])
        day = date(start - 1, 9, 1)
        return replace(self, today=lambda: day)

    @property
    def state_dir(self) -> Path:
        return self.state_root / self.request_id

    @property
    def plans_dir(self) -> Path:
        return self.plans_root / self.learner

    @property
    def work_images(self) -> Path:
        return self.worktree / ".school-notes" / "images"

    def ledger(self) -> dict:
        path = self.state_dir / "ledger.json"
        if not path.is_file():
            return {"request_id": self.request_id, "jobs": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_executor_config(self, folder: Path, target: str, repo: Path) -> Path:
        """learning_image.py's config for one call; it allows exactly one target file.

        `repo` is a host-private staging copy, never the worktree: learning_image.py opens
        files by path and would follow a link the container planted (S6)."""
        path = folder / "learning-images.json"
        write_json(path, {
            "request_id": self.request_id, "state_dir": str(self.state_dir),
            "max_total_usd": str(self.max_total_usd), "reservation_usd": str(self.reservation_usd),
            "max_attempts": self.max_attempts,
            "learners": {self.learner: {"repo": str(repo), "targets": [target],
                                        "max_usd": str(self.learner_max_usd)}}})
        return path
