"""Bare clones and durable worktrees (plan 6.2). Created once, checked at every job start."""

from .run import Git

# No `+`: a rewritten remote history makes the fetch fail instead of silently moving.
# An exact refspec fails when the remote ref is missing, so refs that may not exist yet
# (claude-reviewed before the cut-over, gh-pages before the first release) are fetched
# only by the step that needs them.
GH_PAGES_SPEC = "refs/heads/gh-pages:refs/remotes/origin/gh-pages"


def fetch(git: Git, timeout: float, *specs: str) -> None:
    """Fetch the configured refs, or exactly `specs` when given."""
    git.run("fetch", "--no-tags", "origin", *specs, timeout=timeout)


def rev(git: Git, ref: str) -> str:
    return git.out("rev-parse", "--verify", ref).strip()


def ls_remote(git: Git, ref: str, timeout: float) -> str | None:
    out = git.out("ls-remote", "origin", ref, timeout=timeout).strip()
    return out.split()[0] if out else None
