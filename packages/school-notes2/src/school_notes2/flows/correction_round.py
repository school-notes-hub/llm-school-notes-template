"""Round-local checkpoints, with the first pre-upgrade round kept in place."""

from ..state import safefs
from .inspection_runtime import folder


def number(task):
    return task.get("correction_round", 1)


def identity(task):
    if task.get("correction_round") is None and (folder(task) / "correction").exists():
        return f"{task.run_id}-fix-a{task.get('attempt', 1)}"
    return f"{task.run_id}-fix-r{number(task)}"


def root(task):
    base = folder(task)
    legacy = base / "correction"
    return legacy if number(task) == 1 and (legacy.exists() or task.mode == "interactive") else base / f"correction-r{number(task)}"


def p5(task):
    base = folder(task)
    return "p5.json" if number(task) == 1 and safefs.is_file(base, "p5.json") else f"p5-r{number(task)}.json"


def reader(task, slug):
    base = folder(task) / "reader" / slug
    legacy = base / "recheck"
    return legacy if number(task) == 1 and legacy.exists() else base / f"recheck-r{number(task)}"
