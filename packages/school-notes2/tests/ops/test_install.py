"""ops/install.sh takes every configured learner's lock, in configuration order (G-6)."""

import os
import subprocess
from pathlib import Path

import pytest

INSTALL = Path(__file__).resolve().parents[2] / "src/school_notes2/ops/install.sh"
STUDENT = ('repo = "r"\nrepo_key = "k"\nsite_repo = "s"\nsite_key = "k"\n'
           'drive_root = "d"\ngrade = 9\n')


def install(tmp_path, config: str | None, **env):
    """Runs the installer up to its first external step: the template clone is missing, so
    it stops right after taking the locks."""
    path = tmp_path / "config.toml"
    if config is not None:
        path.write_text(config)
    environ = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "SN_ROOT": str(tmp_path / "srv"),
               "SN_TEMPLATE": str(tmp_path / "no-template"), "SN_CONFIG": str(path),
               "XDG_RUNTIME_DIR": str(tmp_path), **env}
    return subprocess.run(["bash", str(INSTALL), "v9.9.9"], env=environ, capture_output=True,
                          text=True, timeout=60)


def test_every_configured_learner_is_locked_in_table_order(tmp_path):
    names = ["proba", "benedek", "barna"]
    done = install(tmp_path, 'email_to = "o@example.com"\n'
                   + "".join(f"\n[students.{n}]\n{STUDENT}" for n in names))
    assert done.returncode != 0          # the missing template clone ends the trial run
    waits = [line.split()[-2] for line in done.stdout.splitlines()
             if line.startswith("waiting for the lock of")]
    assert waits == names
    assert all((tmp_path / "srv/state" / n / "lock").is_file() for n in names)


@pytest.mark.parametrize("config", ['email_to = "o@example.com"\n', None,
                                    '[students."Bad Name"]\nrepo = "r"\n'])
def test_no_usable_learner_list_stops_before_any_lock(tmp_path, config):
    done = install(tmp_path, config)
    assert done.returncode != 0
    assert "waiting for the lock" not in done.stdout
    assert not (tmp_path / "srv/state").exists()
    assert ("no learner configured" in done.stderr or "cannot read the configuration" in done.stderr
            or "lowercase ascii" in done.stderr)


def test_explicit_learner_list_overrides_the_configuration(tmp_path):
    done = install(tmp_path, None, SN_LEARNERS="egy ketto")
    waits = [line.split()[-2] for line in done.stdout.splitlines()
             if line.startswith("waiting for the lock of")]
    assert waits == ["egy", "ketto"]
