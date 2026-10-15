"""Guarded production through the existing speech chain."""

import os
from pathlib import Path
from lanc.hangok import Csonk, Valodi, hang_es_szavak, idoterv_szavakkal
from .adatok import read, write, steps, sha
from .kitolt import contract
from .kapu_h import gate
from .lapok_h import contacts, review_key
from .osszerak import plan, render
from .elonezet import surface_payload


def accepted(out):
    verdict = read(out / "verdict.json")
    return (
        verdict.get("verdict") == "accept"
        and verdict.get("key") == review_key(out)
        and not any(d.get("severity") == "hiba" for d in verdict.get("defects", []))
    )


def production_preflight(local, out):
    if not accepted(out):
        raise ValueError("nincs accept a mostani képekre és narrációra")
    if not read(out / "kapu.json")["kep_zold"]:
        raise ValueError("piros előnézet; előbb javítás és új review kell")
    script, choice = (
        read(out / "forgatokonyv-kitoltott.json"),
        read(out / "valasztas.json"),
    )
    if contract():
        raise ValueError("a felület szövege változott; új előnézet és review kell")
    fresh = gate(
        script,
        read(out / "dobozok.json"),
        payload=surface_payload(Path(choice["build"])),
        commit=choice["commit"],
        expected_commit=local.git().out("rev-parse", "HEAD").strip(),
        preview=True,
        image_dir=out,
    )
    if not fresh["kep_zold"]:
        write(out / "kapu.json", fresh)
        raise ValueError("a képi kapu már nem zöld; fizetős hívás nem indult")
    return script, choice


def sound(local, out, script):
    # The existing sound helper numbers steps per scene; preserve stable IDs around it.
    narration = [{"id": s["id"], "lepesek": [s]} for s in steps(script)]
    provider = (
        Csonk(narration)
        if os.environ.get("VIDEO_CSONK") == "1"
        else Valodi(local.name, "hasznalat/" + out.name, local=local)
    )
    with (out / "video.log").open("a") as log:
        audio = hang_es_szavak(out, narration, provider, log)
    timing = idoterv_szavakkal(out, 30)
    for step in timing["lepesek"]:
        step["id"] = step["id"].removesuffix("-01")
    write(out / "idoterv.json", timing)
    audio = {"k10": audio["k10"], "hossz_s": audio["hossz_s"]}
    write(out / "hang-ellenorzes.json", audio)
    return timing, audio, provider.csonk


def produce(local, out):
    script, choice = production_preflight(local, out)
    timing, audio, stub = sound(local, out, script)
    measurements = read(out / "dobozok.json")
    frames = plan(script, measurements, timing)
    write(out / "kockaterv.json", frames)
    render(out, frames)
    report = gate(
        script,
        measurements,
        frames,
        timing,
        payload=surface_payload(Path(choice["build"])),
        commit=choice["commit"],
        expected_commit=local.git().out("rev-parse", "HEAD").strip(),
        audio=audio,
        final=False,
        image_dir=out,
    )
    write(out / "kapu.json", report)
    contacts(out, script, measurements, timing)
    files = [
        "fo.mp4",
        "hang.wav",
        "idoterv.json",
        "hang-ellenorzes.json",
        "kockaterv.json",
    ]
    write(
        out / "gyartas.json",
        {
            "csonk": stub,
            "files": {name: sha((out / name).read_bytes()) for name in files},
        },
    )
    return 0 if report["kep_zold"] else 1
