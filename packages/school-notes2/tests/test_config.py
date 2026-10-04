import pytest

from school_notes2 import config

BASE = {
    "email_to": "o@example.com",
    "git": {"name": "O", "email": "o@example.com"},
    "students": {"benedek": {"repo": "git@x:a.git", "repo_key": "~/.ssh/a", "site_repo": "git@x:b.git",
                             "site_key": "~/.ssh/b", "drive_root": "id1"}},
    "harnesses": {"fake": {"headless": ["fake"], "interactive": ["fake"], "login_check": ["true"]}},
    "roles": {"writer": {"harness": "fake", "model": "m", "effort": "high", "timeout_s": 5400},
              "reviewer": {"harness": "fake", "model": "m", "effort": "high", "timeout_s": 600}},
}


def test_parse_defaults_and_paths():
    cfg = config.parse(BASE)
    assert cfg.student("benedek").repo_key.name == "a"
    assert cfg.sources.max_side_px == 2000 and cfg.limits.image_daily_usd == 1.0
    assert cfg.bare("benedek").name == "benedek.git"
    assert cfg.bare("benedek", site=True).name == "benedek-site.git"


def test_effort_above_high_is_refused():
    data = {**BASE, "roles": {**BASE["roles"],
                              "writer": {**BASE["roles"]["writer"], "effort": "xhigh"}}}
    with pytest.raises(config.ConfigError, match="at most high"):
        config.parse(data)


def test_unknown_keys_are_refused():
    with pytest.raises(config.ConfigError, match="unknown keys"):
        config.parse({**BASE, "limits": {"image_daily_usd": 1, "typo": 2}})


def test_unknown_learner():
    with pytest.raises(config.ConfigError):
        config.parse(BASE).student("nobody")


def test_writer_timeout_defaults_to_two_hours_but_explicit_override_survives():
    import copy
    data = copy.deepcopy(BASE)
    del data["roles"]["writer"]["timeout_s"]
    assert config.parse(data).role("writer")[0].timeout_s == 7200
    assert config.parse(BASE).role("writer")[0].timeout_s == 5400


def test_repair_cli_requires_exactly_one_target_mode():
    from school_notes2.cli import _parser
    args = _parser().parse_args(["repair", "barna", "--topic", "wiki/m/a.md", "--no-push"])
    assert args.topic == "wiki/m/a.md" and args.no_push and not args.queue
    assert _parser().parse_args(["repair", "benedek", "--queue"]).queue
    for argv in (["repair", "barna"], ["repair", "barna", "--queue", "--topic", "a"]):
        with pytest.raises(SystemExit):
            _parser().parse_args(argv)
