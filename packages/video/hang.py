"""Egy narrátoros videóhang a podcast beszédkódjával (sn-helyi release), lépésenként egy hívás.

Futtatás:
  uv run --quiet --frozen --project ../school-notes2 python hang.py <tanuló> <mappa>      (a packages/video mappából)
Bemenet: <mappa>/narracio.json: [{id, lepesek: [{text, kepernyo, szunet?}]}] (régi alak: [{id, text}] = egy lépés).
A `text`-ben a {…} szóhoz kötött horgonyt jelöl: a TTS előtt csak a zárójel törlődik, a szó marad, így a
TTS-bemenet (és a gyorsítótár kulcsa) ugyanaz, mint jelölés nélkül.
Kimenet: <mappa>/hang/<id>-<n>.wav lépésenként (24 kHz mono; utána 0,25 s, a jelenet utolsó lépése után
0,5 s csend, plusz a lépés `szunet` mezője másodpercben: gondolkodási idő), <mappa>/hang.wav (az egész,
egymás után, 48 kHz), <mappa>/hangido.json (lépésenként egész mintaszám, lásd `lepes_ido`) és a régi
kód kedvéért <mappa>/hosszak.json ({id: [lépéshossz s, ...]}).
Lépésenként egy hívás, így minden mondat kezdete és vége pontosan ismert: az animáció lépései ehhez igazodnak.
A hívás a podcast közös gyorsítótárán, költségkeretén és naplóján megy át: ugyanaz a szöveg újra nem fizet.
Önellenőrzés: a hang.wav mintaszáma = a lépések mintaszámának összege × 48000/24000 (a loudnorm és az
átmintavételezés megtartja a hosszt), különben hibával áll le.
"""

import json
import math
import re
import subprocess
import sys
import time
import wave
from array import array
from pathlib import Path

from school_notes2.images.budget import images_lock
from school_notes2.local import common
from school_notes2.local.podcast_names import _client
from school_notes2.podcast import speech
from school_notes2.podcast.ledger import Cache, Ledger, speech_reserve

VOICE = "Puck"
STYLE = ("Magyar ismeretterjesztő videó narrátora: nyugodt, barátságos, kíváncsi hang, mint aki egy szép "
         "felfedezést mutat meg; természetes tempó, a kulcsszavaknál apró hangsúly, nem felolvas, hanem magyaráz.")
STEP_PAD_S, SCENE_PAD_S = 0.25, 0.5
OUT_RATE = 48000
HORGONY = re.compile(r"\{([^{}]+)\}")
CSEND_DB, KERET_S = -55.0, 0.01  # beszédhatár: az első/utolsó 10 ms-os keret, amelynek RMS-e -55 dBFS fölött van (-40-nél a halk kezdőhang 0,1–0,2 s-mal később talált)


def tts_szoveg(text: str) -> str:
    """A TTS-bemenet: a {…} horgonyjelekből csak a zárójel törlődik."""
    out = HORGONY.sub(r"\1", text)
    if "{" in out or "}" in out:
        raise ValueError(f"páratlan vagy egymásba ágyazott kapcsos zárójel: {text!r}")
    return out


def horgonyok(text: str) -> list[str]:
    """A lépés horgonynevei a szöveg sorrendjében; lépésen belül egyedinek kell lenniük."""
    nevek = HORGONY.findall(text)
    if len(set(nevek)) != len(nevek):
        raise ValueError(f"ismétlődő horgonynév egy lépésen belül: {text!r}")
    return nevek


def szunet_s(n: int, steps: list, step: dict) -> float:
    """A lépés utáni csend másodpercben: 0,25 s, a jelenet végén 0,5 s, plusz a `szunet` mező."""
    return (SCENE_PAD_S if n == len(steps) else STEP_PAD_S) + float(step.get("szunet", 0))


def beszed(pcm: bytes, rate: int) -> tuple[float, float]:
    """Hol kezd és hol ér véget a beszéd a lépés hangjában (s, a lépés elejétől); helyi RMS, 10 ms-os keretek."""
    minta = array("h")
    minta.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        minta.byteswap()
    meret, kuszob = int(rate * KERET_S), 32768 * 10 ** (CSEND_DB / 20)
    hangos = []
    for i in range(0, len(minta), meret):
        keret = minta[i:i + meret]
        if math.sqrt(sum(x * x for x in keret) / len(keret)) > kuszob:
            hangos.append(i)
    if not hangos:
        return 0.0, 0.0
    return round(hangos[0] / rate, 3), round(min(len(minta), hangos[-1] + meret) / rate, 3)


