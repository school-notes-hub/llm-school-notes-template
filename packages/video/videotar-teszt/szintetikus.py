"""Szintetikus hang- és szóidő a tesztjelenetekhez: TTS és Whisper nélkül, néma hanggal.

Futtatás: python3 szintetikus.py <mappa>
Bemenet: <mappa>/narracio.json, ha van: <mappa>/kezi.json. A narráció lépésének két tesztmezője:
  "szunet": csend a lépés végén (s), mint a valódi láncban;
  "teszt_whisper": {"<narrációs szó>": "<amit a Whisper hallott>"} (a K10 eltéréséhez).
Kimenet: hangido.json (a hang.py sémája + belső szünetek), szavak.json (lépésenként
[{szo, kezd_s, veg_s, ertek, forras, whisper}], a lépés hangjához mérve), idoterv.json (a próba
idoterv.py-jának terv()-je, lépésenként a szavak kockájával), hang.wav (48 kHz, néma).
Szóidő-modell: kezdés 0,10 s, szó 0,10 s + 0,055 s/betű, köz 0,06 s, írásjel után +0,25 s szünet.
Determinisztikus: ugyanabból a narrációból bájtra ugyanaz.
"""

from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

GYOKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GYOKER))
import idoterv  # noqa: E402  (a próba kockaterv-eszköze, változatlanul)
from lanc.szavak import egy_szo  # noqa: E402

RATE, OUT_RATE, FPS = 24000, 48000, 30
KEZD_S, SZO_S, BETU_S, KOZ_S, IRASJEL_S = 0.10, 0.10, 0.055, 0.06, 0.25
LEPES_PAD_S, JELENET_PAD_S, FAROK_S = 0.25, 0.5, 0.05
HORGONY = re.compile(r"\{([^{}]+)\}")



def szamnev(szo: str):
    """A lánc számnév-olvasója (egy olvasó van: lanc.szavak.egy_szo)."""
    return egy_szo(szo)[0]


def lepes_szavai(text: str, whisper: dict) -> tuple[list[dict], dict, list, float]:
    """A lépés szavai idővel, a horgonyok első szavának ideje, a belső szünetek és a beszéd vége."""
    szavak, horg, szunetek, t = [], {}, [], KEZD_S
    for tok in re.findall(r"\{[^{}]+\}|\S+", text):
        nev = tok[1:-1] if tok.startswith("{") else None
        for i, resz in enumerate(nev.split() if nev else [tok]):
            szo = resz.strip(".,:;!?–—\"„”()")
            if not szo:
                continue
            veg = t + SZO_S + BETU_S * len(szo)
            szavak.append({"szo": szo, "kezd_s": round(t, 3), "veg_s": round(veg, 3), "ertek": szamnev(szo),
                           "forras": "whisper", "whisper": whisper.get(szo, szo)})
            if nev and i == 0:
                horg[nev] = {"kezd_s": round(t, 3), "veg_s": round(veg, 3), "forras": "whisper"}
            t = veg + KOZ_S
            if resz[-1] in ",:;":
                szunetek.append([round(veg, 3), round(veg + IRASJEL_S, 3)])
                t += IRASJEL_S
    return szavak, horg, szunetek, round(t - KOZ_S, 3)


def main(mappa: Path) -> None:
    narr = json.loads((mappa / "narracio.json").read_text(encoding="utf-8"))
    kezi_ut = mappa / "kezi.json"
    kezi = json.loads(kezi_ut.read_text(encoding="utf-8")) if kezi_ut.exists() else {}
    ido, szavak_ki, horg_ki = {"rate": RATE, "lepesek": []}, {}, {}
    for jel in narr:
        for n, lep in enumerate(jel["lepesek"], 1):
            sid = f"{jel['id']}-{n:02d}"
            szavak, horg, szunetek, beszed_veg = lepes_szavai(lep["text"], lep.get("teszt_whisper", {}))
            pad = (JELENET_PAD_S if n == len(jel["lepesek"]) else LEPES_PAD_S) + float(lep.get("szunet", 0))
            klip = round((beszed_veg + FAROK_S) * RATE)
            szunet_minta = round(pad * RATE)
            ido["lepesek"].append({"id": sid, "jelenet": jel["id"], "minta": klip + szunet_minta,
                                   "szunet_minta": szunet_minta, "beszed_kezd_s": KEZD_S, "beszed_veg_s": beszed_veg,
                                   "szunetek": szunetek, "text": lep["text"], "horgonyok": HORGONY.findall(lep["text"])})
            szavak_ki[sid] = szavak
            if horg:
                horg_ki[sid] = horg
    terv = idoterv.terv(ido, horg_ki, kezi, FPS)
    for lep in terv["lepesek"]:
        ki = []
        for w in szavak_ki[lep["id"]]:
            abs_s = lep["hang_kezd_s"] + w["kezd_s"]
            k = min(max(idoterv.s_kocka(abs_s - idoterv.ELORE_S, FPS), lep["kezd_kocka"]), lep["veg_kocka"] - 1)
            ki.append({"szo": w["szo"], "ertek": w["ertek"], "szo_s": round(abs_s, 4), "kocka": k, "forras": w["forras"]})
        lep["szavak"] = ki
    iras = {"hangido.json": ido, "szavak.json": szavak_ki, "idoterv.json": terv}
    for nev, adat in iras.items():
        (mappa / nev).write_text(json.dumps(adat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    minta = sum(s["minta"] for s in ido["lepesek"]) * OUT_RATE // RATE
    with wave.open(str(mappa / "hang.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(OUT_RATE)
        w.writeframes(bytes(2 * minta))
    print(f"{mappa.name}: {len(ido['lepesek'])} lépés, {terv['kocka_osszes']} kocka "
          f"({terv['kocka_osszes'] / FPS:.1f} s), {sum(len(v) for v in szavak_ki.values())} szó")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
