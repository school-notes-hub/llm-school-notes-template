"""Process-safe container admission: N slots and an exclusive harness home."""

import fcntl
from contextlib import contextmanager
from pathlib import Path

from ..state.errors import Transient


@contextmanager
def acquire(root: Path, learner: str, home: str, maximum: int):
    root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        volume = open(root / f"{learner}-{home}.lock", "a")
        handles.append(volume)
        try:
            fcntl.flock(volume, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Transient("agent home volume is already in use") from None
        for n in range(maximum):
            slot = open(root / f"slot-{n}.lock", "a")
            try:
                fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                slot.close()
                continue
            handles.append(slot)
            break
        else:
            raise Transient("max_agents reached")
        yield
    finally:
        for handle in reversed(handles):
            handle.close()


def guarded(home):
    """Admission for interactive/login calls; production passes the shared state path."""
    from functools import wraps
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            root = kwargs.pop("lease_dir", None)
            maximum = kwargs.pop("max_agents", 3)
            if root is None:
                return function(*args, **kwargs)
            volume = home or kwargs["role"]
            with acquire(root, kwargs["learner"], volume, maximum):
                return function(*args, **kwargs)
        return call
    return decorate
