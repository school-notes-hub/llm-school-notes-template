"""One lock per learner (plan 7.8): flock on state/<learner>/lock, holder.json for display."""

import fcntl
import os
import time
from pathlib import Path

from ..log import now_iso
from .files import read_json, write_json


class StudentLock:
    """Holds the learner's flock. The fd is inheritable so a detached `finish` keeps it."""

    def __init__(self, state_dir: Path, student: str):
        self.dir = state_dir / student
        self.path = self.dir / "lock"
        self.holder_path = self.dir / "holder.json"
        self.fd: int | None = None

    def try_acquire(self, kind: str) -> bool:
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._held(fd, kind)
        return True

    def probe(self) -> bool:
        """True when nobody holds the lock; holder.json stays untouched."""
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        finally:
            os.close(fd)
        return True

    def acquire(self, kind: str, poll_s: float = 5.0, on_wait=None, timeout_s: float | None = None) -> bool:
        """Blocking acquire for `chat` and `--discard`; `on_wait(holder)` is told who holds it.
        With `timeout_s` it gives up after that long and returns False (fix-52)."""
        told, deadline = False, None if timeout_s is None else time.monotonic() + timeout_s
        while not self.try_acquire(kind):
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if on_wait and not told:
                on_wait(self.holder())
                told = True
            time.sleep(poll_s)
        return True

    def _held(self, fd: int, kind: str) -> None:
        os.set_inheritable(fd, True)
        self.fd = fd
        write_json(self.holder_path, {"pid": os.getpid(), "kind": kind, "since": now_iso()})

    def holder(self) -> dict:
        return read_json(self.holder_path, {}) or {}

    def note(self, kind: str) -> None:
        """Record that another process (e.g. a detached finish) now holds the inherited lock."""
        write_json(self.holder_path, {"pid": os.getpid(), "kind": kind, "since": now_iso()})

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False
