import pytest

from school_notes2 import config
from school_notes2.flows import context, setup
from school_notes2.state.errors import NeedsOwner
from tests.conftest import make_origin


def make_cfg(tmp_path, private, site, learner="benedek"):
    return config.parse({
        "root": str(tmp_path / "srv"), "secrets_dir": str(tmp_path / "secrets"),
        "email_to": "o@example.com", "git": {"name": "O", "email": "o@example.com"},
        "students": {learner: {"repo": str(private), "repo_key": "/nonexistent",
                               "site_repo": str(site), "site_key": "/nonexistent",
                               "drive_root": "id", "grade": 9}},
        "harnesses": {"fake": {"headless": ["x"], "interactive": ["x"], "login_check": ["true"]}},
        "roles": {"writer": {"harness": "fake", "model": "m", "effort": "high", "timeout_s": 1},
                  "reviewer": {"harness": "fake", "model": "m", "effort": "high", "timeout_s": 1}},
    })


@pytest.mark.parametrize("learner", ["benedek", "barna", "proba"])
def test_setup_creates_bares_and_worktrees_and_ensure_detects_swap(tmp_path, local_origin, learner):
    (tmp_path / "p").mkdir()
    (tmp_path / "s").mkdir()
    private = make_origin(tmp_path / "p", {"wiki/index.md": "# W\n"})
    site = make_origin(tmp_path / "s", {"README.md": "site\n"})
    ctx = context.make(make_cfg(tmp_path, private, site, learner), learner, console=False)
    setup.setup(ctx)
    root = tmp_path / "srv"
    assert (root / f"work/{learner}/notes/wiki/index.md").exists()
    assert (root / f"work/{learner}/site/README.md").exists()
    setup.ensure(ctx)
    (root / f"work/{learner}/review/.git").write_text("gitdir: /elsewhere\n")
    with pytest.raises(NeedsOwner):
        setup.ensure(ctx)


def test_ensure_before_setup_needs_owner(tmp_path):
    ctx = context.make(make_cfg(tmp_path, tmp_path, tmp_path), "benedek", console=False)
    with pytest.raises(NeedsOwner, match="not set up"):
        setup.ensure(ctx)
