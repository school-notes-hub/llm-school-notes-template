"""A Manim-videó gépi kapuja (K1–K13), a terv-menet.md 3. pontja szerint, a 2. próba súlyosságával.

Bemenet a munkamappa: narracio.json, hangido.json, idoterv.json, szavak.json, render_naplo.json,
hang.wav, a Manim szekcióindexe és mp4-je, és ha van: kezi.json, kapu-kivetel.json.
Kimenet: kapu.json, tabla.txt, szoveg.md; --atadas mellett kockak/, lapok/, kivagat/,
lepeskulcs.json (és --valtozott mellett lapok-valtozott/). Kilépési kód: 0 zöld, 1 piros.

    python kapu.py <mappa> [--atadas [--valtozott]]

Interfész a láncnak: kapu-interfesz.md. Csak a standard könyvtár és (a lapokhoz) a Pillow kell.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from collections import Counter
from pathlib import Path

GYOKER = Path(__file__).resolve().parent
sys.path.insert(0, str(GYOKER))
from szamnev import ertek as szam_ertek, sima, szoros  # noqa: E402
from lanc.szavak import whisper_ertek  # noqa: E402
from lanc.szavak import elteres as szavak_elteres, hallott_szavak, valtozott_szavak  # noqa: E402

SEMA = "videotar-kapu/1"
VIDEOTAR = GYOKER / "videotar"
W, H = 1920, 1080

# küszöbök (terv-menet.md 3. pont; a 2. próba után hangolandók)
HORGONY_ELONY_S = 0.2       # K1: a horgonyos kép a szó előtt 0–0,2 s-mal
K2_ELOBB_S, K2_KESIK_S, AZONOS_S = 0.30, 1.0, 0.2
K2B_HATRA_S = 1.0
KILOG_PX, SAV_X, SAV_Y = 2, 96, 54
ATFED_PX = 4
ERINT_PX = 2          # K4: a vonal (a vonás közepe) ennyire a szöveg dobozán kívül még a betűhöz ér
KERET_RES_PX = 3      # K4: két fókuszkeret között legalább ennyi rés (különben összeér vagy egymásba lóg)
PARHUZ_PX, PARHUZ_HOSSZ = 6, 40   # K4: a keret éle ennyi px-en belül, legalább ennyi hosszan fut egy másik vonalon
IGAZIT_PX, ELMOZDUL_PX, KOZEL_PX = 2, 10, 150   # K7: a mozgó elem végső helyére igazított új vonal
KAPCSOL_PX = 3        # K1: az eltűnő vonal vége ennyire van a mozgó elem vonalától (hozzá kapcsolódik)
BETU_HIBA, BETU_FIGY = 24, 27
K8_EGYMAS, K8_HOSSZU = 5, 6
K9_ABLAK_S, ROVIDITES_MIN = 0.3, 0.7
K10_WER = 0.20
K11_FIGY_S, K11_LEPES, K11_HIBA_S = 390, 80, 480
K13_PIX, K13_URES, K13_MAJDNEM, K13_S = 0.10, 0.9995, 0.999, 1.0   # K13: ffmpeg blackdetect (pix_th, pic_th, d)
K13_MAGAS = 480       # K13 mindig 480 px magasan mér: a 480p-s és az 1080p-s render ugyanazt az ítéletet kapja
ALLO_S = 1.0          # K12 (a mintavideón beállítva: ott a legrövidebb kulcslépés 1,07 s)
LATHATO = 0.05

KOD_SOR = ["K1", "K2", "K2b", "K3", "K4", "K5", "K6a", "K6b", "K7", "K8", "K8a", "K9", "K10", "K11", "K12", "K13"]
ALLAPOT = [("szinkron", ("K1",)), ("szám", ("K2",)), ("tag", ("K2b",)), ("egy-változás", ("K9",)),
           ("kilógás", ("K3",)), ("átfedés", ("K4",)), ("betű", ("K5",)), ("szín", ("K6a", "K6b")),
           ("helyére", ("K7",)), ("felirat", ("K8", "K8a")), ("hang", ("K10",)), ("hossz", ("K11",)),
           ("álló", ("K12",)), ("üres", ("K13",))]
MARKER = {"jelolo", "kiemeles", "keret"}


# --- segédek -----------------------------------------------------------------------

def tized(x: float, n: int = 1) -> str:
    return f"{x:.{n}f}".replace(".", ",")


def ido(s: float) -> str:
    """p:mp,t (tizedre kerekítve; a kerekítés a percbe visz át: 119,97 → „2:00,0”, nem „1:60,0”)."""
    p, t = divmod(round(s * 10), 600)
    return f"{p}:{t // 10:02d},{t % 10}"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def videotar_hash() -> str:
    """Ugyanaz, mint a videotar/utem.py videotar_hash-e (a render_naplo.json bemenet.videotar)."""
    h = hashlib.sha256()
    for p in sorted(VIDEOTAR.glob("*.py")) + [VIDEOTAR / "naplo-sema.json"]:
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def json_ir(p: Path, adat) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(adat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def szoveg_ir(p: Path, s: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(s, encoding="utf-8")
    tmp.replace(p)


def kodkulcs(k: str) -> int:
    return KOD_SOR.index(k) if k in KOD_SOR else len(KOD_SOR)


def lelet(lepes, kod, sul, obj, uzenet, **x) -> dict:
    d = {"lepes": lepes, "kod": kod, "sulyossag": sul, "obj": obj, "uzenet": uzenet}
    d.update(x)
    return d


def jeltelen(s: str) -> str:
    return s.replace("{", "").replace("}", "")


# --- a munkamappa ----------------------------------------------------------------

class Munka:
    """A munkamappa bemenetei egyszer betöltve, a szabályok közös nézete."""

    def __init__(self, mappa: Path):
        self.m = m = Path(mappa).resolve()

        def be(n, kell=True):
            p = m / n
            if not p.exists():
                if kell:
                    raise FileNotFoundError(n)
                return None
            return json.loads(p.read_text(encoding="utf-8"))

        self.narr = be("narracio.json")
        self.hang = be("hangido.json")
        self.terv = be("idoterv.json")
        self.naplo = be("render_naplo.json", False)
        self.szavak_json = be("szavak.json", False) or {}
        self.kezi = be("kezi.json", False) or {}
        self.kivetel = be("kapu-kivetel.json", False) or {}
        self.fps = float(self.terv["fps"])
        self.narr_lepes = {f"{j['id']}-{n:02d}": dict(l, jelenet=j["id"])
                           for j in self.narr for n, l in enumerate(j.get("lepesek") or [{"text": j["text"]}], 1)}
        self.tl = self.terv["lepesek"]
        self.ids = [t["id"] for t in self.tl]
        self.tmap = {t["id"]: t for t in self.tl}
        self.hmap = {s["id"]: s for s in self.hang["lepesek"]}
        self.lepesek = (self.naplo or {}).get("lepesek", [])
        self.lmap = {l["id"]: l for l in self.lepesek}
        # objektumattribútumok: a legutóbb látott állapot (a statikus jelölések egyformák)
        self.attr: dict[str, dict] = {}
        for l in self.lepesek:
            for k in sorted(l["allapot"]):
                for o in l["allapot"][k]:
                    self.attr[o["obj"]] = o
        if self.naplo:
            fb = self.naplo["felbontas"]
            self.minoseg = f"{fb[1]}p{self.naplo['fps']:g}"
            self.jelenet = self.naplo["jelenet"]
            self.modul = next((k for k in sorted(self.naplo.get("bemenet", {}))
                               if k not in ("narracio.json", "idoterv.json", "videotar")), "jelenetek.py")
            self.media = m / "media" / "videos" / Path(self.modul).stem / self.minoseg
            self.mp4 = self.media / f"{self.jelenet}.mp4"

    def szavak(self, sid: str) -> list[dict]:
        """A lépés szavai abszolút idővel: szo, ertek, szo_s, forras (az idoterv.json-ból, ha van)."""
        t = self.tmap.get(sid, {})
        if t.get("szavak") is not None:
            return t["szavak"]
        kezd = t.get("kezd_kocka", 0) / self.fps
        return [{"szo": w["szo"], "ertek": w.get("ertek"), "szo_s": kezd + w["kezd_s"], "forras": w.get("forras", "becsult")}
                for w in self.szavak_json.get(sid, [])]

    def beszed(self, sid: str) -> tuple[float, float]:
        """A lépés beszédének kezdete és vége abszolút másodpercben."""
        t, h = self.tmap[sid], self.hmap.get(sid, {})
        k = t["kezd_kocka"] / self.fps
        return k + h.get("beszed_kezd_s", 0.0), k + h.get("beszed_veg_s", (t["veg_kocka"] - t["kezd_kocka"]) / self.fps)

    def allapotok(self, l: dict):
        """(kulcs, látható objektumok) a lépés mért állapotaira, rendezett sorrendben."""
        for k in sorted(l["allapot"]):
            yield k, [o for o in l["allapot"][k] if o.get("atl", 1.0) > LATHATO]


# --- K1 szinkron (a szinkron.py Kapu.ellenoriz-éből) -------------------------------------

def k1(mu: Munka) -> list[dict]:
    out, fps = [], mu.fps

    def h(uz, lepes=None, obj=None):
        out.append(lelet(lepes, "K1", "hiba", obj, uz))

    hl, tl = mu.hang["lepesek"], mu.tl
    vart = [(sid, l["text"]) for sid, l in mu.narr_lepes.items()]
    if [(s["id"], s["text"]) for s in hl] != vart:
        h("a hangido.json nem a mostani narracio.json lépései (id vagy szöveg eltér): futtasd újra a láncot")
    if [s["id"] for s in tl] != [s["id"] for s in hl]:
        h("az idoterv.json lépései nem a hangido.json lépései")
    rate, minta, hang_kezd = mu.hang["rate"], 0, {}
    for s, t in zip(hl, tl):
        hang_kezd[s["id"]] = minta / rate
        for k, hs in (("kezd_kocka", minta / rate), ("veg_kocka", (minta + s["minta"]) / rate)):
            if abs(t[k] / fps - hs) > 1 / fps + 1e-9:
                h(f"a terv {k}-ja {t[k]}, a hanghoz képest {tized(t[k] / fps - hs, 3)} s (> 1 kocka)", t["id"])
        minta += s["minta"]
    wav = mu.m / "hang.wav"
    if wav.exists():
        with wave.open(str(wav)) as w:
            n, wr = w.getnframes(), w.getframerate()
        if n != minta * wr // rate:
            h(f"a hang.wav {n} minta, a lépésekből {minta * wr // rate} várható")
        wav_s = n / wr
    else:
        h("nincs hang.wav")
        wav_s = minta / rate
    if not mu.naplo:
        h("nincs render_naplo.json (a render elmaradt vagy elbukott)")
        return out
    if abs(float(mu.naplo["fps"]) - fps) > 1e-9:
        h(f"a render {mu.naplo['fps']} fps, a terv {fps}")
    friss = {"narracio.json": sha(mu.m / "narracio.json"), "idoterv.json": sha(mu.m / "idoterv.json"),
             mu.modul: sha(mu.m / mu.modul), "videotar": videotar_hash()}
    for k, v in friss.items():
        if mu.naplo.get("bemenet", {}).get(k) != v:
            h(f"a render régebbi, mint a(z) {k} (elbukott vagy elmaradt render?): renderelj újra")
    idx = mu.media / "sections" / f"{mu.jelenet}.json"
    if not idx.exists():
        h(f"nincs szekcióindex: {idx.relative_to(mu.m)} (render --save_sections kapcsolóval?)")
        return out
    szek, kezd = [], 0
    for s in json.loads(idx.read_text(encoding="utf-8")):
        n = int(s["nb_frames"])
        szek.append((s["name"], kezd, n))
        kezd += n
        r = s.get("avg_frame_rate", f"{fps:g}/1").split("/")
        if abs(int(r[0]) / int(r[1]) - fps) > 0.01:
            h(f"a(z) {s['name']} szekció {s['avg_frame_rate']} fps, a terv {fps:g}")
    vart_sz = []
    for t in tl:
        vart_sz.append((t["id"], t["kezd_kocka"]))
        for nev, hg in sorted(t["horgonyok"].items(), key=lambda x: (x[1]["kocka"], x[0])):
            if hg["kocka"] > t["kezd_kocka"]:
                vart_sz.append((f"{t['id']}@{nev}", hg["kocka"]))
    nevek = [s[0] for s in szek]
    if nevek != [v[0] for v in vart_sz]:
        i = next((i for i, (x, y) in enumerate(zip(nevek, vart_sz)) if x != y[0]), min(len(nevek), len(vart_sz)))
        h(f"a szekciók nevei vagy sorrendje eltér a tervtől a(z) {i + 1}. helyen "
          f"({nevek[i] if i < len(nevek) else 'nincs'} ≠ {vart_sz[i][0] if i < len(vart_sz) else 'nincs'})")
    vk_map = {s[0]: s[1] for s in szek}
    for nev, vk in vart_sz:
        if nev in vk_map and vk_map[nev] != vk:
            h(f"a(z) {nev} szekció a videóban a {vk_map[nev]}. kockán kezd, a terv {vk}", nev.split("@")[0])
    hossz: dict[str, int] = {}
    for nev, _, n in szek:
        hossz[nev.split("@")[0]] = hossz.get(nev.split("@")[0], 0) + n
    for t in tl:
        sid = t["id"]
        if sid in hossz and hossz[sid] != t["veg_kocka"] - t["kezd_kocka"]:
            h(f"a lépés a videóban {hossz[sid]} kocka, a terv {t['veg_kocka'] - t['kezd_kocka']}", sid)
        l = mu.lmap.get(sid)
        if l is None:
            h("a lépés hiányzik a render_naplo.json-ból", sid)
        elif (l["kezd_kocka"], l["veg_kocka"]) != (t["kezd_kocka"], t["veg_kocka"]):
            h(f"a napló szerint {l['kezd_kocka']}–{l['veg_kocka']}, a terv {t['kezd_kocka']}–{t['veg_kocka']}", sid)
        for nev, hg in sorted(t["horgonyok"].items()):
            elony = hg["szo_s"] - hg["kocka"] / fps
            if not -1 / fps - 1e-9 <= elony <= HORGONY_ELONY_S + 1 / fps + 1e-9:
                obj = next((e["obj"] for e in sorted((l or {}).get("megjelenik", []), key=lambda e: (e["kocka"], e["obj"]))
                            if e.get("kotes") == "horgony" and e.get("kotes_szo") == nev), None)
                irany = "előtt" if elony > 0 else "után"
                h(f"a {{{nev}}} horgony képe {tized(abs(elony), 2)} s-mal a szó {irany} (szó {ido(hg['szo_s'])}, "
                  f"kép {ido(hg['kocka'] / fps)}; cél 0–0,2 s előtte)", sid, obj)
    osszes = sum(s[2] for s in szek)
    if osszes != mu.terv["kocka_osszes"]:
        h(f"a videó {osszes} kocka, a terv {mu.terv['kocka_osszes']}")
    if abs(osszes / fps - wav_s) > 1 / fps + 1e-9:
        h(f"a videó {tized(osszes / fps, 3)} s, a hang.wav {tized(wav_s, 3)} s (> 1 kocka)")
    if mu.mp4.exists():
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                            "stream=nb_read_packets", "-of", "json", str(mu.mp4)], capture_output=True, text=True)
        n = int(json.loads(r.stdout or "{}").get("streams", [{}])[0].get("nb_read_packets", -1))
        if n != osszes:
            h(f"a(z) {mu.mp4.name} {n} kocka, a szekciók összege {osszes}")
    return out


# --- K2, K2b: szám és megnevezett tag a kimondáskor -----------------------------------

def _egyezik(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9


def uj_szamok(e: dict) -> list:
    """A megjelenés új számai: tartalomváltozásnál (`atir`-ral bővített képlet) a korábbi számok
    multihalmaz-különbsége, hogy a már kimondott szám ne számítson újnak."""
    uj = Counter(e.get("szamok") or [])
    uj.subtract(Counter(e.get("elozo_szamok") or []))
    return sorted(v for v, n in uj.items() for _ in range(max(n, 0)))


def k2(mu: Munka) -> list[dict]:
    out, fps = [], mu.fps
    azonos = round(AZONOS_S * fps)
    for i, l in enumerate(mu.lepesek):
        sid = l["id"]
        sz = mu.szavak(sid)
        kov = mu.szavak(mu.lepesek[i + 1]["id"]) if i + 1 < len(mu.lepesek) else []
        elozo = [w for j in range(i) for w in mu.szavak(mu.lepesek[j]["id"])]
        jel: dict[tuple, list] = {}
        for e in l["megjelenik"]:
            uj = uj_szamok(e)
            if not uj or mu.attr.get(e["obj"], {}).get("szamellenorzes"):
                continue
            f = e["veg_kocka"] if e["kat"] == "szamlalo" else e["kocka"]
            for v in sorted(set(uj)):
                jel.setdefault((v, v in (e.get("szor") or [])), []).append((f, e))
        for (v, szor), lst in sorted(jel.items()):
            def illik(w, v=v, szor=szor):
                return _egyezik(w.get("ertek"), v) and (not szor or szoros(w["szo"]))
            csop = []
            for f, e in sorted(lst, key=lambda x: (x[0], x[1]["obj"])):
                if not csop or f - csop[-1][0] > azonos:
                    csop.append((f, e))
            jo = [w for w in sz if illik(w)]
            vs = f"{v:g}" + ("×" if szor else "")
            for k, (f, e) in enumerate(csop):
                obj, auto = e["obj"], True
                if e.get("kotes") in ("szora", "horgony") and e.get("kotes_szo"):   # kifejezett kötés
                    cand = [w for w in jo if sima(w["szo"]) == sima(e["kotes_szo"])] or jo
                    w = min(cand, key=lambda w: (abs(w["szo_s"] - f / fps), w["szo_s"])) if cand else None
                    auto = False
                else:
                    w = jo[k] if k < len(jo) else (jo[-1] if jo else None)
                if w is None:
                    if any(illik(x) for x in kov):
                        out.append(lelet(sid, "K2", "hiba", obj, f"„{vs}” csak a következő lépésben hangzik el "
                                         "(előrefutás lépéshatáron át): a következő lépésbe vagy Szora-val"))
                    elif any(illik(x) for x in elozo):
                        out.append(lelet(sid, "K2", "figy", obj, f"„{vs}” ebben a lépésben nem hangzik el, csak korábban "
                                         "(visszautalás)"))
                    else:
                        why = " (az n× csak -szor/-szer szóhoz párosodhat)" if szor else ""
                        out.append(lelet(sid, "K2", "figy", obj, f"„{vs}” sehol nem hangzik el{why}"))
                    continue
                d = f / fps - w["szo_s"]
                enyhe = w.get("forras") in ("becsult", "gyanus")
                egy = auto and _egyezik(v, 1) and sima(w["szo"]) == "egy"    # csak a névelő alak; „egyszer” nem
                hol = f"(szó „{w['szo']}” {ido(w['szo_s'])}, kép {ido(f / fps)})"
                if d < -K2_ELOBB_S:
                    sul = "figy" if (enyhe or egy) else "hiba"
                    ok = f"; {w.get('forras')} szóidő" if enyhe else ""
                    out.append(lelet(sid, "K2", sul, obj, f"„{vs}” {tized(-d)} s-mal a kimondása előtt látszik {hol}{ok}"
                                     " → Szora vagy későbbi elem"))
                elif egy:
                    out.append(lelet(sid, "K2", "figy", obj, f"az 1-es automatikusan az „{w['szo']}” szóhoz párosul, ami "
                                     "névelő is lehet → Szora(\"egy\", hanyadik=k)"))
                elif d > K2_KESIK_S:
                    out.append(lelet(sid, "K2", "figy", obj, f"„{vs}” {tized(d)} s-mal a kimondása után jelenik meg (késik) {hol}"))
        # K2b: megnevezett tag a szava előtt; kötetlen saját képlet
        _, beszed_veg = mu.beszed(sid) if sid in mu.tmap else (0, 0)
        for e in sorted(l["megjelenik"], key=lambda e: (e["kocka"], e["obj"])):
            a = mu.attr.get(e["obj"], {})
            szo = e.get("szo") or a.get("szo")
            f = e["kocka"]
            if szo:
                s0 = sima(str(szo))           # a kód számot is adhat szónak (szo=6)
                cand = [w for w in sz if sima(w["szo"]) == s0 or (len(s0) >= 4 and sima(w["szo"]).startswith(s0[:4]))]
                if cand:
                    w = min(cand, key=lambda w: (abs(w["szo_s"] - f / fps), w["szo_s"]))
                    if f / fps < w["szo_s"] - K2_ELOBB_S:
                        sul = "figy" if w.get("forras") in ("becsult", "gyanus") else "hiba"
                        out.append(lelet(sid, "K2b", sul, e["obj"], f"a tag {tized(w['szo_s'] - f / fps)} s-mal a „{w['szo']}” "
                                         f"előtt látszik (szó {ido(w['szo_s'])}, kép {ido(f / fps)}) → Szora"))
            elif e["kat"] == "keplet" and not e.get("kotes") and a.get("forras") == "sajat" and e["ok"] == "uj":
                hatra = beszed_veg - f / fps
                if hatra > K2B_HATRA_S:
                    out.append(lelet(sid, "K2b", "figy", e["obj"], f"kötetlen képlet: megjelenése után még {tized(hatra)} s "
                                     "beszéd van hátra → Keplet tagonként szóra, vagy jelol(szo=)"))
    return out


# --- K3, K4, K5: kilógás, átfedés, betűméret -------------------------------------------

def _metszet(a, b) -> tuple[int, int]:
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _szakasz_doboz(p, q, d) -> bool:
    """A p–q szakasz metszi-e a d dobozt (Liang–Barsky)."""
    x0, y0, dx, dy = p[0], p[1], q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - d[0]), (dx, d[2] - x0), (-dy, y0 - d[1]), (dy, d[3] - y0)):
        if pp == 0:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def _vonal_metsz(v: dict, d) -> bool:
    if v["t"] == "kor":
        cx, cy, r = v["k"][0], v["k"][1], v["r"]
        nx, ny = min(max(cx, d[0]), d[2]), min(max(cy, d[1]), d[3])
        kozel = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
        tavol = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x in (d[0], d[2]) for y in (d[1], d[3]))
        return kozel < r < tavol
    p = v.get("p") or []
    vonalak = [p] if p and isinstance(p[0][0], (int, float)) else p
    return any(_szakasz_doboz(a, b, d) for vl in vonalak for a, b in zip(vl, vl[1:]))


def _szoveg(o) -> bool:
    return "font" in o


def _vonalak(v: dict | None) -> list[list]:
    """A napló vonalgeometriája töröttvonalak listájaként (a kör nélkül)."""
    if not v or v.get("t") == "kor":
        return []
    p = v.get("p") or []
    return [p] if p and isinstance(p[0][0], (int, float)) else p


def _pont_szakasz(q, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / n))
    return ((q[0] - a[0] - t * dx) ** 2 + (q[1] - a[1] - t * dy) ** 2) ** 0.5


def _pont_vonal(q, v: dict) -> float:
    """A q pont távolsága a vonalgeometriától (töröttvonal vagy kör)."""
    if v.get("t") == "kor":
        return abs(((q[0] - v["k"][0]) ** 2 + (q[1] - v["k"][1]) ** 2) ** 0.5 - v["r"])
    return min((_pont_szakasz(q, a, b) for vl in _vonalak(v) for a, b in zip(vl, vl[1:])), default=float("inf"))


def _pont_doboz(q, d) -> float:
    dx, dy = max(d[0] - q[0], 0, q[0] - d[2]), max(d[1] - q[1], 0, q[1] - d[3])
    return (dx * dx + dy * dy) ** 0.5


def _bovit(d, px) -> list:
    return [d[0] - px, d[1] - px, d[2] + px, d[3] + px]


def _celok(o: dict, objs: list[dict]) -> set[str] | None:
    """A jelölés céljai (vonatkozik) és azok csoportja; None, ha nincs `vonatkozik`."""
    ref = set(o.get("vonatkozik") or [])
    if not ref:
        return None
    return ref | {x["csoport"] for x in objs if x["obj"] in ref or x["csoport"] in ref}


def _ra_mentes(v: dict, a: dict, objs: list[dict]) -> bool:
    """A vonal `ra` kapcsolója a szöveget felmenti-e: a `vonatkozik`-kal deklarált jelölés (keret, kiemelés,
    nyíl) `ra`-ja csak a saját céljaira szól (amit körülvesz), más feliratot a vonala nem metszhet."""
    if not v.get("ra"):
        return False
    celok = _celok(v, objs)
    return celok is None or a["obj"] in celok or a["csoport"] in celok


def _keret(o: dict) -> bool:
    """Fókuszkeret: `keret` töröttvonalas körvonallal, `vonatkozik`-kal (a halmazkör nem: az a tartalom része)."""
    return o["kat"] == "keret" and bool(o.get("vonatkozik")) and bool(o.get("vonal")) and o["vonal"].get("t") != "kor"


def _keretek_rese(a, b) -> int | None:
    """Két keret dobozának rése px-ben (negatív: egymásba lóg); None, ha az egyik a másikat tartalmazza."""
    da, db = a["doboz"], b["doboz"]
    if all(da[i] <= db[i] for i in (0, 1)) and all(da[i] >= db[i] for i in (2, 3)) or \
            all(db[i] <= da[i] for i in (0, 1)) and all(db[i] >= da[i] for i in (2, 3)):
        return None
    return max(db[0] - da[2], da[0] - db[2], db[1] - da[3], da[1] - db[3])


def _parhuzamos_hossz(k: dict, o: dict, lepes_px: int = 2) -> int:
    """A k keret körvonalának leghosszabb összefüggő szakasza (px), amely az o vonalától legfeljebb
    PARHUZ_PX-re fut (a keret egybeolvad vele). Keresztezés így legfeljebb ~2·PARHUZ_PX hosszú."""
    zona = _bovit(o["doboz"], PARHUZ_PX)
    leg = 0
    for vl in _vonalak(k["vonal"]):
        fut = 0
        for a, b in zip(vl, vl[1:]):
            hossz = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            n = max(1, int(hossz // lepes_px))
            for i in range(n):
                q = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                if zona[0] <= q[0] <= zona[2] and zona[1] <= q[1] <= zona[3] and _pont_vonal(q, o["vonal"]) <= PARHUZ_PX:
                    fut += hossz / n
                    leg = max(leg, fut)
                else:
                    fut = 0
    return round(leg)


def k345(mu: Munka) -> list[dict]:
    out = []
    for l in mu.lepesek:
        sid = l["id"]
        for kulcs, objs in mu.allapotok(l):
            hol = "" if kulcs == "vege" else f" ({kulcs})"
            for o in objs:
                d = o["doboz"]
                if not o.get("kivul"):
                    kl = max(-d[0], -d[1], d[2] - W, d[3] - H)
                    if kl > KILOG_PX:
                        out.append(lelet(sid, "K3", "hiba", o["obj"], f"kilóg a képből {kl} px-lel (doboz {d}){hol}",
                                         doboz=d, allapot=kulcs))
                    elif d[0] < SAV_X or d[2] > W - SAV_X or d[1] < SAV_Y or d[3] > H - SAV_Y:
                        out.append(lelet(sid, "K3", "figy", o["obj"], f"az 5%-os szélső sávba ér (doboz {d}){hol}",
                                         doboz=d, allapot=kulcs))
                if _szoveg(o):
                    fs = o["font"]
                    if fs < BETU_HIBA:
                        out.append(lelet(sid, "K5", "hiba", o["obj"], f"hatásos betűméret {tized(fs)} < {BETU_HIBA}{hol}"))
                    elif fs < BETU_FIGY:
                        out.append(lelet(sid, "K5", "figy", o["obj"], f"hatásos betűméret {tized(fs)} (24–27){hol}"))
            szovegek = sorted((o for o in objs if _szoveg(o)), key=lambda o: o["obj"])
            for i, a in enumerate(szovegek):
                # a `ra` csak a vonal–szöveg vizsgálat alól ment fel (a szám a körvonal mellett, a régióban
                # állhat); szöveg–szöveg és szöveg–jelölő átfedés `ra` mellett is lelet
                for b in szovegek[i + 1:] + sorted((o for o in objs if o["kat"] == "jelolo" and not _szoveg(o)),
                                                   key=lambda o: o["obj"]):
                    mx, my = _metszet(a["doboz"], b["doboz"])
                    if mx > ATFED_PX and my > ATFED_PX:
                        u = [min(a["doboz"][0], b["doboz"][0]), min(a["doboz"][1], b["doboz"][1]),
                             max(a["doboz"][2], b["doboz"][2]), max(a["doboz"][3], b["doboz"][3])]
                        out.append(lelet(sid, "K4", "figy", a["obj"], f"átfed: {b['obj']} ({mx}×{my} px){hol}",
                                         doboz=u, allapot=kulcs))
                if a.get("ra"):
                    continue
                belso = [a["doboz"][0] + ATFED_PX, a["doboz"][1] + ATFED_PX, a["doboz"][2] - ATFED_PX, a["doboz"][3] - ATFED_PX]
                kozel = _bovit(a["doboz"], ERINT_PX)
                van_belso = belso[0] < belso[2] and belso[1] < belso[3]
                for v in sorted((o for o in objs if o.get("vonal") and o["obj"] != a["obj"] and not _ra_mentes(o, a, objs)),
                                key=lambda o: o["obj"]):
                    if van_belso and _vonal_metsz(v["vonal"], belso):
                        out.append(lelet(sid, "K4", "figy", a["obj"], f"a(z) {v['obj']} vonala metszi a szöveget{hol}",
                                         doboz=a["doboz"], allapot=kulcs))
                    elif _vonal_metsz(v["vonal"], kozel):
                        out.append(lelet(sid, "K4", "figy", a["obj"], f"a(z) {v['obj']} vonala a szöveg szélén fut "
                                         f"(≤ {ERINT_PX} px-re a betűktől) → tedd távolabb{hol}",
                                         doboz=_bovit(a["doboz"], 20), allapot=kulcs))
            out += k4_keretek(sid, kulcs, hol, objs)
    return out


def k4_keretek(sid: str, kulcs: str, hol: str, objs: list[dict]) -> list[dict]:
    """K4 a fókuszkeretekre (`keret` `vonatkozik`-kal): két keret nem érhet össze és nem lóghat egymásba, és a
    keret éle nem futhat egy másik (nem jelölt) elem vonalán, mert akkor a kettő egybeolvad."""
    out = []
    keretek = sorted((o for o in objs if _keret(o)), key=lambda o: o["obj"])
    for i, a in enumerate(keretek):
        for b in keretek[i + 1:]:
            res = _keretek_rese(a, b)
            if res is not None and res < KERET_RES_PX:
                u = [min(a["doboz"][0], b["doboz"][0]), min(a["doboz"][1], b["doboz"][1]),
                     max(a["doboz"][2], b["doboz"][2]), max(a["doboz"][3], b["doboz"][3])]
                mi = "egymásba lóg" if res < 0 else "összeér"
                out.append(lelet(sid, "K4", "figy", a["obj"], f"a(z) {b['obj']} keretével {mi} (rés {res} px, "
                                 f"kell ≥ {KERET_RES_PX}){hol}", doboz=u, allapot=kulcs))
        if not a.get("vonal"):
            continue
        celok = _celok(a, objs)
        for o in sorted(objs, key=lambda o: o["obj"]):
            if o is a or not o.get("vonal") or _szoveg(o) or _keret(o) or o["kat"] == "kiemeles" or \
                    o["obj"] in celok or o["csoport"] in celok or set(o.get("vonatkozik") or []) & celok:
                continue                # a kiemelés és az ugyanarra vonatkozó jel a keret mentén fut (szándékos)
            d, z = a["doboz"], _bovit(o["doboz"], PARHUZ_PX)
            if z[0] > d[2] or z[2] < d[0] or z[1] > d[3] or z[3] < d[1]:
                continue
            hossz = _parhuzamos_hossz(a, o)
            if hossz >= PARHUZ_HOSSZ:
                out.append(lelet(sid, "K4", "figy", a["obj"], f"a keret éle {hossz} px hosszan a(z) {o['obj']} vonalán "
                                 f"fut (≤ {PARHUZ_PX} px), a kettő egybeolvad → a keret kerülje meg{hol}",
                                 doboz=d, allapot=kulcs))
    return out


# --- K6b, K7 ----------------------------------------------------------------------

def k6b(mu: Munka) -> list[dict]:
    out = []
    for l in mu.lepesek:
        objs = [o for o in l["allapot"]["vege"] if o.get("atl", 1.0) > LATHATO]
        csop: dict[str, list] = {}
        for o in objs:
            if o["kat"] in MARKER and o.get("alairas") and not o.get("cimke"):
                csop.setdefault(o["csoport"], []).append(o)
        sig = {}
        for c, os_ in sorted(csop.items()):
            al = tuple(sorted(json.dumps(o["alairas"], sort_keys=True) for o in os_))
            szin = tuple(sorted(o.get("szin", "") for o in os_))
            sig[c] = (al, szin)
        nevek = sorted(sig)
        for i, a in enumerate(nevek):
            for b in nevek[i + 1:]:
                if sig[a][0] == sig[b][0] and sig[a][1] != sig[b][1]:
                    d = [min(o["doboz"][j] for o in csop[a] + csop[b]) if j < 2 else
                         max(o["doboz"][j] for o in csop[a] + csop[b]) for j in range(4)]
                    out.append(lelet(l["id"], "K6b", "figy", a, f"{a} és {b} csak színben különbözik (alak, méret, minta, "
                                     "felirat azonos) → más alak, minta vagy felirat", doboz=d, allapot="vege"))
    return out


def k7(mu: Munka) -> list[dict]:
    out = []
    for l in mu.lepesek:
        mozog = sorted(l["mozog"], key=lambda s: (s["tol"], s["obj"]))
        vege = {o["obj"]: o for o in l["allapot"]["vege"]}
        for e in sorted(l["megjelenik"], key=lambda e: (e["kocka"], e["obj"])):
            a = mu.attr.get(e["obj"], {})
            ref = set(a.get("vonatkozik") or [])
            k0, k1_ = e["kocka"], e["veg_kocka"]
            if ref:
                for s in mozog:
                    so = mu.attr.get(s["obj"], {})
                    if (s["obj"] in ref or so.get("csoport") in ref) and s["tol"] < k1_ and s["ig"] > k0:
                        out.append(lelet(l["id"], "K7", "figy", e["obj"], f"megjelenése alatt ({ido(k0 / mu.fps)}–"
                                         f"{ido(k1_ / mu.fps)}) a vonatkozott {s['obj']} még mozog → előbb a helyére, "
                                         "aztán köré (két elem)", doboz=a.get("doboz"), allapot="vege"))
                        break
            elif e["kat"] in ("keret", "kiemeles") and e["obj"] in vege:
                d = vege[e["obj"]]["doboz"]
                for s in mozog:
                    so = vege.get(s["obj"])
                    if so and s["obj"] != e["obj"] and s["tol"] < k1_ and s["ig"] > k0 and \
                            so["doboz"][0] >= d[0] and so["doboz"][1] >= d[1] and so["doboz"][2] <= d[2] and so["doboz"][3] <= d[3]:
                        out.append(lelet(l["id"], "K7", "figy", e["obj"], f"deklarált viszony nélkül a dobozában mozgó "
                                         f"{s['obj']} alatt jelenik meg → jelol(vonatkozik=…), előbb a helyére",
                                         doboz=d, allapot="vege"))
                        break
    return out + k7_vegso_hely(mu) + k7_ures_keret(mu)


def _elozo_vege(mu: Munka) -> dict[str, dict[str, dict]]:
    """Lépésenként az előző lépés végállapota (obj → objektum): ez a lépés kezdőképe."""
    ki, elozo = {}, {}
    for l in mu.lepesek:
        ki[l["id"]] = elozo
        elozo = {o["obj"]: o for o in l["allapot"]["vege"] if o.get("atl", 1.0) > LATHATO}
    return ki


def k1_kapcsolt(mu: Munka) -> list[dict]:
    """K1 (szinkron), figy.: egy vonal (kar, merőleges, szögjel) eltűnik, mialatt az elem, amelyhez a vége kapcsolódik
    (a lépés elején a vonalán áll, vagy `vonatkozik`), még mozog: a kép a mozgás vége előtt mutatja a változás
    eredményét. A kapcsolódó jel kövesse a mozgást, és akkor tűnjön el, amikor a narráció kimondja.
    Nem lelet: a keret és a kiemelés (jelölés, nem a dolog része), a jel, amely a lépésben maga is követi a mozgást
    (mozog vagy átalakul), és az áttűnéses csere (ugyanolyan fajtájú új elem jelenik meg ugyanakkor a régi helyén
    vagy a mozgó elemhez kötve)."""
    out, elozo = [], _elozo_vege(mu)
    for l in mu.lepesek:
        kezd = elozo[l["id"]]
        vege = {o["obj"]: o for o in l["allapot"]["vege"] if o.get("atl", 1.0) > LATHATO}
        koveti = {s["obj"] for f in ("mozog", "atalakul") for s in l[f]}
        for x in sorted(l["eltunik"], key=lambda e: (e["kocka"], e["obj"])):
            o = kezd.get(x["obj"])
            if not o or _szoveg(o) or o["kat"] in ("keret", "kiemeles") or x["obj"] in koveti or \
                    not _vonalak(o.get("vonal")):
                continue
            vegek = [q for vl in _vonalak(o["vonal"]) for q in (vl[0], vl[-1])]
            for s in sorted(l["mozog"], key=lambda s: (s["tol"], s["obj"])):
                y = kezd.get(s["obj"])
                if not y or s["obj"] == x["obj"] or y["csoport"] == o["csoport"] or not y.get("vonal") or \
                        not (x["kocka"] < s["ig"] and x["veg_kocka"] > s["tol"]):
                    continue
                y1 = vege.get(s["obj"], y)

                def csere(e):
                    """Áttűnéses csere: ugyanolyan fajtájú új elem ugyanakkor, a régi helyén vagy a mozgó elemhez
                    kötve (a végén a vonalán áll); máshol a képen megjelenő elem nem felment."""
                    eo = vege.get(e["obj"])
                    if not eo or eo["kat"] != o["kat"] or not (e["kocka"] < x["veg_kocka"] and e["veg_kocka"] > x["kocka"]):
                        return False
                    mx, my = _metszet(_bovit(o["doboz"], KAPCSOL_PX), eo["doboz"])
                    return (mx > 0 and my > 0) or bool(y1.get("vonal")) and any(
                        _pont_vonal(q, y1["vonal"]) <= KAPCSOL_PX for vl in _vonalak(eo.get("vonal")) for q in (vl[0], vl[-1]))
                if any(csere(e) for e in l["megjelenik"]):
                    continue
                ref = set(o.get("vonatkozik") or [])
                if s["obj"] in ref or y["csoport"] in ref or any(_pont_vonal(q, y["vonal"]) <= KAPCSOL_PX for q in vegek):
                    out.append(lelet(l["id"], "K1", "figy", x["obj"], f"eltűnik ({ido(x['kocka'] / mu.fps)}–"
                                     f"{ido(x['veg_kocka'] / mu.fps)}), mialatt a(z) {s['obj']}, amelyhez kapcsolódik, még "
                                     f"mozog (–{ido(s['ig'] / mu.fps)}): a változás előrefut → a jel kövesse a mozgást, és a "
                                     "kimondásra tűnjön el", doboz=o["doboz"], allapot="vege"))
                    break
    return out


def _kozep(d) -> tuple[float, float]:
    return (d[0] + d[2]) / 2, (d[1] + d[3]) / 2


def k7_vegso_hely(mu: Munka) -> list[dict]:
    """K7: új vonal (méretvonal, kar, segédvonal) jelenik meg egy másik elem mozgása alatt, és a vége a mozgó elem
    végső helyéhez igazodik (ugyanabban az oszlopban vagy sorban áll, vagy hozzáér), a kiinduló helyéhez nem: a
    jel a helyet azelőtt mutatja, hogy az elem odaért. Deklarált viszony nélkül is (a `vonatkozik`-osat a k7 nézi)."""
    out, elozo = [], _elozo_vege(mu)
    for l in mu.lepesek:
        vege = {o["obj"]: o for o in l["allapot"]["vege"] if o.get("atl", 1.0) > LATHATO}
        for e in sorted(l["megjelenik"], key=lambda e: (e["kocka"], e["obj"])):
            o = vege.get(e["obj"])
            if not o or _szoveg(o) or o["kat"] in MARKER or not _vonalak(o.get("vonal")):
                continue
            vegek = [q for vl in _vonalak(o["vonal"]) for q in (vl[0], vl[-1])]
            for s in sorted(l["mozog"], key=lambda s: (s["tol"], s["obj"])):
                a0, a1 = elozo[l["id"]].get(s["obj"]), vege.get(s["obj"])
                if s["obj"] == e["obj"] or not a0 or not a1 or a1["csoport"] == o["csoport"] or \
                        s["obj"] in (o.get("vonatkozik") or []) or not (s["tol"] < e["veg_kocka"] and s["ig"] > e["kocka"]):
                    continue
                c0, c1 = _kozep(a0["doboz"]), _kozep(a1["doboz"])
                if max(abs(c0[0] - c1[0]), abs(c0[1] - c1[1])) < ELMOZDUL_PX:
                    continue

                def igazodik(q, c, d):
                    return (abs(q[0] - c[0]) <= IGAZIT_PX and abs(q[1] - c[1]) <= KOZEL_PX) or \
                        (abs(q[1] - c[1]) <= IGAZIT_PX and abs(q[0] - c[0]) <= KOZEL_PX) or _pont_doboz(q, d) <= KAPCSOL_PX
                vegsok = [q for q in vegek if igazodik(q, c1, a1["doboz"])]
                if vegsok and not any(igazodik(q, c0, a0["doboz"]) for q in vegek):
                    out.append(lelet(l["id"], "K7", "figy", e["obj"], f"megjelenése alatt ({ido(e['kocka'] / mu.fps)}–"
                                     f"{ido(e['veg_kocka'] / mu.fps)}) a(z) {s['obj']} még mozog, a vonal vége pedig már a "
                                     "végső helyéhez igazodik → előbb a helyére, aztán a hozzá mért vonal (két elem)",
                                     doboz=o["doboz"], allapot="vege"))
                    break
    return out


def k7_ures_keret(mu: Munka) -> list[dict]:
    """K7: a keret vagy kiemelés a képen marad, de amit jelöl (`vonatkozik`), az már egészen eltűnt, és a helyére sem
    lépett más (névváltó csere, például ReplacementTransform: az új elem ugyanabban a lépésben jelenik meg a
    dobozában, vagy a doboz több mint felét kitölti úgy, hogy maga is többnyire a dobozban áll; utána ez számít a
    keret céljának). Csak
    ismert nevű célra (ami a videóban szerepelt). Összefüggő lépéssoronként egy lelet, az első lépésen."""
    out, ismert = [], set(mu.attr) | {o["csoport"] for o in mu.attr.values()}
    futo: dict[str, list] = {}           # keret → [első lépés, utolsó lépés, doboz, állapot, fajta]
    orokolt: dict[str, set] = {}         # keret → a cserében a célja helyére lépett objektumok
    uj = set()                           # az aktuális lépésben megjelent objektumok

    def _csere(x, d) -> bool:
        """A cél helyére lépett elem: ugyanabban a lépésben jelent meg, és a keret dobozában áll, vagy a keret
        dobozának több mint felét kitölti, és maga is több mint felével benne áll (a keret mögötti nagy háttérelem
        és a régóta ott álló kis elem nem)."""
        mx, my = _metszet(d, x["doboz"])
        k = x["doboz"]
        kozos = mx * my if mx > 0 and my > 0 else 0
        bent = d[0] <= _kozep(k)[0] <= d[2] and d[1] <= _kozep(k)[1] <= d[3]
        return (x["obj"] in uj and bent) or (kozos > (d[2] - d[0]) * (d[3] - d[1]) / 2
                                              and kozos > (k[2] - k[0]) * (k[3] - k[1]) / 2)

    def zar(nev):
        e, u, d, kulcs, fajta = futo.pop(nev)
        hol = "" if kulcs == "vege" else f" ({kulcs})"
        tart = "" if e == u else f", üresen marad {u}-ig"
        out.append(lelet(e, "K7", "figy", nev, f"a jelölt elem már nincs a képen, a dobozában sincs semmi, a {fajta} "
                         f"mégis marad{hol}{tart} → vele együtt tűnjön el", doboz=d, allapot=kulcs))
    for l in mu.lepesek:
        uj = {e["obj"] for e in l["megjelenik"]}
        ures: dict[str, tuple] = {}
        for kulcs, objs in mu.allapotok(l):
            lat = {o["obj"] for o in objs} | {o["csoport"] for o in objs}
            for o in sorted(objs, key=lambda o: o["obj"]):
                ref = set(o.get("vonatkozik") or [])
                if o["kat"] not in ("keret", "kiemeles") or not ref or not ref <= ismert or ref & lat or o["obj"] in ures:
                    continue
                d = o["doboz"]
                if orokolt.get(o["obj"], set()) & lat:
                    continue
                csere = [x["obj"] for x in objs if x is not o and x["kat"] not in ("keret", "kiemeles") and _csere(x, d)]
                if csere:
                    orokolt.setdefault(o["obj"], set()).update(csere)
                    continue
                ures[o["obj"]] = (d, kulcs, "keret" if o["kat"] == "keret" else "kiemelés")
        for nev in sorted(set(futo) - set(ures)):
            zar(nev)
        for nev, (d, kulcs, fajta) in sorted(ures.items()):
            if nev in futo:
                futo[nev][1] = l["id"]
            else:
                futo[nev] = [l["id"], l["id"], d, kulcs, fajta]
    for nev in sorted(futo):
        zar(nev)
    return sorted(out, key=lambda x: (x["lepes"], x["obj"]))


# --- K8, K9, K10, K11, K12 ---------------------------------------------------------
# A nyitó- és a záróképet (cím, tantárgy, zene; lanc/nyitozaro.py) a lánc a --vegleges összefésülésnél teszi a
# fő render elé és mögé: a K8 (képszöveg) és a K11 (hossz) csak a fő rendert és az időtervet látja, így ezt a két
# részt kihagyja. A K8a az összefésült fájlon fut: továbbra is pontosan 1 videó- és 1 hangsávot követel meg.

def _szavak(s: str) -> list[str]:
    return [w for w in (sima(x) for x in jeltelen(s).split()) if w]


def k8(mu: Munka) -> list[dict]:
    out = []
    for i, l in enumerate(mu.lepesek):
        sid = l["id"]
        szomszed = [mu.narr_lepes.get(mu.lepesek[j]["id"], {}).get("text", "") for j in (i - 1, i, i + 1)
                    if 0 <= j < len(mu.lepesek)]
        ngram = {tuple(ws[k:k + K8_EGYMAS]) for t in szomszed for ws in [_szavak(t)] for k in range(len(ws) - K8_EGYMAS + 1)}
        latott = set()
        for _, objs in mu.allapotok(l):
            for o in objs:
                if o["kat"] != "szoveg" or not o.get("tartalom") or o["obj"] in latott:
                    continue
                latott.add(o["obj"])
                ws = _szavak(o["tartalom"])
                if any(tuple(ws[k:k + K8_EGYMAS]) in ngram for k in range(len(ws) - K8_EGYMAS + 1)):
                    out.append(lelet(sid, "K8", "hiba", o["obj"], f"a képszövegben a narráció {K8_EGYMAS} egymást követő "
                                     f"szava áll („{o['tartalom'][:40]}”): ez felirat → rövid címke vagy kép"))
                elif len(ws) >= K8_HOSSZU:
                    out.append(lelet(sid, "K8", "figy", o["obj"], f"{len(ws)} szavas képszöveg („{o['tartalom'][:40]}”)"))
    return out


def k9(mu: Munka) -> list[dict]:
    out, fps = [], mu.fps
    for l in mu.lepesek:
        sid = l["id"]
        if sid not in mu.tmap:
            continue
        hatar = mu.beszed(sid)[0] + K9_ABLAK_S
        kotetlen: dict[str, int] = {}
        for e in l["megjelenik"]:
            a = mu.attr.get(e["obj"], {})
            # nem új tartalom: a kiemelés, és a vonatkozott objektumra rajzolt keret és nyíl; a `vonatkozik`-os
            # szöveg, képlet vagy szám tartalom, ezt is kötni kell
            if e["kat"] == "kiemeles" or (e["kat"] in ("keret", "nyil") and a.get("vonatkozik")):
                continue
            c = e.get("csoport") or e["obj"]
            if e.get("kotes"):
                continue
            kotetlen[c] = min(kotetlen.get(c, e["kocka"]), e["kocka"])
        # a kötött elemet is tartalmazó csoport nem kötetlen
        kotott = {(e.get("csoport") or e["obj"]) for e in l["megjelenik"] if e.get("kotes")}
        sor = sorted(((f, c) for c, f in kotetlen.items() if c not in kotott))
        elejen = 0
        for f, c in sor:
            if f / fps > hatar + 1e-9:
                out.append(lelet(sid, "K9", "hiba", c, f"kötetlen tartalmi csoport a lépés közben (+{tized(f / fps - mu.beszed(sid)[0])} s "
                                 "a beszédkezdettől) → Szora/Horgony, vagy külön lépés"))
            else:
                elejen += 1
                if elejen > 1:
                    out.append(lelet(sid, "K9", "hiba", c, "a lépés elején a második kötetlen tartalmi csoport → "
                                     "egy lépés, egy változás"))
    return out


def k10(mu: Munka) -> list[dict]:
    out = []
    for sid in mu.ids:
        ws = [w for w in mu.szavak_json.get(sid, []) if "whisper" in w]
        if not ws:
            continue
        if not any(w["whisper"] for w in ws):      # a Whisper szó nélkül válaszolt (minden próbára): nem a hang hibája
            out.append(lelet(sid, "K10", "figy", None, "a Whisper ebben a lépésben minden próbára szó nélkül "
                             "válaszolt; a hang gépileg nincs ellenőrizve → a tulajdonos a nyugta k10_ketseges "
                             "időpontján meghallgatja", nincs_szo=True))
            continue
        hibas = []
        for w in ws:
            v, hv = w.get("ertek"), whisper_ertek(w["whisper"])
            if v is not None and not _egyezik(v, hv):
                hibas.append(f"„{w['szo']}” helyett „{w['whisper'] or '–'}”")
        hallott = hallott_szavak(ws)      # a több narrációs szóra osztott Whisper-szöveg egyszer számít
        elter = szavak_elteres([w["szo"] for w in ws], hallott)
        # egy betű is más szó lehet („számokat” → „sámokat”): a kiejtés szerint is eltérő szó jelzés, nem zaj.
        # A lánc ilyenkor már újrakérte a Whispert és a hangot (lanc/hangok.py); ami marad, a nyugta
        # k10_ketseges-ébe kerül, a tulajdonos ezeket az időpontokat hallgatja meg. Elfogadni nem lehet.
        valt = valtozott_szavak([w["szo"] for w in ws], hallott)
        parok = [f"„{v['szo']}” helyett „{v['hallott']}”" for v in valt]
        szo = ("; más szót hallott: " + ", ".join(parok)) if parok else ""
        if hibas:
            out.append(lelet(sid, "K10", "hiba", None, "a hang mást mond: " + ", ".join(hibas) + szo +
                             " → írd át a mondatot (más szórend vagy számalak)"))
        elif valt:
            out.append(lelet(sid, "K10", "figy", None, "a Whisper új hanggal is más szót hallott: " + ", ".join(parok) +
                             " → a tulajdonos a nyugta k10_ketseges időpontjain meghallgatja; ha elkerülhető, írd át "
                             "(más szó vagy szórend)" + (f" (eltérés {round(100 * elter)}%)" if elter > K10_WER else ""),
                             szovaltozas=len(valt)))
        elif elter > K10_WER:
            out.append(lelet(sid, "K10", "figy", None, f"a hang és a szöveg eltérése {round(100 * elter)}% "
                             "(karakteres, > 20%)"))
    return out


def k11(kocka_osszes: int, fps: float, lepesszam: int) -> list[dict]:
    s = kocka_osszes / fps
    if s > K11_HIBA_S:
        return [lelet(None, "K11", "hiba", None, f"a videó {ido(s)} (> 8 perc) → bontsd két videóra")]
    if s > K11_FIGY_S or lepesszam > K11_LEPES:
        return [lelet(None, "K11", "figy", None, f"a videó {ido(s)}, {lepesszam} lépés (> 6,5 perc vagy > 80 lépés)")]
    return []


def kulcslepes(mu: Munka, l: dict) -> bool:
    t = mu.tmap.get(l["id"], {})
    return bool(t.get("horgonyok")) or mu.narr_lepes.get(l["id"], {}).get("kulcspont") is True or \
        any(e["kat"] == "eredmeny" for e in l["megjelenik"])


def allo_s(mu: Munka, l: dict) -> float:
    uv = l["utolso_valtozas"]
    return (l["veg_kocka"] - (uv if uv is not None else l["kezd_kocka"])) / mu.fps


def k12(mu: Munka) -> list[dict]:
    out = []
    for l in mu.lepesek:
        if kulcslepes(mu, l) and allo_s(mu, l) < ALLO_S:
            out.append(lelet(l["id"], "K12", "figy", None, f"új fogalom vagy eredmény, de az álló idő {tized(allo_s(mu, l))} s "
                             f"(< {tized(ALLO_S)} s) → rövidebb rajzolás vagy szunet"))
    return out


def sotet_szakaszok(mp4: Path, hossz_s: float) -> dict[str, list[tuple[float, float]]]:
    """K13 mérése egy ffmpeg-menetben, két blackdetect-ággal: {"ures": [...], "majdnem": [...]}, (kezd, vég) s.
    „ures”: a kép legalább 99,95%-a sötét (pix_th 0,10); „majdnem”: legalább 99,9%-a (egy kis felirat a fekete
    képen). A mérés 480 px magasra kicsinyítve fut (az 1080p-s renderen is), így a felbontás nem dönt: kis jel
    1080p-n arányosan kevesebb képpont, mint a 480p-s render élsimított rajzán. A blackdetect a szakasz elejét és végét kockametaadatként adja (ezt írja a két `metadata`-ág
    fájlba); a K13_S-nél rövidebb szakasz és a hossz végéig tartó, lezáratlan szakasz itt dől el."""
    with tempfile.TemporaryDirectory() as d:
        f = {n: Path(d) / f"{n}.txt" for n in ("ures", "majdnem")}
        ag = ";".join(f"[{n}]blackdetect=d={K13_S}:pix_th={K13_PIX}:pic_th={pic},metadata=mode=print:file='{f[n]}'[{n}o]"
                      for n, pic in (("ures", K13_URES), ("majdnem", K13_MAJDNEM)))
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(mp4), "-filter_complex",
                            f"[0:v]scale=-2:{K13_MAGAS}:flags=area,split[ures][majdnem];{ag}", "-map", "[ureso]", "-f", "null", "-",
                            "-map", "[majdnemo]", "-f", "null", "-"], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"ffmpeg blackdetect: {r.stderr.strip()[-300:]}")
        ki = {}
        for n, p in f.items():
            szak, kezd = [], None
            for sor in (p.read_text(encoding="utf-8") if p.exists() else "").splitlines():
                if sor.startswith("lavfi.black_start="):
                    kezd = float(sor.split("=", 1)[1])
                elif sor.startswith("lavfi.black_end=") and kezd is not None:
                    szak.append((kezd, float(sor.split("=", 1)[1])))
                    kezd = None
            if kezd is not None:
                szak.append((kezd, hossz_s))
            ki[n] = [(a, b) for a, b in szak if b - a >= K13_S - 1e-6]
    return ki


def _kivon(m: tuple[float, float], ki: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Az (a, b) szakasz darabjai a `ki` szakaszain kívül."""
    darab = [m]
    for c, d in sorted(ki):
        darab = [x for a, b in darab for x in ((a, min(b, c)), (max(a, d), b)) if x[1] - x[0] > 1e-6]
    return darab


