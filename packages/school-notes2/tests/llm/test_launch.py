import dataclasses
import os
import stat

import pytest

from school_notes2.config import Harness
from school_notes2.llm import launch
from school_notes2.state.errors import BadWork, NeedsOwner, Prerequisite, Transient

FAKE = launch.Path(__file__).with_name("fake_podman.sh")


def set_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("FAKE_MODE", mode)


def make_run(fake, role, harness, tmp_path, **kw):
    work = fake["FAKE_WORK"]
    return launch.RoleRun(learner="benedek", run_id="20261003-0100-ab12", role_name="writer",
                          role=role, harness=harness, image="localhost/school-notes-agent:v2.0.0",
                          mounts=launch.Mounts(work=work, sessdir=tmp_path / "sess"),
                          output_host=work / ".school-notes" / "result.json", schema="result",
                          task_dir=tmp_path / "task", grade=9, **kw)


def go(run, log):
    work = run.mounts.work or run.output_host.parent
    return launch.run_headless(run, log=log, podman=str(FAKE),
                               snapshot=lambda: launch.tree_fingerprint(work))


def argv_lines(fake):
    return fake["FAKE_ARGV"].read_text().splitlines()


def test_success_argv_prompt_and_transcript(fake, role, harness, tmp_path, log, monkeypatch):
    set_mode(monkeypatch, "ok")
    run = make_run(fake, role, harness, tmp_path)
    run.output_host.write_text("old")  # the old result.json is deleted before the start
    outcome = go(run, log)
    assert outcome.output == {"status": "done"} and outcome.rc == 0 and outcome.changed
    argv = argv_lines(fake)
    assert argv[:4] == ["run", "--rm", "--name", "school-notes-benedek-20261003-0100-ab12-writer-1-1"]
    for flag in ("--userns=keep-id", "no-new-privileges", "core=0", "--cap-add=NET_ADMIN,NET_RAW"):
        assert flag in argv
    assert f"{fake['FAKE_WORK']}:/work:rw" in argv
    assert "sn-agent-home-benedek-writer:/home/agent" in argv
    assert f"{tmp_path / 'sess'}:/run/sn:ro" in argv
    for flag in ("--init", "--pids-limit=512", "--memory=2g"):
        assert flag in argv
    assert "SN_MODEL_PROBE=https://api.openai.com/" in argv
    assert argv[-5:] == ["codex", "-m", "gpt-6-astra", "exec", "-"]
    env = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert {e.split("=")[0] for e in env} == {"SN_RUN_ID", "SN_ALLOWED_DOMAINS", "SN_MODEL_PROBE"}
    assert fake["FAKE_STDIN"].read_text() == launch.prompt("writer", grade=9)
    mode = stat.S_IMODE(os.stat(outcome.transcript).st_mode)
    assert mode == 0o600
    assert "rm -f --ignore school-notes-benedek" in fake["FAKE_LOG"].read_text()


@pytest.mark.parametrize("mode,error", [
    ("nothing", Transient),        # non-zero, nothing changed, no output: did not work
    ("changed_fail", BadWork),     # non-zero after changing files
    ("zero_noout", BadWork),       # exit 0 without result.json
    ("bad_json", BadWork),
    ("210", NeedsOwner), ("212", NeedsOwner), ("211", Transient), ("125", Prerequisite),
    ("10", Transient),             # a harness exit 10 is not the preflight: did not work
    ("127", NeedsOwner),
])
def test_outcome_classes(fake, role, harness, tmp_path, log, monkeypatch, mode, error):
    set_mode(monkeypatch, mode)
    with pytest.raises(error):
        go(make_run(fake, role, harness, tmp_path), log)


def test_timeout_stops_container_and_has_its_own_policy(fake, harness, tmp_path, log, monkeypatch, role):
    set_mode(monkeypatch, "sleep")
    quick = dataclasses.replace(role, timeout_s=1)
    with pytest.raises(launch.TimedOut, match="time"):
        go(make_run(fake, quick, harness, tmp_path), log)
    assert "stop -t 10 school-notes-benedek" in fake["FAKE_LOG"].read_text()


