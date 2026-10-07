"""sn 0.3.3 (decision F3): a failed PDF step, build or gh-pages publish writes its timed line
too, with its error class. Each test fails on 9b85754."""

import json

import pytest

from school_notes2.site import publish as site_publish
from school_notes2.state.errors import NeedsOwner
from tests.site.test_site import Env, allow_local_origin  # noqa: F401
from tests.site.test_step_log import lines, steps  # noqa: F401


def test_a_failed_pdf_step_writes_its_timed_line(tmp_path, steps):  # noqa: F811
    env = Env(tmp_path, steps)
    env.push({"wiki/gazd/tema.md": "# Téma\n\nPDF_FAIL\n"})
    with pytest.raises(Exception):
        env.build(env.main())
    found = {x["action"]: x for x in lines(steps)}
    assert (found["site.pdf"]["outcome"], found["site.pdf"]["seconds"], found["site.pdf"]["error_class"]) == ("error", 1.5, "transient")
    assert found["site.build"]["outcome"] == "error" and found["site.build"]["error_class"] == "transient"


def test_a_failed_publish_writes_its_timed_line(tmp_path, steps, monkeypatch):  # noqa: F811
    env = Env(tmp_path, steps)
    record = env.build(env.main())

    def broken(*a, **k):
        raise NeedsOwner("rsync is missing")
    monkeypatch.setattr(site_publish, "_stage", broken)
    with pytest.raises(NeedsOwner):
        site_publish.publish(env.site, record.output / "site", student="benedek", source_commit=record.commit,
                             run_id="r", tool_version="2.0.0", log=steps)
    [line] = [x for x in lines(steps) if x["action"] == "site.publish"]
    assert line["outcome"] == "error" and line["error_class"] == "needs_owner" and "seconds" in line
    assert len(json.dumps(line)) < 300
