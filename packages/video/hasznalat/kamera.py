"""Cameras use browser CSS coordinates on desktop, composition pixels on phone."""

SIZE = (1920, 1080)
PHONE = (729, 40, 462, 1000)
PHONE_VIEW = (390, 844)


def combined(boxes):
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    return [
        x,
        y,
        max(b[0] + b[2] for b in boxes) - x,
        max(b[1] + b[3] for b in boxes) - y,
    ]


def phone_box(box):
    x, y, w, h = box
    ox, oy, width, height = PHONE
    return [
        ox + x * width / PHONE_VIEW[0],
        oy + y * height / PHONE_VIEW[1],
        w * width / PHONE_VIEW[0],
        h * height / PHONE_VIEW[1],
    ]


def camera_box(step, box):
    return phone_box(box) if step["nezet"] == "telefon" else box


def fitted(box, width, height, column=None):
    x, y, w, h = box
    aspect = 16 / 9
    if column:
        x, w = column[0], column[2]
    span = max(width / 2, w + 32, 0 if column else (h + 32) * aspect)
    crop_width = min(width, span)
    crop_height = crop_width / aspect
    left = min(max(0, x - (crop_width - w) / 2), width - crop_width)
    top = min(max(0, y - 16), height - crop_height)
    return [left, top, crop_width, crop_height]


def crop(step, measurement):
    mobile = step["nezet"] == "telefon"
    width, height = (
        SIZE
        if mobile
        else (measurement["viewport"]["width"], measurement["viewport"]["height"])
    )
    boxes = [
        measurement["roles"][c["szereplo"]]["box"]
        for c in step.get("kiemel", [])
        if measurement["roles"].get(c["szereplo"], {}).get("box")
    ]
    if step["kamera"] == "teljes" or not boxes:
        return [0, 0, width, height]
    box = camera_box(step, combined(boxes))
    if tall_cues(step, measurement):
        return tall_crop(box, width)
    column = (
        measurement.get("layout", {}).get("content")
        if step["kamera"] == "tartalom"
        else None
    )
    # Keep the phone's full width and its header near a top-of-page highlight.
    if mobile:
        result = fitted(box, width, height)
        result[1] = max(0, min(result[1], box[1] + box[3] / 2 - result[3] / 2))
        return result
    return fitted(box, width, height, column)


def tall_crop(box, width):
    # Retain as much context as possible, with a margin above H2's 60% threshold.
    span = min(width, max(width / 2, box[2] / 0.65))
    left = min(max(0, box[0] + box[2] / 2 - span / 2), width - span)
    return [left, 0, span, span * 9 / 16]


def tall_cues(step, measurement):
    available = measurement["viewport"]["height"] - measurement.get("layout", {}).get(
        "top", 0
    )
    return [
        cue
        for cue in step.get("kiemel", [])
        if cue.get("magas")
        and (measurement["roles"].get(cue["szereplo"], {}).get("box") or [0] * 4)[3]
        > available
    ]


def phone_in_camera(view):
    x, y, width, height = view
    ox, oy, w, h = PHONE
    return (
        max(0, (ox - 8 - x) * SIZE[0] / width),
        max(0, (oy - 8 - y) * SIZE[1] / height),
        min(SIZE[0], (ox + w + 8 - x) * SIZE[0] / width),
        min(SIZE[1], (oy + h + 8 - y) * SIZE[1] / height),
    )
