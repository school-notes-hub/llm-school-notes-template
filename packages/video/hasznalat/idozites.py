"""Derived production pauses; the reviewed script stays byte-for-byte intact."""

import copy

from .adatok import steps
from .kitolt import transition_seconds
from .mozgas import FPS, recorded_motion


def timed_script(script, measurements):
    result = copy.deepcopy(script)
    ordered = steps(result)
    by_id = {m["id"]: m for m in measurements}
    for previous, step in zip(ordered, ordered[1:]):
        fade = 9 if (previous["url"], previous["nezet"]) != (step["url"], step["nezet"]) else 0
        count = max(
            round(step.get("atmenet_s", 0) * FPS),
            round(transition_seconds(step, previous) * FPS),
            len(recorded_motion(by_id[step["id"]])) + fade,
        )
        step["atmenet_s"] = count / FPS
        click = 27 if previous.get("kurzor", {}).get("kattint") else 0
        previous["szunet"] = max(previous.get("szunet", 0), (count + click) / FPS)
    return result
