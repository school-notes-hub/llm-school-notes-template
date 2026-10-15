"""Minden lépés és kiemelés olvasható kontaktlapon, tartalmi sorrendben."""

import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from lapok import lapok_ir

from .adatok import sha, read, write
from .osszerak import frame, source
from .kamera import crop, phone_in_camera

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def contact_cell(out, step, measurement, cue):
    role = cue["szereplo"] if cue else None
    spec = {
        "image": measurement["image"],
        "crop": crop(step, measurement),
        "nezet": step["nezet"],
        "kiemel": role,
        "box": measurement["roles"].get(role, {}).get("box"),
        "alpha": 1,
    }
    picture = frame(out, spec)
    mobile = step["nezet"] == "telefon"
    height = 1050 if mobile else 510
    if mobile:
        picture = ImageOps.contain(
            picture.crop(phone_in_camera(spec["crop"])), (620, 900)
        )
    else:
        picture = picture.resize((640, 360), Image.Resampling.LANCZOS)
    cell = Image.new("RGB", (640, height), "white")
    cell.paste(picture, ((640 - picture.width) // 2, 0))
    lines = textwrap.wrap(f"{role or '–'} · {step['text']}", 68)
    if len(lines) > 7:
        raise ValueError("túl hosszú kontaktlap-felirat: " + step["id"])
    ImageDraw.Draw(cell).multiline_text(
        (8, height - 142),
        "\n".join(lines),
        font=ImageFont.truetype(FONT, 17),
        fill="black",
        spacing=4,
    )
    return cell


def table_row(step, measurement, cue, timing):
    role = cue["szereplo"] if cue else None
    time = (
        next(
            (
                f"{t['kezd_kocka'] / 30:.3f} s"
                for t in timing["lepesek"]
                if t["id"] == step["id"]
            ),
            "–",
        )
        if timing
        else "– (hang nélkül)"
    )
    text = measurement["roles"].get(role, {}).get("text", "")[:160]
    return f"{step['id']} | {time} | {step['text']} | {role or '–'} | {text}"


def scene_contacts(out, scene, by_id, timing, temporary):
    cells, pictures, table = [], {}, []
    for step in scene["lepesek"]:
        measurement = by_id[step["id"]]
        if measurement.get("before_image"):
            index = len(cells)
            before = {**measurement, "image": measurement["before_image"]}
            pictures[index] = contact_cell(out, step, before, None)
            cells.append({"kocka": index, "jelenet": scene["id"], "cimke": step["id"] + " · előtte"})
        for cue in step.get("kiemel") or [None]:
            index = len(cells)
            pictures[index] = contact_cell(out, step, measurement, cue)
            cells.append({"kocka": index, "jelenet": scene["id"], "cimke": step["id"]})
            table.append(table_row(step, measurement, cue, timing))
    size = (640, 1050 if scene["nezet"] == "telefon" else 510)
    lapok_ir(cells, pictures, temporary, oszlop=2, sor=4, cella=size)
    return table


def contacts(out, script, measurements, timing=None):
    source.cache_clear()
    by_id = {m["id"]: m for m in measurements}
    destination = out / "lapok"
    destination.mkdir(exist_ok=True)
    for old in destination.glob("*.png"):
        old.unlink()
    table, number = [], 0
    with tempfile.TemporaryDirectory(dir=out, prefix="lapok-") as folder:
        for scene in script["jelenetek"]:
            table.extend(scene_contacts(out, scene, by_id, timing, Path(folder)))
            for picture in sorted(Path(folder).glob("*.png")):
                number += 1
                picture.replace(
                    destination / f"{number:02}-{picture.name.split('-', 1)[1]}"
                )
    (out / "tabla.txt").write_text("\n".join(table) + "\n")
    return {
        str(p.relative_to(out)): sha(p.read_bytes())
        for p in sorted(destination.glob("*.png"))
    }


def review_key(out):
    script = read(out / "forgatokonyv-kitoltott.json")
    actors = read(out / "szereplok.json")
    capture = read(out / "felvetel-nyugta.json")
    for name in capture["images"]:
        if not name.startswith("kepek/") or not (out / name).resolve().is_relative_to(
            (out / "kepek").resolve()
        ):
            raise ValueError("képfájl a munkamappán kívül")
    images = {name: sha((out / name).read_bytes()) for name in capture["images"]}
    sheets = {
        str(p.relative_to(out)): sha(p.read_bytes())
        for p in sorted((out / "lapok").glob("*.png"))
    }
    return sha(
        {
            "script": script,
            "actors": actors,
            "images": images,
            "contacts": sheets,
            "boxes": read(out / "dobozok.json"),
            "capture": capture,
        }
    )


def review(out):
    key = review_key(out)
    write(out / "keys.json", {"key": key})
    choice = read(out / "valasztas.json") if (out / "valasztas.json").exists() else {}
    text = (
        f"Tanuló: {choice.get('tanulo', '–')} · Választás: {choice.get('tantargy', '–')}, {choice.get('lecke', '–')}\n"
        f"Bemenet: {out}\n"
        "Feladat: a használati videó narrációjának és állóképeinek átnézése.\n"
        "Bemenet: forgatokonyv-kitoltott.json, tabla.txt, lapok/, kapu.json, keys.json.\n"
        "Minden mondat önmagában értelmes, szó szerint igaz, és azt mondja, ami éppen a képen van.\n"
        "Semmit nem különböztet meg csak szín.\n"
        "Egy fókusz, egyféle jelölés; előbb helyére kerül, aztán jelöljük; nincs üres kép vagy felirat.\n"
        "Nézd meg az összes lépést és kiemelést; a nevek egyezzenek a látható szöveggel.\n"
        "Ne legyen holnap hamissá váló állítás. Minden hibához pontos javítást adj.\n"
        "Kimenet: verdict.json {key, verdict: accept|reject, defects: [{lepes, observed, expected, severity: hiba|javaslat}]}.\n"
        f"Kulcs: {key}\n"
    )
    (out / "review.txt").write_text(text)
    return key
