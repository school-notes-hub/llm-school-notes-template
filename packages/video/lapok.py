"""Kontaktlapok, egyedi kockák, kivágatok és lépéskulcsok a lektornak (terv-menet.md 2. és 5. pont).

- kockak/: a kiválasztott kockák a renderelt videóból (egy ffmpeg-dekódolás), determinisztikus névvel:
  <jelenet>-eleje.png, <lépés>@<horgony>.png, <lépés>-eredmeny.png, <lépés>-vege.png.
- lapok/NN-<jelenet>[-b].png: 1920×1140, 3×3 cella (640×360-as bélyeg + 20 px címkesáv, `!` a
  figyelmeztetéses lépés kockáján); a jelenet új lapon kezdődik.
- lapok-iro/NN-<jelenet>[-<jelenet>].png: az író 480p-s futásának sűrű lapjai (4×4 cella, `iro_lapok`), ugyanazokkal
  a kockákkal; az író átadás előtt egy üzenetben nézi meg őket (10. és 12. szabály).
- kivagat/<lépés>-<obj>.png: a K4/K6b/K7 figyelmeztetés objektuma körül, eredeti felbontásban (min. 600×400).
- lepeskulcs.json: lépésenként a szöveg, a relatív események és a végállapot kulcsa; --valtozott:
  lapok-valtozott/ a lepeskulcs-1.json-hoz képest változott lépésekre és a rákövetkezőjükre.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from kapu import W, H, Munka, ido, json_ir

CELLA_W, CELLA_H, SAV = 640, 360, 20
RACS = 3
KIVAGAT_MIN = (600, 400)
KIVAGAT_MARGO = 40
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _fajlnev(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_@.-]+", "_", s)


# --- melyik kocka ------------------------------------------------------------------

def kockalista(mu: Munka, k: dict, csak: set[str] | None = None) -> list[dict]:
    """A lapok kockái: jelenetenként az első, lépésenként a horgonyok, a Szamolas-eredmény és a vége."""
    figy = {x["lepes"] for x in k["leletek"] if not x.get("elfogadva") and not x.get("felulbiralva")}
    ki, lattam, jelenet = [], set(), None
    for t in mu.tl:
        sid, kk, vk = t["id"], t["kezd_kocka"], t["veg_kocka"]
        jel = mu.narr_lepes.get(sid, {}).get("jelenet", sid.split("-")[0])
        uj_jelenet = jel != jelenet
        jelenet = jel
        if csak is not None and sid not in csak:
            continue
        jelolt = "! " if sid in figy else ""
        tetel = []
        if uj_jelenet:
            tetel.append((kk, f"{jel}-eleje", f"{jel} eleje {ido(kk / mu.fps)}"))
        hs = sorted(t["horgonyok"].items(), key=lambda x: (x[1]["kocka"], x[0]))
        for i, (nev, h) in enumerate(hs):
            veg = (hs[i + 1][1]["kocka"] if i + 1 < len(hs) else vk) - 1
            tetel.append((veg, f"{sid}@{nev}", f"{jelolt}{sid} @{nev} {ido(veg / mu.fps)}"))
        l = mu.lmap.get(sid, {})
        for e in sorted(l.get("megjelenik", []), key=lambda e: (e["veg_kocka"], e["obj"])):
            if e["kat"] == "eredmeny" and e["veg_kocka"] < vk - 1:
                tetel.append((e["veg_kocka"], f"{sid}-eredmeny", f"{jelolt}{sid} eredmény {ido(e['veg_kocka'] / mu.fps)}"))
                break
        tetel.append((vk - 1, f"{sid}-vege", f"{jelolt}{sid} vége {ido((vk - 1) / mu.fps)}"))
        for kocka, nev, cimke in sorted(tetel):
            if kocka in lattam:
                continue
            lattam.add(kocka)
            ki.append({"kocka": kocka, "nev": _fajlnev(nev), "cimke": cimke, "lepes": sid, "jelenet": jel})
    return ki


def kivesz(mp4: Path, kockak: list[int], meret: tuple[int, int]):
    """A kért kockák (növekvő, egyedi) RGB-bájtjai egyetlen dekódolással, sorrendben."""
    from PIL import Image
    if not kockak:
        return {}
    expr = "+".join(f"eq(n\\,{k})" for k in kockak)
    w, h = meret
    p = subprocess.run(["ffmpeg", "-v", "error", "-threads", "0", "-i", str(mp4), "-map", "0:v:0",
                        "-vf", f"select='{expr}'", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True)
    n = w * h * 3
    if len(p.stdout) != n * len(kockak):
        raise RuntimeError(f"{len(kockak)} kocka helyett {len(p.stdout) // n} jött a(z) {mp4.name}-ból")
    return {k: Image.frombytes("RGB", (w, h), p.stdout[i * n:(i + 1) * n]) for i, k in enumerate(kockak)}


def _ures(mappa: Path) -> Path:
    if mappa.exists():
        shutil.rmtree(mappa)
    mappa.mkdir(parents=True)
    return mappa


def _font(meret: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(FONT), meret)
    except OSError:
        return ImageFont.load_default(meret)


def lapok_ir(lista: list[dict], kepek: dict, cel: Path, oszlop: int = RACS, sor: int = RACS,
             cella: tuple[int, int] = (CELLA_W, CELLA_H), jelenetenkent: bool = True) -> int:
    """Kontaktlapok a `cel` mappába. A lektoré (alapértékek): 3×3 cella, a jelenet új lapon kezdődik. Az íróé
    (`iro_lapok`): sűrű rács, a lapok folyamatosan telnek (a jelenet elejét a cella címkéje mutatja)."""
    from PIL import Image, ImageDraw
    _ures(cel)
    font = _font(14)
    cw, ch = cella
    lapok: list[tuple[str, list]] = []
    for x in lista:
        uj_jelenet = jelenetenkent and bool(lapok) and lapok[-1][1][-1]["jelenet"] != x["jelenet"]
        if not lapok or uj_jelenet or len(lapok[-1][1]) == oszlop * sor:
            folyt = jelenetenkent and bool(lapok) and lapok[-1][1][-1]["jelenet"] == x["jelenet"]
            nev = x["jelenet"] if not folyt else f"{x['jelenet']}-{chr(ord('a') + sum(1 for l in lapok if l[1][0]['jelenet'] == x['jelenet']))}"
            lapok.append((nev, [x]))
        else:
            lapok[-1][1].append(x)
    for i, (nev, cellak) in enumerate(lapok, 1):
        if not jelenetenkent and cellak[-1]["jelenet"] != cellak[0]["jelenet"]:
            nev = f"{cellak[0]['jelenet']}-{cellak[-1]['jelenet']}"
        sorok, oszlopok = -(-len(cellak) // oszlop), min(len(cellak), oszlop)   # csak a használt rács (kevesebb képtoken)
        lap = Image.new("RGB", (cw * oszlopok, (ch + SAV) * sorok), (0, 0, 0))
        d = ImageDraw.Draw(lap)
        for j, x in enumerate(cellak):
            ox, oy = (j % oszlop) * cw, (j // oszlop) * (ch + SAV)
            lap.paste(kepek[x["kocka"]].resize((cw, ch), Image.Resampling.LANCZOS), (ox, oy))
            d.rectangle([ox, oy + ch, ox + cw - 1, oy + ch + SAV - 1], fill=(48, 48, 48))
            d.text((ox + 6, oy + ch + 2), x["cimke"], fill=(255, 210, 80) if x["cimke"].startswith("!") else (235, 235, 235),
                   font=font)
        lap.save(cel / f"{i:02d}-{nev}.png", optimize=False, compress_level=6)
    return len(lapok)


# Az író 480p-s futásának kontaktlapjai: ugyanazok a kockák, mint a lektoré (`kockalista`), de sűrűbben, mert
# az író LLM-ként nézi őket (a képtoken a lap területével nő, ezért kevés, teli lap): 4×4 cella, 480×270 px
# (a 854×480-as kocka fele), egy lap 1920×1160. Egy 5 perces videó kb. 70 kockája így 5 lap (a lektoré 9–13).
# A modell a lapot kb. 1400–1570 px szélesre kicsinyíti (cella kb. 350–390 px): a mérlegvideó lapján a testek
# formája, a karok aránya, a nyilak és a feliratok helye így is megítélhető (12. szabály); a képletek apró
# indexei nem, azokat a kapu (K5) és a lektor nézi. A 3×3-as rács ugyanennyi kockára kb. 60%-kal több képtoken.
IRO_OSZLOP, IRO_SOR, IRO_CELLA = 4, 4, (480, 270)
IRO_MAPPA = "lapok-iro"


def iro_lapok(mu: Munka, k: dict) -> tuple[int, int, Path]:
    """Az író futásának kontaktlapjai a lapok-iro/ alá (minden futás újraírja): (lapszám, kockaszám, mappa)."""
    lista = kockalista(mu, k)
    kepek = kivesz(mu.mp4, sorted({x["kocka"] for x in lista}), tuple(mu.naplo["felbontas"]))
    cel = mu.m / IRO_MAPPA
    n = lapok_ir(lista, kepek, cel, IRO_OSZLOP, IRO_SOR, IRO_CELLA, jelenetenkent=False)
    return n, len(lista), cel


def kivagat(kep, doboz: list[int], cel: Path) -> None:
    """Kivágat a dobozra (1920×1080-as px) a kép saját felbontásában, margóval, legalább 600×400."""
    w, h = kep.size
    s = w / W
    x0, y0, x1, y1 = [round(v * s) for v in doboz]
    x0, y0, x1, y1 = x0 - KIVAGAT_MARGO, y0 - KIVAGAT_MARGO, x1 + KIVAGAT_MARGO, y1 + KIVAGAT_MARGO
    for a, b, mn, lim in ((0, 2, min(KIVAGAT_MIN[0], w), w), (1, 3, min(KIVAGAT_MIN[1], h), h)):
        v = [x0, y0, x1, y1]
        if v[b] - v[a] < mn:
            c = (v[a] + v[b]) // 2
            v[a], v[b] = c - mn // 2, c - mn // 2 + mn
        if v[a] < 0:
            v[a], v[b] = 0, v[b] - v[a]
        if v[b] > lim:
            v[a], v[b] = max(0, v[a] - (v[b] - lim)), lim
        x0, y0, x1, y1 = v
    kep.crop((x0, y0, x1, y1)).save(cel, compress_level=6)


def iro_kivagat(mappa: Path, lepes: str, obj: str, kep_png: Path) -> Path:
    """Az író --kivagat-ja: a lépés végállapotának állóképe (Manim -s, IG=<lépés>) az objektum dobozára vágva."""
    from PIL import Image
    mu = Munka(mappa)
    o = next((o for o in mu.lmap[lepes]["allapot"]["vege"] if o["obj"] == obj or o["csoport"] == obj), None)
    if o is None:
        raise KeyError(f"{lepes}: nincs {obj} a végállapotban")
    dd = [o2["doboz"] for o2 in mu.lmap[lepes]["allapot"]["vege"] if o2["obj"] == obj or o2["csoport"] == obj]
    d = [min(x[0] for x in dd), min(x[1] for x in dd), max(x[2] for x in dd), max(x[3] for x in dd)]
    cel = mu.m / "kivagat" / f"iro-{_fajlnev(lepes)}-{_fajlnev(obj)}.png"
    cel.parent.mkdir(exist_ok=True)
    kivagat(Image.open(kep_png).convert("RGB"), d, cel)
    return cel


# --- lépéskulcs ------------------------------------------------------------------

def _h(x) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _n(nev: str) -> str:
    return nev.split("#")[0]   # az automatikus sorszám (Text#7) egy korábbi új objektumtól elcsúszhat


def lepeskulcs(mu: Munka) -> dict:
    ki = {}
    for t in mu.tl:
        sid, l = t["id"], mu.lmap.get(t["id"], {})
        kk = l.get("kezd_kocka", t["kezd_kocka"])
        ev = sorted([("meg", _n(e["obj"]), e["kocka"] - kk, e["veg_kocka"] - e["kocka"], e["ok"], e.get("tartalom", ""))
                     for e in l.get("megjelenik", [])] +
                    [(f, _n(s["obj"]), s["tol"] - kk, s["ig"] - s["tol"], "", "") for f in ("mozog", "atalakul")
                     for s in l.get(f, [])] +
                    [(f, _n(e["obj"]), e["kocka"] - kk, e["veg_kocka"] - e["kocka"], "", "") for f in ("eltunik", "szinvaltas")
                     for e in l.get(f, [])] +
                    [("szo", e.get("szora") or e.get("horgony"), e["kezd_kocka"] - kk, 0, "", "")
                     for e in l.get("elemek", []) if e.get("szora") or e.get("horgony")])
        vege = sorted((_n(o["obj"]), o["kat"], [2 * round(v / 2) for v in o["doboz"]], o.get("tartalom", ""), o.get("szin", ""))
                      for o in (l.get("allapot") or {}).get("vege", []))
        ki[sid] = {"szoveg": _h(mu.narr_lepes.get(sid, {}).get("text", "")), "esemenyek": _h(ev), "vege": _h(vege)}
    return {"sema": "lepeskulcs/1", "lepesek": ki}


def valtozott_lepesek(uj: dict, regi: dict | None, ids: list[str]) -> set[str]:
    r = (regi or {}).get("lepesek", {})
    valt = [sid for sid in ids if uj["lepesek"].get(sid) != r.get(sid)]
    ki = set(valt)
    for sid in valt:
        i = ids.index(sid)
        if i + 1 < len(ids):
            ki.add(ids[i + 1])
    return ki


# --- az átadás -------------------------------------------------------------------

KIVAGAT_MAX = 5          # kivágat körönként (a terv szerint legfeljebb 5)


def atadas(mu: Munka, k: dict, valtozott: bool = False) -> str:
    m = mu.m
    # lépéskulcs: az előző átadásé lepeskulcs-1.json lesz (azonos újrafuttatásnál marad)
    uj = lepeskulcs(mu)
    p, p1 = m / "lepeskulcs.json", m / "lepeskulcs-1.json"
    if p.exists() and json.loads(p.read_text(encoding="utf-8")) != uj:
        p.replace(p1)
    json_ir(p, uj)
    csak = None
    if valtozott:
        regi = json.loads(p1.read_text(encoding="utf-8")) if p1.exists() else None
        csak = valtozott_lepesek(uj, regi, mu.ids)
    lista = kockalista(mu, k)
    kiv = sorted((x for x in k["leletek"] if x["kod"] in ("K4", "K6b", "K7") and x["sulyossag"] == "figy"
                  and x.get("doboz")), key=lambda x: (x["lepes"] or "", x["kod"], x["obj"] or ""))
    kiv, kimarad = kiv[:KIVAGAT_MAX], kiv[KIVAGAT_MAX:]
    if kimarad:                           # a tábla végére: ezekhez a lektor kér kivágatot, ha kell
        with open(m / "tabla.txt", "a", encoding="utf-8") as f:
            f.write(f"+{len(kimarad)} kivágat nélkül (körönként legfeljebb {KIVAGAT_MAX}): "
                    + ", ".join(f"{x['lepes']}/{x['obj']} {x['kod']}" for x in kimarad) + "\n")
    vege = {t["id"]: t["veg_kocka"] - 1 for t in mu.tl}
    horgony_kocka = {}
    for t in mu.tl:
        hs = sorted(t["horgonyok"].items(), key=lambda x: (x[1]["kocka"], x[0]))
        for i, (nev, h) in enumerate(hs):
            horgony_kocka[(t["id"], f"@{nev}")] = (hs[i + 1][1]["kocka"] if i + 1 < len(hs) else t["veg_kocka"]) - 1
    kiv_kocka = [horgony_kocka.get((x["lepes"], x.get("allapot")), vege[x["lepes"]]) for x in kiv]
    kell = sorted({x["kocka"] for x in lista} | set(kiv_kocka))
    fb = tuple(mu.naplo["felbontas"])
    kepek = kivesz(mu.mp4, kell, fb)
    kd = _ures(m / "kockak")
    for x in lista:
        kepek[x["kocka"]].save(kd / f"{x['nev']}.png", compress_level=1)
    n_lap = lapok_ir(lista, kepek, m / "lapok")
    sor = f"lapok   {n_lap} lap, {len(lista)} kocka ({fb[1]}p)"
    if valtozott:
        vl = [x for x in lista if x["lepes"] in csak]
        if vl:
            n_v = lapok_ir(vl, kepek, m / "lapok-valtozott")
        else:
            _ures(m / "lapok-valtozott")
            n_v = 0
        sor += f" · változott {len(csak)} lépés, {n_v} lap (lapok-valtozott/)"
    kv = _ures(m / "kivagat")
    for x, kocka in zip(kiv, kiv_kocka):
        kivagat(kepek[kocka], x["doboz"], kv / f"{_fajlnev(x['lepes'])}-{_fajlnev(x['obj'])}.png")
    return sor + f" · kivágat {len(kiv)}" + (f" (+{len(kimarad)} kivágat nélkül)" if kimarad else "")
