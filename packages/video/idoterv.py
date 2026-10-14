"""Kockaterv a videóhoz a fix hangból (Manim nélkül): <mappa>/idoterv.json.

Futtatás: python3 idoterv.py <mappa> [--fps 30]
Bemenet: <mappa>/hangido.json (a hang.py írja), ha van: <mappa>/horgonyok.json és <mappa>/kezi.json.
Kimenet: <mappa>/idoterv.json:
  {"fps": 30, "elore_s": 0.1, "rate": 24000, "kocka_osszes": N,
   "lepesek": [{"id": "s01-10", "kezd_kocka": 512, "veg_kocka": 571, "anim_kocka": 512,
                "hang_kezd_s": 17.067, "hang_veg_s": 19.033,
                "horgonyok": {"huszonegy": {"kocka": 543, "szo_s": 18.191, "forras": "whisper"}}}]}
Kockaszámítás: kocka = round(abs_s · fps), a videó elejéhez mérve (egész mintaszámból, felfelé kerekítve
a felénél), így a kerekítés nem halmozódik. A lépés a kezd_kocka-tól a veg_kocka előttig tart.
anim_kocka: a lépés első animációjának kockája; ha a TTS elején 0,2 s-nál több a csend, a beszéd
kezdete − ELORE, különben a lépés első kockája.
Horgony: a lépés `{…}` jelölésű szavai (hangido.json `horgonyok`). Az idejük a horgonyok.json-ból jön
({lépés: {név: {kezd_s, veg_s?, forras}}}, a lépés fájljához mérve), a kezi.json felülírja
({"<lépés>@<név>": {"kezd_s": …}} a horgony ideje, {"<lépés>": {"eltolas_s": …}} a lépés minden
horgonyát eltolja). A horgony kockája: szó kezdete − ELORE (+ eltolás), a lépésen belülre szorítva.
Ha egy jelölt horgonynak nincs ideje, vagy van idő jelöletlen horgonyhoz, hibával áll le.
"""

import argparse
import json
import sys
from pathlib import Path

ELORE_S = 0.1          # ennyivel jön előbb a kép a szónál
CSEND_ELEJEN_S = 0.2   # ennél több TTS-csend a lépés elején: az első animáció a beszédhez tolódik


def kocka(minta: int, rate: int, fps: int) -> int:
    """round(minta / rate · fps) egészekkel, a felénél felfelé (pontos, nincs lebegőpontos hiba)."""
    return (2 * minta * fps + rate) // (2 * rate)


def s_kocka(s: float, fps: int) -> int:
    return int(s * fps + 0.5)


def terv(ido: dict, horg: dict, kezi: dict, fps: int) -> dict:
    rate, hibak, lepesek, minta = ido["rate"], [], [], 0
    ismert = {s["id"] for s in ido["lepesek"]}
    for kulcs in kezi:
        if kulcs.split("@")[0] not in ismert:
            hibak.append(f"kezi.json: ismeretlen lépés {kulcs}")
    for sid in horg:
        if sid not in ismert:
            hibak.append(f"horgonyok.json: ismeretlen lépés {sid}")
    for s in ido["lepesek"]:
        kezd_s, kk, vk = minta / rate, kocka(minta, rate, fps), kocka(minta + s["minta"], rate, fps)
        anim = s_kocka(kezd_s + s["beszed_kezd_s"] - ELORE_S, fps) if s["beszed_kezd_s"] > CSEND_ELEJEN_S else kk
        lepes = {"id": s["id"], "kezd_kocka": kk, "veg_kocka": vk, "anim_kocka": min(max(anim, kk), vk - 1),
                 "hang_kezd_s": round(kezd_s, 4), "hang_veg_s": round((minta + s["minta"]) / rate, 4),
                 "horgonyok": {}}
        jelolt, merve = list(s.get("horgonyok", [])), dict(horg.get(s["id"], {}))
        for nev, adat in kezi.items():
            if "@" in nev and nev.split("@")[0] == s["id"]:
                merve[nev.split("@", 1)[1]] = dict(merve.get(nev.split("@", 1)[1], {}), **adat, forras="kezi")
        for nev in sorted(set(merve) - set(jelolt)):
            hibak.append(f"{s['id']}: a(z) {nev!r} horgonynak van ideje, de a szövegben nincs {{…}} jelölése")
        eltolas = float(kezi.get(s["id"], {}).get("eltolas_s", 0))
        elozo = None
        for nev in jelolt:
            if nev not in merve or "kezd_s" not in merve[nev]:
                hibak.append(f"{s['id']}: a(z) {{{nev}}} horgonynak nincs ideje (horgonyok.json vagy kezi.json)")
                continue
            szo = kezd_s + float(merve[nev]["kezd_s"])
            k = min(max(s_kocka(szo - ELORE_S + eltolas, fps), kk), vk - 1)
            if elozo is not None and k <= elozo:
                hibak.append(f"{s['id']}: a(z) {{{nev}}} horgony nem az előző horgony után esik")
            elozo = k
            lepes["horgonyok"][nev] = {"kocka": k, "szo_s": round(szo, 4), "forras": merve[nev].get("forras", "?")}
        lepesek.append(lepes)
        minta += s["minta"]
    if hibak:
        raise SystemExit("hiba:\n  " + "\n  ".join(hibak))
    return {"fps": fps, "elore_s": ELORE_S, "rate": rate, "kocka_osszes": kocka(minta, rate, fps),
            "lepesek": lepesek}


def betolt(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mappa", type=Path)
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    mappa = a.mappa.resolve()
    if not (mappa / "hangido.json").exists():
        sys.exit(f"hiba: nincs {mappa / 'hangido.json'} (előbb a hang.py)")
    t = terv(betolt(mappa / "hangido.json"), betolt(mappa / "horgonyok.json"), betolt(mappa / "kezi.json"), a.fps)
    (mappa / "idoterv.json").write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    nh = sum(len(s["horgonyok"]) for s in t["lepesek"])
    print(f"idoterv.json: {len(t['lepesek'])} lépés, {nh} horgony, {t['kocka_osszes']} kocka "
          f"({t['kocka_osszes'] / t['fps']:.3f} s, {t['fps']} fps)")


if __name__ == "__main__":
    main()
