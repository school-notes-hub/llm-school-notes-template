"""sn 0.3.2: every paid generation attempt writes one timed `image.attempt` line."""

import json

from school_notes2.images import generate
from school_notes2.local.common import STEPS
from school_notes2.log import Log
from test_variants import local_images  # noqa: F401 - the real executor with a fake transport


def test_each_generation_attempt_writes_one_timed_line(local_images, tmp_path):  # noqa: F811
    settings, calls = local_images("barna")
    steps = Log(tmp_path / "logs" / "school-notes.log", student="barna", console=False, steps=STEPS)
    assert generate.generate(settings, "termeles-banner", log=steps)["state"] == "generated"
    assert generate.generate(settings, "termeles-banner", "A cím legyen olvasható.", log=steps)["state"] == "generated"
    found = [json.loads(line) for line in steps.main.read_text().splitlines()]
    assert [(x["action"], x["outcome"], x["target"]) for x in found] == [("image.attempt", "generated", "barna-termeles-banner")] * 2
    assert all(isinstance(x["seconds"], float) for x in found) and len(calls) == 2
