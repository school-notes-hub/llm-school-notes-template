"""H1–H10: az előnézet kapuja csak a mért képi feltételeket fogadja el."""

import re
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageStat

from .adatok import ROOT, read, roles, steps
from .kapu_kiadas import h6, h7
from .kapu_lathatosag import h2


def h1(step, measurement, add):
    for role in roles(step):
        item = measurement.get("roles", {}).get(role, {})
        if item.get("count") != 1 or not item.get("visible"):
            add(
                "H1",
                step["id"],
                role,
                item.get("reason")
                or f"{step.get('url')}: találat: {item.get('count', 0)}",
            )


def h3(step, measurement, add):
    for cue in step.get("kiemel", []):
        item = measurement.get("roles", {}).get(cue["szereplo"], {})
        structure = cue.get("szerkezet")
        required = cue.get("kell", cue.get("horgony", ""))
        if structure:
            if structure not in item.get("structures", []):
                add(
                    "H3",
                    step["id"],
                    cue["szereplo"],
                    "a szerkezeti feltétel nem teljesül: " + structure,
                )
        elif not required or required.casefold() not in item.get("text", "").casefold():
            add(
                "H3",
                step["id"],
                cue["szereplo"],
                f"a narráció »{required}«-t mond, a kiemelt elemben nincs",
            )


def highlight_timing(step, time, frames, add):
    for cue in step.get("kiemel", []):
        start = (
            time["horgonyok"][cue["horgony"]]["kocka"]
            if cue.get("horgony")
            else time["kezd_kocka"]
        )
        shown = [
            (i, f)
            for i, f in enumerate(frames)
            if f["lepes"] == step["id"] and f.get("kiemel") == cue["szereplo"]
        ]
        stationary = shown and all(
            not f.get("mozgas") and f.get("crop") == shown[0][1].get("crop")
            for _, f in shown
        )
        if not shown or shown[0][0] != start or len(shown) < 36 or not stationary:
            add(
                "H4",
                step["id"],
                cue["szereplo"],
                "horgonyidő, 1,2 s kiemelés vagy mozdulatlan kamera nem teljesül",
            )


def frame_images(frame):
    result = {frame["image"]}
    if isinstance(frame.get("fade"), dict):
        result |= frame_images(frame["fade"])
    return result


def h4(step, measurement, frame_plan, timing, add):
    if frame_plan is None or timing is None:
        return
    frames = frame_plan["kockak"]
    used = set().union(*(frame_images(f) for f in frames)) if frames else set()
    missing = [image for image in measurement.get("frames", []) if image not in used]
    if missing:
        add(
            "H4",
            step["id"],
            "",
            "felvett képek kimaradtak a kockatervből: " + ", ".join(missing),
        )
    time = next((t for t in timing["lepesek"] if t["id"] == step["id"]), None)
    if not time or time["veg_kocka"] - time["kezd_kocka"] < 45:
        add("H4", step["id"], "", "a lépés rövidebb másfél másodpercnél")
    else:
        highlight_timing(step, time, frames, add)


def h5(step, measurement, image_dir, add):
    nonblank = True
    if image_dir is not None:
        try:
            with Image.open(Path(image_dir) / measurement["image"]) as image:
                nonblank = max(ImageStat.Stat(image.convert("RGB")).stddev) > 0.1
        except (OSError, KeyError):
            nonblank = False
    if not measurement.get("content") or measurement.get("broken") or not nonblank:
        add("H5", step["id"], "", "üres tartalom vagy törött kép")


def h8(step, measurement, add):
    expected = urlsplit(step.get("url", "")).path
    if (
        measurement.get("status") != 200
        or measurement.get("errors")
        or measurement.get("theme") != "light"
        or measurement.get("actualUrl", expected) != expected
    ):
        add("H8", step["id"], "", "HTTP, konzol, URL vagy téma eltérés")


def h9(step, add):
    if re.search(r"\[\[.*?\]\]", step["text"]):
        add("H9", step["id"], "", "kitöltetlen hely")


def h10_text(payload, contract, add):
    if payload is None:
        add("H10", "", "", "nincs build a felület-szerződéshez")
        return
    html = unescape(
        re.sub("<[^>]+>", " ", " ".join(p["html"] for p in payload["pages"]))
    )
    html = " ".join(html.split())
    rows = contract["szovegek"] + [
        {"text": text, "html": True} for text in contract.get("build_szovegek", [])
    ]
    for row in rows:
        if row.get("html") and row["text"] not in html:
            add(
                "H10",
                "",
                "",
                "a felület változott, a narrációt át kell nézni: " + row["text"],
            )


def h10_interactions(script, measurements, contract, add):
    by_id = {step["id"]: step for step in steps(script)}
    subject = next((s["url"] for s in by_id.values() if s["lap"] == "tantargy"), None)
    for rule in contract.get("interakciok", []):
        sid, role = rule["lepes"], rule.get("szereplo", "")
        if sid not in by_id:
            add("H10", sid, role, "a felület-szerződés nem létező lépésre hivatkozik")
            continue
        item = measurements.get(sid, {}).get("roles", {}).get(role, {})
        if rule["feltetel"] == "buborek":
            valid = item.get("tooltip") and not item.get("hrefs")
        else:
            valid = bool(item.get("hrefs")) and all(
                urlsplit(h).path == subject and "#ora-" in h for h in item["hrefs"]
            )
        if not valid:
            add("H10", sid, role, rule["ok"])


def gate(
    script,
    measurements,
    frame_plan=None,
    timing=None,
    *,
    payload=None,
    commit=None,
    expected_commit=None,
    audio=None,
    output=None,
    duration=None,
    contract=None,
    preview=False,
    final=True,
    image_dir=None,
):
    findings = []

    def add(code, sid, role, message):
        item = {"lepes": sid, "kod": code, "szereplo": role, "uzenet": message}
        if item not in findings:
            findings.append(item)

    by_id = {m["id"]: m for m in measurements}
    for step in steps(script):
        measurement = by_id.get(step["id"], {})
        step_checks(step, measurement, frame_plan, timing, image_dir, add)
    if not commit or commit != expected_commit:
        add("H8", "", "", "a build commitja nem a tanuló HEAD-je")
    definition = contract if contract is not None else read(ROOT / "felulet.json")
    h10_text(payload, definition, add)
    h10_interactions(script, by_id, definition, add)
    if not preview:
        h6(audio, add)
        if final:
            h7(output, duration, add)
    return report(script, findings, preview, final)


def report(script, findings, preview, final):
    order = {s["id"]: i for i, s in enumerate(steps(script))}
    findings.sort(
        key=lambda f: (order.get(f["lepes"], -1), int(f["kod"][1:]), f["szereplo"])
    )
    pending = ["H4", "H6", "H7"] if preview else ["H7"] if not final else []
    return {
        "zold": not findings and (preview or not pending),
        "elonezet": preview,
        "kep_zold": not findings,
        "kiadhato": not findings and not pending,
        "nem_mert": pending,
        "leletek": findings,
    }


def step_checks(step, measurement, frame_plan, timing, image_dir, add):
    for check in (h1, h2, h3, h8):
        check(step, measurement, add)
    h4(step, measurement, frame_plan, timing, add)
    h5(step, measurement, image_dir, add)
    h9(step, add)
