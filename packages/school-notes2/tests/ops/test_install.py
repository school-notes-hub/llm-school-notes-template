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
    environ = {k: v for k, v in environ.items() if v is not None}     # None: left unset
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


@pytest.mark.parametrize("explicit", [True, False])
def test_open_task_check_reads_the_configuration_that_chose_the_locks(tmp_path, explicit):
    """A rollback to an installed tag reaches `verify-tasks`: it gets the configuration the
    learner list came from (SN_CONFIG, else the default path), never another one."""
    default = tmp_path / ".config/school-notes/config.toml"
    default.parent.mkdir(parents=True)
    default.write_text("".join(f"\n[students.{n}]\n{STUDENT}" for n in ("egy", "ketto")))
    release = tmp_path / "srv/releases/v9.9.9"
    (release / "bin").mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    (release / "bin/school-notes").write_text(f'#!/bin/sh\necho "$@" >> {calls}\n')
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "podman").write_text("#!/bin/sh\nexit 0\n")       # the image already exists
    for script in (release / "bin/school-notes", fake / "podman"):
        script.chmod(0o755)
    env = {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    if explicit:
        done = install(tmp_path, f"\n[students.proba]\n{STUDENT}", **env)
        used, locked = tmp_path / "config.toml", ["proba"]
    else:
        done = install(tmp_path, None, SN_CONFIG=None, **env)
        used, locked = default, ["egy", "ketto"]
    assert done.returncode == 0, done.stderr
    waits = [line.split()[-2] for line in done.stdout.splitlines()
             if line.startswith("waiting for the lock of")]
    assert waits == locked
    assert calls.read_text() == f"--config {used} verify-tasks\n"
    assert (tmp_path / "srv/current").resolve() == release.resolve()


def test_a_python_without_tomllib_gets_a_plain_message(tmp_path):
    """Before `uv sync` the system python3 reads the configuration; tomllib is 3.11+."""
    old = tmp_path / "old-python"
    old.mkdir()
    (old / "tomllib.py").write_text('raise ImportError("no tomllib before Python 3.11")\n')
    done = install(tmp_path, f"\n[students.proba]\n{STUDENT}", PYTHONPATH=str(old))
    assert done.returncode != 0 and "Traceback" not in done.stderr
    assert "python3 >= 3.11 (tomllib) is required" in done.stderr
    assert not (tmp_path / "srv/state").exists()


def test_install_waits_for_round_vm_lock_before_taking_learner_locks(tmp_path):
    import fcntl
    import select
    vm = tmp_path / "srv/state/operations/vm/lock"
    vm.parent.mkdir(parents=True)
    with vm.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        env = {**os.environ, "SN_ROOT": str(tmp_path / "srv"), "SN_LEARNERS": "benedek barna",
               "SN_TEMPLATE": str(tmp_path / "missing-template")}
        proc = subprocess.Popen(["bash", str(INSTALL), "v9.9.9"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert select.select([proc.stdout], [], [], 5)[0]
            assert proc.stdout.readline().strip() == "waiting for the VM lock ..."
            assert proc.poll() is None
            assert not (tmp_path / "srv/state/benedek/lock").exists()
            fcntl.flock(lock, fcntl.LOCK_UN)
            stdout, stderr = proc.communicate(timeout=10)
            assert proc.returncode != 0  # No template clone; never contacts a remote.
            assert "waiting for the lock of benedek" in stdout
            assert "waiting for the lock of barna" in stdout
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
