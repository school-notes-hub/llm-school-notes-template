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
    column = measurement.get("layout", {}).get("content")
    if not mobile and column:
        return column_crop(step, measurement, box, column)
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


def cuts_text(view, words):
    """Return words crossed by a crop edge, including vertical line cuts."""
    x, y, w, h = view
    result = []
    for word in words:
        a, b, c, d = word["box"]
        if min(x + w, a + c) <= max(x, a) or min(y + h, b + d) <= max(y, b):
            continue
        if a < x - 0.5 or b < y - 0.5 or a + c > x + w + 0.5 or b + d > y + h + 0.5:
            result.append(word)
    return result


def column_crop(step, measurement, box, column):
    """Keep the real text column, context and line boundaries at native scale."""
    viewport = measurement["viewport"]
    items = [measurement["roles"].get(c["szereplo"], {}) for c in step.get("kiemel", [])]
    contexts = [i.get("context") or i["box"] for i in items if i.get("box")]
    context = combined(contexts) if contexts else box
    label = any(i.get("label_context") for i in items)
    footer = label or step.get("dom_sorrend") or any(
        set(i.get("structures", [])) & {"cimke", "datum-link"} for i in items
    )
    tall = bool(tall_cues(step, measurement))
    top = measurement.get("layout", {}).get("top", 0)
    if tall and top - 1 <= box[1] < top:
        top = box[1]  # Fractional browser scroll coordinates are not clipping.
    words = measurement.get("text_rects", [])
    valid = []
    fallback = None
    # A few pixels of breathing room can vary so both horizontal crop edges
    # land between actual text lines, without changing the page or its scale.
    for padding in [*range(16, 3, -1), *range(17, 25)]:
        left = max(0, column[0] - padding)
        width = min(viewport["width"] - left, column[2] + padding * 2)
        height = width * 9 / 16
        margin = 12 if box[3] > height * 0.4 else 24
        preferred = top if tall else (box[1] + box[3] + 32 - height if footer else context[1] - height * 0.2)
        fallback = fallback or [left, min(max(top, preferred), viewport["height"] - height), width, height]
        candidates = [preferred, top, viewport["height"] - height]
        for word in words:
            _, y, _, h = word["box"]
            candidates.extend([y - 1, y + h + 1, y - height - 1, y + h + 1 - height])
        for y in sorted(set(candidates)):
            if y < top or y + height > viewport["height"]:
                continue
            if not tall and (y > box[1] - margin or y + height < box[1] + box[3] + margin):
                continue
            if tall and y > box[1]:
                continue
            if label and box[1] < y + height / 2:
                continue
            view = [left, y, width, height]
            if not cuts_text(view, words):
                lost = max(0, y - context[1]) + max(0, context[1] + context[3] - y - height)
                valid.append((lost, abs(y - preferred) + abs(16 - padding), view))
    if valid:
        return min(valid, key=lambda v: v[:2])[2]
    # The gate reports impossible layouts rather than hiding text or scaling DOM.
    return fallback


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
