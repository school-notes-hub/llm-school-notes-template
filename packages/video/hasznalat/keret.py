"""Closed ordinary borders; explicitly tall elements keep their true edges."""

from PIL import Image, ImageDraw, ImageChops

from .kamera import SIZE, camera_box


def bounds(spec):
    x, y, width, height = camera_box(spec, spec["box"])
    left, top, w, h = spec["crop"]
    edges = (
        (x - left) * SIZE[0] / w - 8,
        (y - top) * SIZE[1] / h - 8,
        (x + width - left) * SIZE[0] / w + 8,
        (y + height - top) * SIZE[1] / h + 8,
    )
    if spec.get("magas"):
        return edges
    # Padding must not push an otherwise visible element's border off screen.
    return tuple(min(SIZE[i % 2] - 5, max(4, edge)) for i, edge in enumerate(edges))


def outline(image, spec, color):
    ImageDraw.Draw(image).rounded_rectangle(
        bounds(spec), radius=10, outline=color, width=4
    )


def closed_border(spec):
    """Check all four rendered sides and their corners form one closed contour."""
    mask = Image.new("L", SIZE)
    outline(mask, spec, 255)
    if mask.getbbox() is None or any(mask.crop(edge).getbbox() for edge in (
        (0, 0, SIZE[0], 3), (0, SIZE[1] - 3, SIZE[0], SIZE[1]),
        (0, 0, 3, SIZE[1]), (SIZE[0] - 3, 0, SIZE[0], SIZE[1]),
    )):
        return False
    expected = Image.new("L", SIZE)
    ImageDraw.Draw(expected).rounded_rectangle(bounds(spec), radius=10, outline=255, width=1)
    return ImageChops.subtract(expected, mask).getbbox() is None


def clipped_sides(spec):
    x, y, w, h = camera_box(spec, spec["box"])
    left, top, width, height = spec["crop"]
    return [
        name
        for name, clipped in (
            ("bal", x < left),
            ("felso", y < top),
            ("jobb", x + w > left + width),
            ("also", y + h > top + height),
        )
        if clipped
    ]


def open_border(spec):
    """Probe the actual renderer at the middle of each clipped canvas edge."""
    mask = Image.new("L", SIZE)
    outline(mask, spec, 255)
    x, y, right, bottom = bounds(spec)
    cx = round((max(0, x) + min(SIZE[0] - 1, right)) / 2)
    cy = round((max(0, y) + min(SIZE[1] - 1, bottom)) / 2)
    probes = {
        "bal": (0, cy, 4, cy + 1),
        "felso": (cx, 0, cx + 1, 4),
        "jobb": (SIZE[0] - 4, cy, SIZE[0], cy + 1),
        "also": (cx, SIZE[1] - 4, cx + 1, SIZE[1]),
    }
    return all(not mask.crop(probes[side]).getbbox() for side in clipped_sides(spec))


def closed_top(spec):
    """The rendered upper edge and both rounded corners must be on the canvas."""
    left, top, right, bottom = bounds(spec)
    if left < 4 or top < 4 or right > SIZE[0] - 5 or top + 14 >= SIZE[1]:
        return False
    mask = Image.new("L", SIZE)
    outline(mask, spec, 255)
    expected = Image.new("L", SIZE)
    ImageDraw.Draw(expected).rounded_rectangle(
        (left, top, right, bottom), radius=10, outline=255, width=4
    )
    upper = (0, 0, SIZE[0], int(top) + 15)
    return ImageChops.subtract(expected, mask).crop(upper).getbbox() is None