def k13(mu: Munka, szakaszok: dict | None = None) -> list[dict]:
    """K13 üres kép (mérce 9.): a fő render sötét vagy szinte üres szakasza (≥ 1 s). Üres (≥ 99,95% sötét): hiba;
    szinte üres (≥ 99,9%, csak egy kis jel a fekete képen): figyelmeztetés, ha az üres szakaszokon kívüli
    darabja (darabonként mérve) legalább 1 s; a lelet a darab kezdő lépésén van. A nyitó- és zárókártya, és az
    áttűnésük nincs a fő renderben (a --vegleges fűzi elé és mögé), ezért ez nem méri."""
    if szakaszok is None:
        if not getattr(mu, "mp4", None) or not mu.mp4.exists():
            return []
        szakaszok = sotet_szakaszok(mu.mp4, mu.terv["kocka_osszes"] / mu.fps)
    ures = szakaszok.get("ures", [])
    tetel = [("hiba", a, b) for a, b in ures] + \
        [("figy", a, b) for m in szakaszok.get("majdnem", []) for a, b in _kivon(m, ures)
         if b - a >= K13_S - 1e-6]                                      # az üresen kívüli darab, darabonként
    lepesenkent: dict[str, list] = {}
    for sul, a, b in sorted(tetel, key=lambda x: (x[1], x[2], x[0])):
        erint = [t["id"] for t in mu.tl if t["kezd_kocka"] / mu.fps < b and t["veg_kocka"] / mu.fps > a] or [mu.ids[-1]]
        lepesenkent.setdefault(erint[0], []).append((sul, a, b, erint))
    out = []
    for sid, ts in lepesenkent.items():
        sul = "hiba" if any(t[0] == "hiba" for t in ts) else "figy"
        reszek = [f"{'üres' if s == 'hiba' else 'szinte üres'} kép {ido(a)}–{ido(b)} ({tized(b - a)} s; "
                  f"{e[0]}{'–' + e[-1] if len(e) > 1 else ''})" for s, a, b, e in ts]
        out.append(lelet(sid, "K13", sul, None, "; ".join(reszek) + " → a színpad álljon előbb, a beszéd közben "
                         "legyen a képen, amiről szól (mérce 9.)"))
    return out