def test_stdout_mode_reviewer(fake, role, tmp_path, log, monkeypatch):
    set_mode(monkeypatch, "stdout")
    harness = Harness("x", ["rev"], ["rev"], ["x"], output="stdout")
    out = tmp_path / "out"
    out.mkdir()
    run = launch.RoleRun(learner="barna", run_id="review-1", role_name="reviewer", role=role,
                         harness=harness, image="img",
                         mounts=launch.Mounts(work=fake["FAKE_WORK"], work_readonly=True,
                                              in_dir=tmp_path / "in", out_dir=out),
                         output_host=out / "review.json", schema="review", task_dir=tmp_path / "t",
                         grade=11)
    outcome = launch.run_headless(run, log=log, podman=str(FAKE), snapshot=lambda: 0)
    assert outcome.output == {"verdict": "ok", "findings": []}
    argv = argv_lines(fake)
    assert f"{fake['FAKE_WORK']}:/work:ro" in argv and f"{tmp_path / 'in'}:/in:ro" in argv
    assert f"{out}:/out:rw" in argv and not any("/run/sn" in a for a in argv)
    assert "sn-agent-home-barna-reviewer:/home/agent" in argv
    assert "/out/review.json" not in fake["FAKE_STDIN"].read_text()


def test_metrics_never_fail_and_are_logged(fake, role, harness, tmp_path, log, monkeypatch):
    set_mode(monkeypatch, "ok")
    go(make_run(fake, role, harness, tmp_path), log)
    assert '"action": "llm.launch role=writer"' in log.main.read_text()


def test_login_check(fake, harness, tmp_path, log, monkeypatch):
    set_mode(monkeypatch, "login_in")
    assert launch.login_ok(learner="benedek", run_id="r", role="reviewer", harness=harness,
                           image="img", log=log, podman=str(FAKE))
    argv = argv_lines(fake)
    assert "sn-agent-home-benedek-reviewer:/home/agent" in argv
    assert argv[3] == "school-notes-benedek-r-reviewer-login-1-1" and argv[-3:] == ["codex", "login", "status"]
    assert not any(a.endswith(":/work:rw") for a in argv)
    set_mode(monkeypatch, "login_out")
    assert not launch.login_ok(learner="benedek", run_id="r", role="writer", harness=harness,
                               image="img", log=log, podman=str(FAKE))
    set_mode(monkeypatch, "211")
    with pytest.raises(Transient):
        launch.login_ok(learner="benedek", run_id="r", role="writer", harness=harness,
                        image="img", log=log, podman=str(FAKE))


def test_offline_helper_has_no_network(fake, tmp_path, log, monkeypatch):
    set_mode(monkeypatch, "zero_noout")
    rc = launch.run_offline(learner="barna", run_id="r", image="img", in_dir=tmp_path / "i",
                            out_dir=tmp_path / "o", command=["rsvg-convert", "x.svg"], log=log,
                            timeout=10, podman=str(FAKE))
    argv = argv_lines(fake)
    assert rc == 0 and "--network" in argv and "none" in argv
    assert not any("NET_ADMIN" in a for a in argv)
    assert not any("/home/agent" in a for a in argv) and "SN_NO_NETWORK=1" in argv


def test_interactive_argv_has_tty(role, harness):
    argv = launch.podman_argv(learner="barna", image="img", run_id="r",
                              mounts=launch.Mounts(work=launch.Path("/w")), name="n",
                              interactive=True)
    assert "-it" in argv and "-i" not in argv


def test_prompt_as_argument_when_the_template_wants_no_stdin(fake, role, harness, tmp_path,
                                                              log, monkeypatch):
    set_mode(monkeypatch, "ok")
    argless = dataclasses.replace(harness, prompt_stdin=False)
    go(make_run(fake, role, argless, tmp_path), log)
    first_line = launch.prompt("writer", grade=9).splitlines()[0]
    assert first_line in argv_lines(fake)
    assert fake["FAKE_STDIN"].read_text() == ""


def test_login_run_uses_the_role_volume_and_login_domains(fake, harness, log, monkeypatch):
    set_mode(monkeypatch, "login_in")
    rc = launch.run_login(learner="barna", role="reviewer", harness=harness, image="img", log=log,
                          allowed_domains=("api.openai.com", "auth.openai.com", "claude.ai"),
                          podman=str(FAKE))
    argv = argv_lines(fake)
    assert rc == 0 and "sn-agent-home-barna-reviewer:/home/agent" in argv
    assert "SN_ALLOWED_DOMAINS=api.openai.com,auth.openai.com,claude.ai" in argv
    assert argv[-3:] == ["codex", "login", "--device-auth"] and "-it" in argv


def test_unknown_role_volume_is_refused():
    with pytest.raises(ValueError):
        launch.home_volume("barna", "intruder")


def test_expand_keeps_json_braces(role):
    out = launch.expand(["--mcp-config", '{"mcpServers":{}}', "--model", "{model}",
                         "effort={effort}"], role)
    assert out == ["--mcp-config", '{"mcpServers":{}}', "--model", "gpt-6-astra", "effort=high"]