def lepes_ido(sid: str, n: int, step: dict, pcm: bytes, szunet_minta: int, rate: int) -> dict:
    """A hangido.json egy lépése. `pcm` a beszéd csend nélkül; a `minta` a csenddel együtt értendő."""
    kezd, veg = beszed(pcm, rate)
    return {"id": f"{sid}-{n:02d}", "jelenet": sid, "minta": len(pcm) // 2 + szunet_minta,
            "szunet_minta": szunet_minta, "beszed_kezd_s": kezd, "beszed_veg_s": veg,
            "text": step["text"], "horgonyok": horgonyok(step["text"])}


def hang_osszefuz(folder: Path, parts: list[Path]) -> Path:
    """A lépések wav-jai egymás után, hangosságra igazítva, 48 kHz-en: <mappa>/hang.wav."""
    listing = folder / "hang" / "lista.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(OUT_RATE), str(folder / "hang.wav")],
                   check=True)
    return folder / "hang.wav"


def hang_ellenoriz(wav: Path, ido: dict) -> None:
    """Önellenőrzés: a hang.wav mintaszáma = a lépések mintaszámának összege, 48 kHz-re váltva."""
    with wave.open(str(wav)) as w:
        van, rate = w.getnframes(), w.getframerate()
    vart = sum(s["minta"] for s in ido["lepesek"]) * rate // ido["rate"]
    if van != vart:
        raise SystemExit(f"hiba: a {wav.name} {van} minta, a lépésekből {vart} várható (eltérés {van - vart})")
    print(f"önellenőrzés: {wav.name} {van} minta = a lépések összege ({van / rate:.3f} s)")


def main(learner: str, folder: Path) -> None:
    scenes = json.loads((folder / "narracio.json").read_text())
    local = common.load(learner)
    settings = local.podcast_settings()
    client = _client(settings, time.sleep)
    out = folder / "hang"
    out.mkdir(exist_ok=True)
    lengths, parts, ido = {}, [], {"rate": speech.RATE, "lepesek": []}
    with images_lock(settings.lock_path, settings.lock_timeout_s, what="podcast"):
        ledger, cache = Ledger(settings), Cache(settings.cache_dir)
        paid = speech.Paid(client, ledger, cache, f"video-hang/{folder.name}")
        for scene in scenes:
            steps = scene.get("lepesek") or [{"text": scene["text"]}]
            lengths[scene["id"]] = []
            for n, step in enumerate(steps, 1):
                text = tts_szoveg(step["text"])
                request = {"model": speech.MODEL, "voice": VOICE, "response_format": "pcm", "instructions": STYLE,
                           "input": text}
                pcm = paid.speech(request, len(text))
                gap = int(szunet_s(n, steps, step) * speech.RATE)
                ido["lepesek"].append(lepes_ido(scene["id"], n, step, pcm, gap, speech.RATE))
                pcm += b"\0\0" * gap
                path = out / f"{scene['id']}-{n:02d}.wav"
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(speech.RATE), w.writeframes(pcm)
                lengths[scene["id"]].append(round(len(pcm) / 2 / speech.RATE, 3))
                parts.append(path)
            print(f"{scene['id']}: {len(steps)} lépés, {sum(lengths[scene['id']]):.2f} s")
    for line in paid.warnings:
        print("figyelmeztetés:", line)
    (folder / "hosszak.json").write_text(json.dumps(lengths, indent=2) + "\n")
    (folder / "hangido.json").write_text(json.dumps(ido, ensure_ascii=False, indent=1) + "\n")
    hang_ellenoriz(hang_osszefuz(folder, parts), ido)
    cost = sum(c.get("cost_usd") or 0 for c in paid.opened)
    print(f"összesen {sum(map(sum, lengths.values())):.1f} s, {len(paid.opened)} fizetős hívás, könyvelt költség {cost} USD")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]).resolve())
