import pytest

from school_notes2 import config

BASE = {
    "email_to": "o@example.com",
    "git": {"name": "O", "email": "o@example.com"},
    "students": {"benedek": {"repo": "git@x:a.git", "repo_key": "~/.ssh/a", "site_repo": "git@x:b.git",
                             "site_key": "~/.ssh/b", "drive_root": "id1", "grade": 9}},
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


@pytest.mark.parametrize("grade", ["missing", 0, -1, "9", 9.5, True])
def test_learner_grade_is_required_and_positive(grade):
    import copy
    data = copy.deepcopy(BASE)
    if grade == "missing":
        del data["students"]["benedek"]["grade"]
    else:
        data["students"]["benedek"]["grade"] = grade
    with pytest.raises(config.ConfigError, match=r"\[students\.benedek\]"):
        config.parse(data)


def test_learners_keep_the_configured_order():
    import copy
    data = copy.deepcopy(BASE)
    entry = data["students"]["benedek"]
    data["students"] = {name: {**entry, "grade": n} for n, name in
                        enumerate(["proba", "benedek", "barna"], 7)}
    cfg = config.parse(data)
    assert list(cfg.students) == ["proba", "benedek", "barna"]
    assert [cfg.student(n).grade for n in cfg.students] == [7, 8, 9]


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


def test_operational_cli_and_reader_stage_timeouts():
    from school_notes2.cli import _parser
    for command in ("run", "nightly"):
        assert _parser().parse_args([command, "synthetic", "--manual"]).manual
    assert _parser().parse_args(["round"]).command == "round"
    data = {**BASE, "nightly_after": "04:20", "roles": {**BASE["roles"], "reader": {
        **BASE["roles"]["reviewer"], "timeout_s": 1800, "list_timeout_s": 700, "recheck_timeout_s": 1300}}}
    cfg = config.parse(data)
    reader, _ = cfg.role("reader")
    assert (reader.timeout_s, reader.list_timeout_s, reader.recheck_timeout_s) == (1800, 700, 1300)
    assert cfg.nightly_after == "04:20"


def test_reader_defaults_are_role_defaults_without_reviewer_timeout_leakage():
    data = {**BASE, "roles": {**BASE["roles"], "reader": {
        k: v for k, v in BASE["roles"]["reviewer"].items() if k != "timeout_s"}}}
    for cfg in (config.parse(BASE), config.parse(data)):
        reader, _ = cfg.role("reader")
        assert (reader.timeout_s, reader.list_timeout_s, reader.recheck_timeout_s) == (
            config.Role.timeout_s, config.Role.list_timeout_s, config.Role.recheck_timeout_s)


def test_obsolete_d60_keys_warn_and_are_ignored_for_one_release():
    limits = {"review_max_images": 1, "review_max_diff_kb": 2, "max_agents": 2}
    with pytest.warns(FutureWarning) as warnings:
        cfg = config.parse({**BASE, "limits": limits})
    assert [str(w.message).split()[1] for w in warnings] == ["review_max_diff_kb", "review_max_images"]
    assert cfg.limits.max_agents == 2 and not hasattr(cfg.limits, "review_max_images")
    assert limits["review_max_images"] == 1