def k8a(mp4: Path) -> list[dict]:
    """K8a a --vegleges összefésült mp4-jén (a lánc hívja): 1 videó- és 1 hangsáv, se fejezet, se felirat, se cím."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-of", "json",
                        str(mp4)], capture_output=True, text=True)
    p = json.loads(r.stdout or "{}")
    tip = [s.get("codec_type") for s in p.get("streams", [])]
    baj = []
    if tip.count("video") != 1 or tip.count("audio") != 1 or len(tip) != 2:
        baj.append(f"sávok: {', '.join(sorted(map(str, tip)))} (pontosan 1 videó és 1 hang kell)")
    if p.get("chapters"):
        baj.append(f"{len(p['chapters'])} fejezet")
    cimkek = {k.lower() for k in (p.get("format", {}).get("tags") or {})} | \
        {k.lower() for s in p.get("streams", []) for k in (s.get("tags") or {})}
    if cimkek & {"title", "comment", "description", "subtitle"}:
        baj.append("cím- vagy leírás-metaadat: " + ", ".join(sorted(cimkek & {"title", "comment", "description", "subtitle"})))
    return [lelet(None, "K8a", "hiba", None, "; ".join(baj))] if baj else []


# --- összesítés, kivételek --------------------------------------------------------

def rendez(leletek: list[dict]) -> list[dict]:
    egy: dict[tuple, dict] = {}
    for x in leletek:
        k = (x["lepes"] or "", x["kod"], x["obj"] or "")
        if k not in egy or (x["sulyossag"] == "hiba" and egy[k]["sulyossag"] != "hiba"):
            egy[k] = x
    return [egy[k] for k in sorted(egy, key=lambda k: (k[0], kodkulcs(k[1]), k[2]))]


def kivetelek(mu: Munka, leletek: list[dict], vezerlo: bool = False) -> list[dict]:
    """kapu-kivetel.json: elfogad (író, csak figy.), teves_hiba (író, hibára), felulbiral (csak a vezérlő, hibára).
    A fájlt az író is írja, ezért a `felulbiral` csak vezérlőmódban (--atadas, --vegleges) számít; az író
    480p-s futásában érvénytelen kivétel."""
    hibas = []
    idx = {(x["lepes"], x["kod"], x["obj"]): x for x in leletek}
    for fajta, kell, mezo in (("elfogad", "figy", "elfogadva"), ("teves_hiba", "hiba", "teves_hiba"),
                              ("felulbiral", "hiba", "felulbiralva")):
        for e in mu.kivetel.get(fajta, []):
            k = (e.get("lepes"), e.get("kod"), e.get("obj"))
            x, indok = idx.get(k), (e.get("indok") or "").strip()
            if fajta == "elfogad" and x is not None and (x.get("szovaltozas") or x.get("nincs_szo")):
                hibas.append({"fajta": fajta, **{a: e.get(a) for a in ("lepes", "kod", "obj")},
                              "ok": f"{'a szóváltozást' if x.get('szovaltozas') else 'a gépileg nem ellenőrzött hangot'} "
                                    "nem lehet elfogadni (a tulajdonos hallgatja meg: nyugta k10_ketseges)"})
            elif fajta == "felulbiral" and not vezerlo:
                hibas.append({"fajta": fajta, **{a: e.get(a) for a in ("lepes", "kod", "obj")},
                              "ok": "csak a vezérlő, --atadas"})
            elif not indok:
                hibas.append({"fajta": fajta, **{a: e.get(a) for a in ("lepes", "kod", "obj")}, "ok": "indok nélkül"})
            elif x is None:
                hibas.append({"fajta": fajta, **{a: e.get(a) for a in ("lepes", "kod", "obj")}, "ok": "nincs ilyen lelet"})
            elif x["sulyossag"] != kell:
                hibas.append({"fajta": fajta, **{a: e.get(a) for a in ("lepes", "kod", "obj")},
                              "ok": f"csak {'figyelmeztetésre' if kell == 'figy' else 'hibára'} vonatkozhat"})
            else:
                x[mezo] = indok
    return hibas


def allapotsor(leletek: list[dict]) -> str:
    r = []
    for nev, kodok in ALLAPOT:
        ls = [x for x in leletek if x["kod"] in kodok and not x.get("felulbiralva") and not x.get("elfogadva")]
        r.append(f"{nev} {'✗' if any(x['sulyossag'] == 'hiba' for x in ls) else '!' if ls else '✓'}")
    return " ".join(r)


def kapu(mappa: Path, vezerlo: bool = False) -> dict:
    """A kapu: a leletek és a döntés (kapu.json tartalma). Fájlt nem ír."""
    mu = Munka(mappa)
    return kapu_munkan(mu, vezerlo)


def kapu_munkan(mu: Munka, vezerlo: bool = False) -> dict:
    leletek = k1(mu) + k1_kapcsolt(mu)
    if mu.naplo:
        leletek += k2(mu) + k345(mu) + k6b(mu) + k7(mu) + k8(mu) + k9(mu) + k12(mu) + k13(mu)
    leletek += k10(mu) + k11(mu.terv["kocka_osszes"], mu.fps, len(mu.tl))
    leletek = rendez(leletek)
    rossz = kivetelek(mu, leletek, vezerlo)
    nyitott = [x for x in leletek if x["sulyossag"] == "hiba" and not x.get("felulbiralva")]
    jelzes = []
    for l in mu.lepesek:
        sk = min((float(e.get("rovidites", 1.0)) for e in l["elemek"] if e["tipus"] != "wait"), default=1.0)
        if sk < ROVIDITES_MIN:
            jelzes.append({"lepes": l["id"], "uzenet": f"rövidítés {tized(sk, 2)} (< 0,7): bontsd ketté, vagy növeld a szunet-et"})
    szam = {"hiba": sum(x["sulyossag"] == "hiba" for x in leletek), "figy": sum(x["sulyossag"] == "figy" for x in leletek),
            "elfogadva": sum("elfogadva" in x for x in leletek), "teves_hiba": sum("teves_hiba" in x for x in leletek),
            "felulbiralva": sum("felulbiralva" in x for x in leletek)}
    bemenet = {n: sha(mu.m / n) for n in ("narracio.json", "idoterv.json", "szavak.json", "render_naplo.json",
                                          "kezi.json", "kapu-kivetel.json") if (mu.m / n).exists()}
    return {"sema": SEMA, "jelenet": (mu.naplo or {}).get("jelenet"), "minoseg": getattr(mu, "minoseg", None),
            "lepesek": len(mu.tl), "kockak": mu.terv["kocka_osszes"], "fps": mu.fps, "bemenet": bemenet,
            "zold": not nyitott, "atadhato": all(x.get("teves_hiba") for x in nyitott),
            "szamok": szam, "allapot": allapotsor(leletek), "leletek": leletek,
            "ervenytelen_kivetelek": rossz, "jelzesek": jelzes}


def osszefoglalo(k: dict, max_figy: int = 12, max_hiba: int = 6, max_lelet: int = 14) -> list[str]:
    """A lánc-összefoglaló kapu-része: legfeljebb 6 hiba- és 12 figyelmeztetéssor, együtt 14 (a futtat
    két további sorával legfeljebb 20 sor)."""
    sz = k["szamok"]
    x = []
    if sz["elfogadva"]:
        x.append(f"{sz['elfogadva']} elfogadva")
    if sz["teves_hiba"]:
        x.append(f"{sz['teves_hiba']} „téves hiba?”")
    if sz["felulbiralva"]:
        x.append(f"{sz['felulbiralva']} felülbírálva")
    fej = f"KAPU: {'ZÖLD' if k['zold'] else 'PIROS'} – {sz['hiba']} hiba, {sz['figy']} figyelmeztetés" + \
        (f" ({', '.join(x)})" if x else "") + ("" if k["zold"] or not k["atadhato"] else " · átadható (téves hiba?)")
    sorok = [fej]

    def sor(x):
        jel = " [téves hiba?]" if x.get("teves_hiba") else " [felülbírálva]" if x.get("felulbiralva") else ""
        return f" {'HIBA' if x['sulyossag'] == 'hiba' else 'FIGY'} {x['kod']} {x['lepes'] or '–'} " \
               f"{x['obj'] or ''}{' ' if x['obj'] else ''}{x['uzenet']}{jel}"[:200]
    hibak = [x for x in k["leletek"] if x["sulyossag"] == "hiba" and not x.get("felulbiralva")]
    figy = [x for x in k["leletek"] if x["sulyossag"] == "figy" and not x.get("elfogadva")]
    felul = [x for x in k["leletek"] if x.get("felulbiralva")]
    nh = min(len(hibak), max_hiba)
    nf = min(len(figy), max_figy, max_lelet - nh)
    sorok += [sor(x) for x in hibak[:nh]] + [sor(x) for x in figy[:nf]]
    tobb = len(hibak) - nh + len(figy) - nf
    if tobb:
        sorok.append(f" … {tobb} további: kapu.json")
    sorok += [f" FELÜLBÍRÁLVA {x['kod']} {x['lepes'] or '–'} {x['obj'] or ''}: {x['felulbiralva']}"[:200] for x in felul]
    if k["ervenytelen_kivetelek"]:
        sorok.append(f" érvénytelen kivétel: {len(k['ervenytelen_kivetelek'])} (kapu.json)")
    sorok.append(k["allapot"])
    return sorok


# --- a lánc belépési pontja ---------------------------------------------------------

def futtat(mappa: Path, atadas: bool = False, valtozott: bool = False,
           vezerlo: bool = False) -> tuple[int, list[str]]:
    """Kapu + tábla + szöveg; átadáskor lapok, kivágatok, lépéskulcs. (kilépési kód 0/1, összefoglaló sorai).
    vezerlo: a vezérlő futása (--atadas, --vegleges), csak ekkor számít a `felulbiral` kivétel."""
    import lapok
    import tabla
    mu = Munka(mappa)
    k = kapu_munkan(mu, vezerlo)
    json_ir(mu.m / "kapu.json", k)
    sorok = osszefoglalo(k)
    sorok.append(tabla.ir(mu, k))
    if atadas:
        sorok.append(lapok.atadas(mu, k, valtozott))
    return (0 if k["zold"] else 1), sorok


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mappa", type=Path)
    ap.add_argument("--atadas", action="store_true", help="lapok, kivágatok, lépéskulcs (1080p-s render után)")
    ap.add_argument("--valtozott", action="store_true", help="lapok-valtozott/ a lepeskulcs-1.json-hoz képest")
    a = ap.parse_args()
    kod, sorok = futtat(a.mappa, a.atadas, a.valtozott, vezerlo=a.atadas)
    print("\n".join(sorok))
    sys.exit(kod)


if __name__ == "__main__":
    main()
