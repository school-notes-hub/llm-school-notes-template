"""Cursor trajectories, expanding rings and complete-frame transitions."""

import copy

from .kamera import crop

FPS = 30


def cursor_frames(frames, step, measurement, timing, next_step):
    cursor = step.get("kurzor", {})
    box = measurement["roles"].get(cursor.get("szereplo"), {}).get("box")
    if not box or not (cursor.get("horgony") or cursor.get("kattint")):
        return
    end = (
        timing["horgonyok"][cursor["horgony"]]["kocka"]
        if cursor.get("horgony")
        else timing["veg_kocka"] - round(next_step.get("atmenet_s", 0) * FPS) - 9
    )
    target = measurement.get("anchor_cursor") or [
        box[0] + box[2] / 2,
        box[1] + box[3] / 2,
    ]
    for number in range(
        max(timing["kezd_kocka"], end - 18), min(timing["veg_kocka"], end + 9)
    ):
        u = min(1, max(0, (number - end + 18) / 18))
        ease = u * u * (3 - 2 * u)
        frames[number]["kurzor"] = [
            target[0] - 80 * (1 - ease),
            target[1] + 50 * (1 - ease),
        ]
        if number >= end:
            frames[number]["gyuru"] = 6 + 3 * (number - end)


def motion_frame(item, index, count):
    result = dict(item)
    if item.get("approach") and item.get("cursor"):
        u = (index + 1) / count
        ease = u * u * (3 - 2 * u)
        x, y = item["cursor"]
        result["cursor"] = [x - 80 * (1 - ease), y + 50 * (1 - ease)]
    if item.get("ring"):
        result["radius"] = 6 + 3 * index
    return result


def recorded_motion(measurement):
    motion = measurement.get("motion")
    if motion is None:
        motion = [
            {"image": image, "seconds": 1 / FPS}
            for image in measurement.get("frames", [])
        ]
    result = []
    for item in motion:
        count = max(1, round(item["seconds"] * FPS))
        result.extend(motion_frame(item, i, count) for i in range(count))
    return result


def transition_frames(frames, step, previous, measurement, timing):
    count = round(step.get("atmenet_s", 0) * FPS)
    if count > round(previous.get("szunet", 0) * FPS):
        raise ValueError("H4: az átmenet nem fér a csendbe: " + step["id"])
    start = timing["kezd_kocka"] - count
    old = copy.deepcopy(frames[start - 1]) if start else None
    fade_count = (
        9
        if old
        and (previous["nezet"] != step["nezet"] or previous["url"] != step["url"])
        else 0
    )
    motion = recorded_motion(measurement)
    if len(motion) + fade_count > count:
        raise ValueError("H4: a felvett képsor nem fér az átmenetbe: " + step["id"])
    target = crop(step, measurement)
    for offset in range(count):
        frames[start + offset] = transition_frame(
            step, measurement, motion, target, old, fade_count, offset, count
        )


def transition_frame(step, measurement, motion, target, old, fade_count, offset, count):
    item = motion[min(max(0, offset - fade_count), len(motion) - 1)] if motion else {}
    image = item.get("image", measurement.get("before_image") or measurement["image"])
    progress = offset / max(1, count - 1)
    ease = progress * progress * (3 - 2 * progress)
    view = (
        target
        if fade_count or not old
        else [a + (b - a) * ease for a, b in zip(old["crop"], target)]
    )
    spec = {
        "lepes": step["id"],
        "image": image,
        "crop": view,
        "nezet": step["nezet"],
        "kiemel": None,
        "box": None,
        "alpha": 0,
        "mozgas": True,
    }
    if fade_count and offset < fade_count:
        spec.update(fade=old, mix=offset / (fade_count - 1))
    if item.get("cursor"):
        spec["kurzor"] = item["cursor"]
    if item.get("ring"):
        spec["gyuru"] = item["radius"]
    return spec
