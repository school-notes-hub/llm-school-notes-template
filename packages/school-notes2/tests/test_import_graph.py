"""The package is the local command line and nothing else (local pipeline plan 4.1).

Walks every import (module level and inside functions) from `cli.py` and `local/`; nothing
reachable may be a VM-era module, every imported package module must exist, and no module of
the package may be left unreachable (a module nothing imports is dead code)."""

import ast
from pathlib import Path

import school_notes2

SRC = Path(school_notes2.__file__).resolve().parent
PKG = "school_notes2"
FORBIDDEN = ("flows", "mcp", "llm", "notify", "repair", "container", "ops", "reader", "review",
             "state.phase", "state.lock", "migration")


def modules() -> dict[str, Path]:
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        parts = [PKG, *path.relative_to(SRC).with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    return found


def imports(name: str, path: Path, known: dict[str, Path]) -> set[str]:
    """Package modules `name` imports: `from x import y` counts x, and x.y when y is a module."""
    base = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names if a.name.split(".")[0] == PKG]
        elif isinstance(node, ast.ImportFrom):
            module = ".".join(base[:len(base) - node.level + 1] + ([node.module] if node.module else [])) \
                if node.level else (node.module or "")
            if module.split(".")[0] != PKG:
                continue
            targets = [module] + [f"{module}.{a.name}" for a in node.names if f"{module}.{a.name}" in known]
        else:
            continue
        for target in targets:
            parts = target.split(".")
            out.update(".".join(parts[:i]) for i in range(2, len(parts) + 1))
    return out


def reachable() -> tuple[dict[str, str | None], set[str]]:
    """(module → the module that first imported it, imported names that are no module)."""
    known = modules()
    starts = sorted(m for m in known if m == PKG or m in (f"{PKG}.cli", f"{PKG}.__main__")
                    or m.startswith(f"{PKG}.local"))
    seen: dict[str, str | None] = {}
    missing = set()
    stack = [(m, None) for m in reversed(starts)]
    while stack:
        name, parent = stack.pop()
        if name in seen:
            continue
        if name not in known:
            if not (SRC.parent / name.replace(".", "/")).is_dir():     # a namespace package is fine
                missing.add(f"{parent} → {name}")
            continue
        seen[name] = parent
        stack += [(t, name) for t in sorted(imports(name, known[name], known), reverse=True)]
    return seen, missing


def chain(seen, name):
    out = []
    while name:
        out.append(name)
        name = seen[name]
    return " ← ".join(out)


def test_nothing_reachable_is_a_vm_module():
    seen, _ = reachable()
    bad = [chain(seen, m) for m in sorted(seen)
           if any(m == f"{PKG}.{f}" or m.startswith(f"{PKG}.{f}.") for f in FORBIDDEN)]
    assert bad == []


def test_every_imported_module_exists():
    _, missing = reachable()
    assert sorted(missing) == []


def test_no_module_is_left_unreachable():
    seen, _ = reachable()
    assert sorted(set(modules()) - set(seen)) == []


def test_the_vm_packages_are_gone():
    assert [f for f in FORBIDDEN if (SRC / f.replace(".", "/")).exists()
            or (SRC / (f.replace(".", "/") + ".py")).exists()] == []
