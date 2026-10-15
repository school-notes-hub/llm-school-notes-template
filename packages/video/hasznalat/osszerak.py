"""CSS-koordinátás kamera és teljes kockaleírások; Pillow → ffmpeg."""

import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

from .adatok import steps
from .kamera import SIZE, PHONE, PHONE_VIEW, crop, tall_cues
from .mozgas import cursor_frames, transition_frames
from .keret import outline

FPS = 30


def still_frames(step, measurement, timing):
    cues = [
        (
            timing["horgonyok"][c["horgony"]]["kocka"]
            if c.get("horgony")
            else timing["kezd_kocka"],
            c,
        )
        for c in step.get("kiemel", [])
    ]
    action = next((a for a in step.get("allapot", []) if a.get("horgony")), None)
    switch = (
        timing["horgonyok"][action["horgony"]]["kocka"]
        if action
        else timing["kezd_kocka"]
    )
    result = []
    for number in range(timing["kezd_kocka"], timing["veg_kocka"]):
        active = [(at, cue) for at, cue in cues if at <= number]
        at, cue = active[-1] if active else (number, None)
        image = (
            measurement.get("before_image") if number < switch else measurement["image"]
        )
        result.append(
            {
                "lepes": step["id"],
                "image": image or measurement["image"],
                "crop": crop(step, measurement),
                "nezet": step["nezet"],
                "kiemel": cue["szereplo"] if cue else None,
                "magas": cue in tall_cues(step, measurement) if cue else False,
                "box": measurement["roles"].get(cue["szereplo"], {}).get("box")
                if cue
                else None,
                "alpha": min(1, (number - at + 1) / 6) if cue else 0,
                "mozgas": False,
            }
        )
    return result


def plan(script, measurements, timing):
    by_id = {m["id"]: m for m in measurements}
    times = {t["id"]: t for t in timing["lepesek"]}
    frames = []
    ordered = steps(script)
    for index, step in enumerate(ordered):
        measurement, time = by_id[step["id"]], times[step["id"]]
        if len(frames) != time["kezd_kocka"]:
            raise ValueError("nem folytonos időterv: " + step["id"])
        frames.extend(still_frames(step, measurement, time))
        cursor_frames(
            frames,
            step,
            measurement,
            time,
            ordered[index + 1] if index + 1 < len(ordered) else {},
        )
        if index:
            transition_frames(frames, step, ordered[index - 1], measurement, time)
    if len(frames) != timing["kocka_osszes"]:
        raise ValueError("hibás kockaszám")
    return {"fps": FPS, "kockak": frames}


@lru_cache(maxsize=4)
def source(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def base_frame(out, spec):
    image = source(str(Path(out) / spec["image"]))
    if spec["nezet"] == "telefon":
        result = Image.new("RGB", SIZE, "#f1f3f5")
        ox, oy, width, height = PHONE
        ImageDraw.Draw(result).rounded_rectangle(
            (ox - 8, oy - 8, ox + width + 8, oy + height + 8), radius=28, fill="black"
        )
        result.paste(image.resize((width, height), Image.Resampling.LANCZOS), (ox, oy))
        return result, (width / PHONE_VIEW[0], height / PHONE_VIEW[1], ox, oy)
    x, y, w, h = spec["crop"]
    pixels = image.crop(tuple(round(v * 3) for v in (x, y, x + w, y + h)))
    result = pixels.resize(SIZE, Image.Resampling.LANCZOS)
    return result, (SIZE[0] / w, SIZE[1] / h, -x * SIZE[0] / w, -y * SIZE[1] / h)


def draw_highlight(result, spec):
    if not spec.get("box") or not spec.get("kiemel"):
        return result
    overlay = result.copy()
    outline(overlay, spec, "#D9480F")
    return Image.blend(result, overlay, spec.get("alpha", 1))


def draw_cursor(result, spec, transform):
    if not spec.get("kurzor"):
        return
    sx, sy, ox, oy = transform
    x, y = spec["kurzor"]
    x, y = x * sx + ox, y * sy + oy
    draw = ImageDraw.Draw(result)
    if spec["nezet"] != "telefon":
        draw.polygon(
            [(x, y), (x + 5, y + 25), (x + 11, y + 17), (x + 23, y + 17)],
            fill="white",
            outline="black",
            width=2,
        )
    if spec.get("gyuru"):
        radius = spec["gyuru"]
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius), outline="#D9480F", width=3
        )


def frame(out, spec):
    result, transform = base_frame(out, spec)
    if spec["nezet"] == "telefon":
        x, y, w, h = spec["crop"]
        result = result.crop((x, y, x + w, y + h)).resize(
            SIZE, Image.Resampling.LANCZOS
        )
        sx, sy, ox, oy = transform
        zx, zy = SIZE[0] / w, SIZE[1] / h
        transform = (sx * zx, sy * zy, (ox - x) * zx, (oy - y) * zy)
    result = draw_highlight(result, spec)
    draw_cursor(result, spec, transform)
    if spec.get("fade"):
        result = Image.blend(frame(out, spec["fade"]), result, spec["mix"])
    return result


FFMPEG = [
    "ffmpeg",
    "-loglevel",
    "error",
    "-y",
    "-f",
    "rawvideo",
    "-pix_fmt",
    "rgb24",
    "-s",
    "1920x1080",
    "-r",
    "30",
    "-i",
    "-",
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    "23",
    "-tune",
    "stillimage",
    "-pix_fmt",
    "yuv420p",
    "-g",
    "300",
    "-threads",
    "4",
    "-map_metadata",
    "-1",
]


def render(out, frame_plan):
    source.cache_clear()
    cmd = [*FFMPEG, str(Path(out) / "fo.mp4")]
    with open(Path(out) / "ffmpeg.log", "ab") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        try:
            send_frames(proc, out, frame_plan)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def send_frames(proc, out, frame_plan):
    previous, data = None, None
    for spec in frame_plan["kockak"]:
        if spec != previous:
            data = frame(out, spec).tobytes()
            previous = spec
        proc.stdin.write(data)
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg: lásd ffmpeg.log")
