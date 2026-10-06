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
