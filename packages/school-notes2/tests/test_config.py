import copy

import pytest

from school_notes2 import config

BASE = {
    "git": {"name": "O", "email": "o@example.com"},
    "students": {"benedek": {"site_repo": "https://github.com/o/b.git", "drive_root": "id1", "grade": 9}},
}

# The owner's VM-era file (2026-10-07): every key the tool no longer reads.
LEGACY = {
    "root": "~/.local/share/school-notes", "secrets_dir": "~/.config/school-notes/secrets",
    "release_dir": "~/jegyzet/llm-school-notes-template", "email_to": "o@example.com",
    "git": {"name": "O", "email": "o@example.com", "ssh_hostname": "ssh.github.com", "ssh_port": 443},
    "students": {"barna": {"repo": "git@github.com:o/a.git", "repo_key": "~/.ssh/k",
                           "site_repo": "git@github.com:o/b.git", "site_key": "~/.ssh/k",
                           "drive_root": "id2", "grade": 11, "publish": True}},
    "roles": {"writer": {"harness": "claude-review", "model": "m", "effort": "high"}},
    "limits": {"image_monthly_usd": 10.0, "image_daily_usd": 10.0},
    "sources": {"ready_after_s": 0},
}


def test_parse_defaults_and_paths():
    cfg = config.parse(BASE)
    assert cfg.root == config.Path("~/.local/share/school-notes").expanduser()
    assert cfg.state_dir == cfg.root / "state" and cfg.log_path == cfg.root / "logs" / "school-notes.log"
    assert cfg.sources.max_side_px == 2000 and cfg.limits.image_monthly_usd == 10.0
    assert cfg.limits.image_year_total_usd == cfg.limits.image_year_learner_usd == 120.0
    assert cfg.student("benedek").local_repo is None and cfg.ignored == ()


def test_the_vm_era_keys_are_ignored_and_named_once(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text("""root = "~/x"\nsecrets_dir = "s"\nemail_to = "o@example.com"\n
[git]\nname = "O"\nemail = "o@example.com"\nssh_port = 443\n
[students.barna]\nrepo_key = "k"\nsite_repo = "https://github.com/o/b.git"\ndrive_root = "d"\ngrade = 11\n
[roles.writer]\nmodel = "m"\n
[sources]\nready_after_s = 0\n""")
    cfg = config.load(path)
    assert cfg.student("barna").grade == 11
    err = capsys.readouterr().err.splitlines()
    assert err == [f"sn: {path}: not used, ignored: email_to, git.ssh_port, roles, secrets_dir, "
                   "sources.ready_after_s, students.barna.repo_key"]


def test_the_owners_legacy_layout_loads():
    cfg = config.parse(LEGACY)
    assert cfg.student("barna").site_repo == "git@github.com:o/b.git"
    assert cfg.limits.image_monthly_usd == 10.0
    assert cfg.ignored == ("email_to", "git.ssh_hostname", "git.ssh_port", "limits.image_daily_usd", "release_dir",
                           "roles", "secrets_dir", "sources.ready_after_s", "students.barna.publish",
                           "students.barna.repo", "students.barna.repo_key", "students.barna.site_key")


@pytest.mark.parametrize("value", [-1, "10", True])
def test_a_limit_must_be_a_non_negative_number(value):
    with pytest.raises(config.ConfigError, match=r"\[limits\] image_monthly_usd"):
        config.parse({**BASE, "limits": {"image_monthly_usd": value}})


@pytest.mark.parametrize("grade", ["missing", 0, -1, "9", 9.5, True])
def test_learner_grade_is_required_and_positive(grade):
    data = copy.deepcopy(BASE)
    if grade == "missing":
        del data["students"]["benedek"]["grade"]
    else:
        data["students"]["benedek"]["grade"] = grade
    with pytest.raises(config.ConfigError, match=r"\[students\.benedek\]"):
        config.parse(data)


def test_git_identity_is_required():
    with pytest.raises(config.ConfigError, match=r"\[git\] missing email"):
        config.parse({**BASE, "git": {"name": "O"}})


def test_learners_keep_the_configured_order():
    data = copy.deepcopy(BASE)
    entry = data["students"]["benedek"]
    data["students"] = {name: {**entry, "grade": n} for n, name in enumerate(["proba", "benedek", "barna"], 7)}
    cfg = config.parse(data)
    assert list(cfg.students) == ["proba", "benedek", "barna"]
    assert [cfg.student(n).grade for n in cfg.students] == [7, 8, 9]


def test_unknown_learner():
    with pytest.raises(config.ConfigError):
        config.parse(BASE).student("nobody")


def test_missing_file(tmp_path):
    with pytest.raises(config.ConfigError, match="configuration missing"):
        config.load(tmp_path / "none.toml")


@pytest.mark.parametrize("section, key", [("limits", "image_monthy_usd"), ("sources", "max_side"),
                                          ("timeouts", "push")])
def test_a_typo_inside_a_section_the_tool_reads_is_an_error(section, key):
    """D9: a misspelt budget key must not silently give the default budget."""
    with pytest.raises(config.ConfigError, match=rf"\[{section}\] unknown keys: {key}"):
        config.parse({**BASE, section: {key: 1}})


def test_vm_era_keys_inside_kept_sections_only_warn():
    cfg = config.parse({**BASE, "limits": {"image_daily_usd": 1.0, "image_monthly_usd": 5.0},
                        "sources": {"pdf_dpi": 200, "ready_after_s": 0}})
    assert cfg.limits.image_monthly_usd == 5.0
    assert cfg.ignored == ("limits.image_daily_usd", "sources.pdf_dpi", "sources.ready_after_s")
