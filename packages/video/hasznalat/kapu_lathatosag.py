"""H2: ordinary elements fit; explicitly permitted tall elements remain honest."""

from .kamera import crop, camera_box, cuts_text
from .keret import clipped_sides, open_border


def inside(box, view):
    if not box:
        return False
    x, y, width, height = box
    left, top, w, h = view
    return x >= left and y >= top and x + width <= left + w and y + height <= top + h


def intersection(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    return [x, y, max(0, right - x), max(0, bottom - y)]


def tall_error(step, measurement, item, camera):
    box = item["box"]
    top = measurement.get("layout", {}).get("top", 0)
    viewport = measurement["viewport"]
    screen = [0, top, viewport["width"], viewport["height"] - top]
    view = intersection(camera_box(step, screen), camera)
    visible = intersection(camera_box(step, box), view)
    area = view[2] * view[3]
    ratio = visible[2] * visible[3] / area if area else 0
    spec = {"box": box, "crop": camera, "nezet": step["nezet"]}
    upper = camera_box(step, [box[0], box[1], box[2], 0])
    if not top - 1 <= box[1] <= top + 2 or not inside(upper, camera):
        return "a magas elem teteje nem közvetlenül a fejléc alatt látszik"
    if ratio < 0.6:
        return f"a magas elem képfedése {ratio:.1%}, legalább 60% szükséges"
    if not item.get("visible_uncovered") or not all(item["visible_uncovered"]):
        return "a magas elem látható része takart"
    if not clipped_sides(spec) or not open_border(spec):
        return "a magas elem kerete a vágott oldalon nem nyitott"
    return None


def highlight_error(step, measurement, cue, camera):
    item = measurement.get("roles", {}).get(cue["szereplo"], {})
    box = item.get("box")
    available = measurement.get("viewport", {}).get("height", 0) - measurement.get(
        "layout", {}
    ).get("top", 0)
    if box and box[3] > available and cue.get("magas"):
        return tall_error(step, measurement, item, camera)
    if not inside(camera_box(step, box) if box else None, camera) or not all(
        item.get("uncovered", [False])
    ):
        if box and box[3] > available:
            return f"{box[3]:g} > {available:g} CSS px, görgetés nem segít"
        return "az elem nincs teljesen a kamerában, vagy takart"
    return None


def h2(step, measurement, add):
    camera = crop(step, measurement) if measurement else [0, 0, 0, 0]
    if step.get("kamera") != "teljes" and step.get("nezet") != "telefon":
        cut = cuts_text(camera, measurement.get("text_rects", []))
        if cut:
            add("H2", step["id"], "", "a kivágás látható szöveget vág ketté: " + ", ".join(w["text"] for w in cut[:5]))
    if not step.get("kiemel") and measurement.get("focus_visible"):
        add("H2", step["id"], "", "kiemelés nélküli lépésben látható fókuszkeret maradt")
    for cue in step.get("kiemel", []):
        message = highlight_error(step, measurement, cue, camera)
        if message:
            add("H2", step["id"], cue["szereplo"], message)
        item = measurement.get("roles", {}).get(cue["szereplo"], {})
        if (step.get("nezet") != "telefon" and item.get("label_context")
                and item.get("context") and item.get("box")):
            context = camera_box(step, item["context"])
            label = camera_box(step, item["box"])
            if (label[1] < camera[1] + camera[3] / 2 or
                (context[3] <= camera[3] - 48 and not inside(context, camera)) or
                label[1] - max(camera[1], context[1]) < 24):
                add("H2", step["id"], cue["szereplo"], "a címke fölötti szöveg és az alsó félben álló címke nem látszik együtt")
    cursor = step.get("kurzor")
    if not cursor:
        return
    item = measurement.get("roles", {}).get(cursor["szereplo"], {})
    box = item.get("box")
    point = [box[0] + box[2] / 2, box[1] + box[3] / 2, 0, 0] if box else None
    if (
        not inside(camera_box(step, point) if point else None, camera)
        or not item.get("uncovered", [False])[-1]
    ):
        add(
            "H2",
            step["id"],
            cursor["szereplo"],
            "a kurzor célpontja takart vagy a kamerán kívül van",
        )
