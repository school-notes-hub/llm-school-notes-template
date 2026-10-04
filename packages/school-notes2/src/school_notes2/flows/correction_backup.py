"""Preserve rejected interactive edits before the replayable P4 rollback."""

from ..git.run import Git
from ..state import safefs


def rejected(repo, root, prefixes, log):
    if safefs.is_file(root, "rejected.patch"):
        return
    paths = sorted({p for prefix in prefixes for p in safefs.walk_files(repo, prefix)})
    previous = set(safefs.walk_files(root, "rejected"))
    for path in sorted(previous - {"rejected/" + p for p in paths}):
        safefs.unlink(root, path)
    (root / "rejected").mkdir(exist_ok=True)
    for path in paths:
        safefs.write_bytes(root, "rejected/" + path, safefs.read_bytes(repo, path))
    git = Git(root / "unused.git", "School Notes", "school-notes@localhost", log)
    diff = git.run("diff", "--no-index", "--binary", "--no-ext-diff", "--no-textconv",
                   "--", "before", "rejected", cwd=root, check=False, timeout=60)
    if diff.returncode not in (0, 1):
        raise RuntimeError("could not preserve rejected correction diff")
    safefs.write_bytes(root, "rejected.patch", diff.stdout)
