"""JSONL log (plan 8.6): one object per line, a short readable line on the console."""

from contextlib import contextmanager
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(TZ).date().isoformat()


@dataclass
class Log:
    """Logger bound to one run. Never pass raw output, environment, content or secrets."""

    main: Path | None
    run_id: str = ""
    student: str = ""
    extra_files: list[Path] = field(default_factory=list)
    console: bool = True

    def bind(self, *, run_id: str | None = None, student: str | None = None,
             run_log: Path | None = None) -> "Log":
        files = list(self.extra_files) + ([run_log] if run_log else [])
        return Log(self.main, run_id if run_id is not None else self.run_id,
                   student if student is not None else self.student, files, self.console)

    def event(self, action: str, outcome: str = "ok", *, level: str = "info", step: str = "",
              target: str = "", duration_s: float | None = None, **counts) -> None:
        record = {"ts": now_iso(), "level": level, "run_id": self.run_id, "student": self.student,
                  "step": step, "action": action, "target": target, "outcome": outcome}
        if duration_s is not None:
            record["duration_s"] = round(duration_s, 3)
        record.update(counts)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        for path in [self.main, *self.extra_files]:
            if path is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(line)
        if self.console:
            who = "/".join(x for x in (self.student, self.run_id) if x)
            try:
                print(f"[{who}] {action} {outcome} {target}".rstrip(), file=sys.stderr)
            except (OSError, ValueError):
                pass    # a closed terminal (ended chat session) never stops the work

    def error(self, action: str, exc: BaseException, **counts) -> None:
        tb = exc.__traceback__
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        where = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else ""
        if getattr(exc, "kind", None) == "bad_work" and hasattr(exc, "items"):
            from ..mcp.redact import redact
            problems = sorted(exc.items, key=lambda i: (i["file"], i.get("line") or 0, i["message"]))
            counts["problems"] = redact([{k: i.get(k) for k in ("file", "line", "message")}
                                          for i in problems[:20]])
        self.event(action, "error", level="error", error_class=getattr(exc, "kind", "program"),
                   message=str(exc)[:500], where=where, **counts)


class Timer:
    """`with Timer() as t: ...; t.s` gives the elapsed seconds."""

    def __enter__(self):
        self.start = time.monotonic()
        self.s = 0.0
        return self

    def __exit__(self, *exc):
        self.s = time.monotonic() - self.start
        return False


@contextmanager
def duration(log, action):
    """Measure even interrupted steps; never include their content in the event."""
    started, outcome = time.monotonic(), "error"
    try:
        yield
        outcome = "ok"
    finally:
        log.event(action, outcome, duration_s=time.monotonic() - started)
