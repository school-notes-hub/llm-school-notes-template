"""JSONL log: one object per line (`logs/school-notes.log`), optionally a short readable line
on the console. Never pass raw output, environment, content or secrets."""

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


@dataclass
class Log:
    """`main` None: a quiet log (the library functions' events go nowhere).

    `steps`: a step log – only these actions are written, each as one small line with its
    `seconds` and only numeric counts besides (no message, no stderr, no content)."""

    main: Path | None
    student: str = ""
    console: bool = True
    steps: tuple[str, ...] | None = None

    def event(self, action: str, outcome: str = "ok", *, level: str = "info",
              target: str = "", duration_s: float | None = None, **counts) -> None:
        if self.steps is not None:
            if action not in self.steps:
                return
            counts = {k: v for k, v in counts.items()
                      if k == "error_class" or (isinstance(v, (int, float)) and not isinstance(v, bool))}
        record = {"ts": now_iso(), "level": level, "student": self.student,
                  "action": action, "target": target, "outcome": outcome}
        if duration_s is not None:
            record["seconds" if self.steps is not None else "duration_s"] = round(duration_s, 3)
        record.update(counts)
        if self.main is not None:
            self.main.parent.mkdir(parents=True, exist_ok=True)
            with open(self.main, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.console:
            try:
                print(f"[{self.student}] {action} {outcome} {target}".rstrip(), file=sys.stderr)
            except (OSError, ValueError):
                pass    # a closed terminal never stops the work


class Timer:
    """`with Timer() as t: ...; t.s` gives the elapsed seconds."""

    def __enter__(self):
        self.start = time.monotonic()
        self.s = 0.0
        return self

    def __exit__(self, *exc):
        self.s = time.monotonic() - self.start
        return False
