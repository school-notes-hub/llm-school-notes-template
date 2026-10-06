import pytest

from school_notes2 import cli


def test_cli_knows_only_the_local_commands():
    parser = cli._parser()
    choices = parser._subparsers._group_actions[0].choices
    assert sorted(choices) == ["book", "check", "close", "done", "fetch", "gen", "publish"]
    for old in ("run", "nightly", "round", "status", "repair", "chat", "mcp", "setup", "finish"):
        with pytest.raises(SystemExit):
            parser.parse_args([old, "barna"])


def test_cli_arguments():
    p = cli._parser()
    assert p.parse_args(["fetch", "barna", "--apply"]).apply
    assert not p.parse_args(["fetch", "barna"]).apply
    args = p.parse_args(["close", "barna", "--subject", "b,a", "--check"])
    assert args.subject == "b,a" and args.check
    args = p.parse_args(["publish", "benedek", "--reviewed"])
    assert args.reviewed and args.build_only is None
    args = p.parse_args(["gen", "--settle"])
    assert args.settle and args.learner is None
    args = p.parse_args(["book", "barna", "irodalom", "OH-X", "/src", "--offset", "1"])
    assert (args.code, args.offset) == ("OH-X", 1)


@pytest.mark.parametrize("argv", [["gen", "barna"], ["gen", "barna", "fig", "--settle", "--grant"]])
def test_gen_needs_a_figure_unless_settling(argv):
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_config_and_prerequisite_errors_are_one_line_not_a_traceback(tmp_path, capsys):
    missing = tmp_path / "none.toml"
    assert cli.main(["--config", str(missing), "done", "barna"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Hiba: configuration missing") and "Traceback" not in err


def test_refusals_are_logged(monkeypatch, tmp_path, capsys):
    from school_notes2.local import common
    records = []

    class Stub:
        def record(self, command, outcome="ok", **fields):
            records.append((command, outcome, fields.get("error_class")))
    monkeypatch.setattr(common, "load", lambda learner, config=None: Stub())

    def refuse(local, args):
        raise common.Refused("nincs átadás")
    monkeypatch.setattr(cli, "_dispatch", refuse)
    assert cli.main(["close", "barna"]) == 1
    assert records == [("close", "error", "refused")]


def test_only_belongs_to_snapshot():
    with pytest.raises(SystemExit):
        cli.main(["close", "barna", "--only", "a"])
    args = cli._parser().parse_args(["close", "barna", "--subject", "a", "--snapshot", "--only", "x,y"])
    assert args.snapshot and args.only == "x,y"
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["close", "barna", "--snapshot", "--check"])
