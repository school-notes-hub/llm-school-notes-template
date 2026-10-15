"""Final cards, gate and receipt, independent of command dispatch."""

import shutil
import subprocess
from pathlib import Path
from lanc import nyitozaro
from school_notes2 import VERSION
from .adatok import read, write, sha
from .kapu_h import gate
from .kapu_kiadas import exceptions
from .lapok_h import review_key
from .elonezet import surface_payload
from .gyartas import accepted


def final_preflight(out):
    if not accepted(out):
        raise ValueError("nincs érvényes accept")
    report = read(out / "kapu.json")
    if (out / "kapu-kivetel.json").exists():
        report = exceptions(report, read(out / "kapu-kivetel.json"), review_key(out))
    if not report.get("kep_zold"):
        raise ValueError("piros gyártási kapu")
    for name, digest in read(out / "gyartas.json")["files"].items():
        if sha((out / name).read_bytes()) != digest:
            raise ValueError("megváltozott gyártási bemenet: " + name)


def final_receipt(local, out, script, selection, timing, cards, report):
    capture = read(out / "felvetel-nyugta.json")
    measurements = read(out / "dobozok.json")
    shutil.copyfile(out / measurements[0]["image"], out / "hasznalat.png")
    starts = {t["id"]: t["kezd_kocka"] / 30 for t in timing["lepesek"]}
    chapters = [
        {
            "jelenet": j.get("cim", j["id"]),
            "masodperc": cards["nyito_s"] + starts[j["lepesek"][0]["id"]],
        }
        for j in script["jelenetek"]
        if j["lepesek"]
    ]
    receipt = {
        "vegleges": True,
        "csonk": read(out / "gyartas.json")["csonk"],
        "tanulo": local.name,
        "key": review_key(out),
        "commit": selection["commit"],
        "template": VERSION,
        "chromium": capture["chromium"],
        "ffmpeg": subprocess.check_output(
            ["ffmpeg", "-version"], text=True
        ).splitlines()[0],
        "outputs": {
            name: sha((out / name).read_bytes())
            for name in ["hasznalat.mp4", "hasznalat.png"]
        },
        "fejezetek": chapters,
        "hossz_s": timing["kocka_osszes"] / 30 + cards["nyito_s"] + cards["zaro_s"],
        "kepek": [asset for m in measurements for asset in m["assets"]],
        "kapu_sha256": sha((out / "kapu.json").read_bytes()),
        "forgatokonyv_sha256": sha((out / "forgatokonyv-kitoltott.json").read_bytes()),
        "felulbiralasok": [f for f in report["leletek"] if f.get("felulbiralva")],
    }
    write(out / "nyugta.json", receipt)


def finalize(local, out):
    final_preflight(out)
    script, selection = (
        read(out / "forgatokonyv-kitoltott.json"),
        read(out / "valasztas.json"),
    )
    audio, timing = read(out / "hang-ellenorzes.json"), read(out / "idoterv.json")
    cards = final_cards(out)
    report = gate(
        script,
        read(out / "dobozok.json"),
        read(out / "kockaterv.json"),
        timing,
        payload=surface_payload(Path(selection["build"])),
        commit=selection["commit"],
        expected_commit=local.git().out("rev-parse", "HEAD").strip(),
        audio=audio,
        output=out / "hasznalat.mp4",
        duration=timing["kocka_osszes"] / 30 + cards["nyito_s"] + cards["zaro_s"],
        image_dir=out,
    )
    if (out / "kapu-kivetel.json").exists():
        report = exceptions(report, read(out / "kapu-kivetel.json"), review_key(out))
    write(out / "kapu.json", report)
    if not report["zold"]:
        return 1
    final_receipt(local, out, script, selection, timing, cards, report)
    return 0


def final_cards(out):
    cards = nyitozaro.kepek(
        out / "fo.mp4",
        out / "media",
        "1080p",
        "School Notes",
        "Hogyan használd a jegyzetoldalt?",
        out / "video.log",
        1800,
    )
    nyitozaro.osszefesul(
        cards,
        out / "fo.mp4",
        out / "hang.wav",
        out / "hasznalat.mp4",
        out / "video.log",
        threads=4,
    )
    return cards
