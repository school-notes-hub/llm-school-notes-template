"""sn 0.3.2: the library steps write one small timed line each into the JSONL log (the step
log of `common.Local.steps`); other library events and content never reach it."""

import json

import pytest

from school_notes2.local.common import STEPS
from school_notes2.log import Log
from school_notes2.site import publish as site_publish
from tests.site.test_site import Env, allow_local_origin  # noqa: F401 - local file origins


@pytest.fixture
def steps(tmp_path):
    return Log(tmp_path / "logs" / "school-notes.log", student="benedek", console=False, steps=STEPS)


def lines(log):
    return [json.loads(line) for line in log.main.read_text().splitlines()] if log.main.exists() else []


def test_only_the_timed_steps_are_written_small(steps):
    steps.event("git.status", "ok", target="x", duration_s=0.1)
    steps.event("retry", "retry 1/3", message="secret-ish text")
    steps.event("git.push", "error", target="--porcelain origin", duration_s=1.23456, rc=1,
                stderr_head="remote: some text", message="m", error_class="transient", live=True)
    [line] = lines(steps)
    assert line["action"] == "git.push" and line["seconds"] == 1.235 and line["rc"] == 1
    assert line["error_class"] == "transient"
    assert set(line) == {"ts", "level", "student", "action", "target", "outcome", "seconds", "rc", "error_class"}


def test_git_network_operations_build_pdf_push_and_live_check_each_write_one_line(tmp_path, steps):
    env = Env(tmp_path, steps)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nPDF_STEP\n"})
    head = env.main()
    record = env.build(head)
    site_publish.publish(env.site, record.output / "site", student="benedek", source_commit=head, run_id="r",
                         tool_version="2.0.0", log=steps)
    site_publish.wait_until_live("https://x/publish.json", head, steps,
                                 fetch=lambda url: json.dumps({"source_commit": head}).encode(), sleep=lambda s: None)
    found = lines(steps)
    actions = [line["action"] for line in found]
    assert actions[0] == "git.fetch" and {"git.ls-remote", "git.push"} <= set(actions)
    assert actions.count("site.build") == actions.count("site.pdf") == actions.count("site.publish") == 1
    assert actions[-1] == "site.live" and set(actions) <= set(STEPS)
    assert all(isinstance(line["seconds"], float) for line in found)
    pdf = next(line for line in found if line["action"] == "site.pdf")
    assert pdf["seconds"] == 3.5 and pdf["generated"] == 1 and pdf["reused"] == 2
    assert all(len(json.dumps(line)) < 300 for line in found)


def test_a_failed_build_still_writes_its_timed_line(tmp_path, steps):
    env = Env(tmp_path, steps)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nRENDER_FAIL\n"})
    with pytest.raises(Exception):
        env.build(env.main())
    [line] = [x for x in lines(steps) if x["action"] == "site.build"]
    assert line["outcome"] == "error" and "seconds" in line
