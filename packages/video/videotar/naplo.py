"""Objektumnapló a kapunak (render_naplo.json, séma: naplo-sema.json).

Minden play/wait után pillanatkép készül a jelenet teljes családjáról; az előző play utáni
pillanatkép a következő play „előtte” állapota (köztük csak az fv mellékhatása lehet, például egy
self.add, és az a play-hez számít). A két pillanatkép különbségéből jönnek az események
(megjelenik, eltunik, mozog, atalakul, szinvaltas), függetlenül attól, hogy az objektum az
elemtárból vagy az író saját kódjából jön. A saját objektum jelölést a `jelol()`-lal kap; jelölés
nélkül automatikus nevet kap, és az általános szabályok vonatkoznak rá.

Dobozok 1920×1080-as pixelben, a render felbontásától függetlenül (16:9, frame_height = 8).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
from manim import (AnimationGroup, Circle, DecimalNumber, Dot, Integer, Line, MarkupText, Polygram,
                   SingleStringMathTex, Text, Transform, VMobject, config)
from manim.mobject.text.tex_mobject import MathTexPart

SEMA = "videotar-naplo/1"
KAPCSOLOK = ("ra", "kivul", "szamellenorzes")
SZOVEG = (Text, MarkupText, SingleStringMathTex, MathTexPart, DecimalNumber)
PX_W, PX_H = 1920, 1080
LATHATO = 0.01      # e fölötti átlátszóságú családtag látszik
MOZGAS_PX = 2       # ennél nagyobb dobozváltozás mozgás
KIS_ALAK = 0.03     # a kép szélességének ennyi része alatt az alak jelölő

AKTIV = None        # a futó VideoJelenet (a kiemelések tartósságához)


class VideotarHiba(RuntimeError):
    """Az elemtár szabálysértése futás közben (a render megáll, a kapu 3-as kódja)."""


# ---------------------------------------------------------------- regiszter

_REG: dict[int, tuple[object, dict]] = {}   # id → (mobject, adat); erős hivatkozás, így az id nem ismétlődik
_NEVEK: dict[str, int] = {}
_AUTO = [0]


def uj_regiszter() -> None:
    """Üres regiszter (minden render elején, és a tesztekben)."""
    _REG.clear()
    _NEVEK.clear()
    _AUTO[0] = 0


def adat(mob) -> dict | None:
    r = _REG.get(id(mob))
    return r[1] if r is not None and r[0] is mob else None


def _nev_foglal(mob, nev: str, a: dict) -> None:
    masik = _NEVEK.get(nev)
    if masik is not None and masik != id(mob):
        ma = _REG.get(masik)
        if ma is not None and not ma[1].get("lecserelt"):
            raise VideotarHiba(f"a(z) {nev!r} név már foglalt: minden objektumnak egyedi neve legyen")
    if a.get("nev") and _NEVEK.get(a["nev"]) == id(mob):
        del _NEVEK[a["nev"]]
    a["nev"] = nev
    _NEVEK[nev] = id(mob)


def _jelol(mob, nev: str | None = None, forras: str = "videotar", **jel):
    """Regisztrál és jelöl (az elemtár belső útja; a saját kód a `jelol()`-t hívja)."""
    a = adat(mob)
    if a is None:
        a = {"forras": forras}
        _REG[id(mob)] = (mob, a)
    a["jelolt"] = True
    if nev:
        a.pop("auto", None)
        _nev_foglal(mob, nev, a)
    for k, v in jel.items():
        if v is None:
            continue
        if k in KAPCSOLOK and (not isinstance(v, str) or not v.strip()):
            raise VideotarHiba(f"{k}= indok nélkül ({nev or type(mob).__name__}): a kapcsoló értéke "
                               f"kötelezően egy indokszöveg, például {k}=\"szám a régióban\"")
        if k == "vonatkozik":
            v = list(v) if isinstance(v, (list, tuple)) else [v]
            if not v:
                continue
            a[k] = a.get(k, []) + v
        else:
            a[k] = v
    return mob


def jelol(obj, nev: str | None = None, szo: str | None = None, vonatkozik=(), cimke=None, ra: str | None = None,
          kivul: str | None = None, szamellenorzes: str | None = None, csoport: str | None = None):
    """A saját kódú objektum jelölései (ugyanazok, amelyeket az elemtár magától ad).

    nev: egyedi név a táblában és a kapuban; szo: a kimondott szó, amelyre a megjelenése tartozik;
    vonatkozik: az objektumok, amelyekre rárajzoljuk (K7: előbb azok a helyükön); cimke: a felirata
    (K6b: a feliratos keret nem „csak színben” különbözik); ra/kivul/szamellenorzes: elhallgattató
    kapcsolók, kötelező indokszöveggel (K4, K3, K2); csoport: az egy tartalmi egységnek számító
    objektumok közös neve (K9). Visszaadja az objektumot.
    """
    return _jelol(obj, nev=nev, forras="sajat", szo=szo, vonatkozik=vonatkozik, cimke=cimke, ra=ra, kivul=kivul,
                  szamellenorzes=szamellenorzes, csoport=csoport)


def atnevez_csere(regi, uj) -> None:
    """Az `atir()` regisztrációja: az új objektum a régi nevét és jelöléseit örökli."""
    ra = adat(regi)
    if ra is None or not ra.get("nev"):
        return
    ua = adat(uj)
    if ua is not None and ua.get("nev") and not ua.get("auto"):
        ra["lecserelt"] = True
        return
    ra["lecserelt"] = True
    orokolt = {k: v for k, v in ra.items() if k not in ("nev", "lecserelt", "tartalom", "auto", "font0")}
    if ua is not None:
        orokolt.update({k: v for k, v in ua.items() if k != "auto"})
    _REG[id(uj)] = (uj, orokolt)
    if ra.get("auto"):
        orokolt["auto"] = True
    _nev_foglal(uj, ra["nev"], orokolt)


# ---------------------------------------------------------------- mérés

FW = 8.0 * 16 / 9
FH = 8.0
SK = PX_W / FW   # pixel / jelenetegység


def px(p) -> tuple[float, float]:
    return (float(p[0]) + FW / 2) * SK, (FH / 2 - float(p[1])) * SK


def tartalom(mob) -> str | None:
    a = adat(mob)
    if a is not None and "tartalom" in a:
        return a["tartalom"]
    if isinstance(mob, DecimalNumber):
        n = float(mob.number)
        d = int(getattr(mob, "num_decimal_places", 0) or 0)
        return str(int(round(n))) if isinstance(mob, Integer) or d == 0 else f"{n:.{d}f}"
    if isinstance(mob, (SingleStringMathTex, MathTexPart)):
        return mob.tex_string
    if isinstance(mob, (Text, MarkupText)):
        return getattr(mob, "original_text", None) or getattr(mob, "text", None)
    return None


_TEX_PARANCS = re.compile(r"\\[a-zA-Z]+")
_SZAM = re.compile(r"(-?)(\d+(?:[.,]\d+)?)\s*(×)?")


def szamok(s: str | None) -> tuple[list, list]:
    """A szövegben látható számok, és köztük az „n×” alakúak.

    A kötőjel csak akkor előjel, ha közvetlenül a szám előtt áll, és előtte a szöveg eleje, szóköz,
    „(” vagy „=” van („-3”, „x=-3”); a „− 6” (szóközzel) és az „5-3” műveleti jel.
    """
    if not s:
        return [], []
    t = re.sub(r"\\(times|cdot)\b", "×", s)
    t = re.sub(r"\\[,;:! ]", " ", t)
    t = _TEX_PARANCS.sub(" ", t).replace("{", " ").replace("}", " ").replace("−", "-").replace("\u2212", "-")
    ertekek, szor = [], []
    for m in _SZAM.finditer(t):
        if m.start(2) > 0 and (t[m.start(2) - 1].isalnum() or t[m.start(2) - 1] in ".,") and not m.group(1):
            continue
        v = float(m.group(2).replace(",", "."))
        elojel = m.group(1) and (m.start() == 0 or t[m.start() - 1] in " (=[")
        v = -v if elojel else v
        v = int(v) if float(v).is_integer() else v
        ertekek.append(v)
        if m.group(3):
            szor.append(v)
    return ertekek, szor


def _csak_szam(s: str | None) -> bool:
    return bool(s) and re.fullmatch(r"\s*[-−+]?\s*\d+(?:[.,]\d+)?\s*(\\times|×)?\s*", s) is not None


def _lathato_tagok(mob) -> tuple[list, float]:
    tagok, maxop = [], 0.0
    for m in mob.get_family():
        if len(m.points) == 0:
            continue
        if isinstance(m, VMobject):
            fo = m.get_fill_opacities()
            so = m.get_stroke_opacities()
            op = max(float(np.max(fo)) if len(fo) else 0.0,
                     float(np.max(so)) if len(so) and m.get_stroke_width() > 0 else 0.0)
        else:
            op = 1.0
        if op > LATHATO:
            tagok.append(m)
            maxop = max(maxop, op)
    return tagok, maxop


def _doboz(tagok) -> list[int] | None:
    if not tagok:
        return None
    p = np.concatenate([m.points for m in tagok])
    x0, y0 = px((p[:, 0].min(), p[:, 1].max()))
    x1, y1 = px((p[:, 0].max(), p[:, 1].min()))
    return [round(x0), round(y0), round(x1), round(y1)]


def doboz_mob(mob) -> list[int] | None:
    """Az objektum teljes családjának doboza, láthatóságtól függetlenül."""
    return _doboz([m for m in mob.get_family() if len(m.points)])


def _korvonalas(m) -> bool:
    so = m.get_stroke_opacities() if isinstance(m, VMobject) else []
    return isinstance(m, VMobject) and len(m.points) > 0 and m.get_stroke_width() > 0 and len(so) > 0 \
        and float(np.max(so)) > LATHATO


def _bezier_pontok(m) -> list[list[list[int]]]:
    """A görbe tört vonallal (görbénként a 0, ½, 1 paraméternél), részutanként."""
    pts = m.points
    if len(pts) % 4:
        return []
    utak, akt, elozo = [], [], None
    for i in range(0, len(pts), 4):
        p0, p1, p2, p3 = pts[i:i + 4]
        if elozo is not None and np.linalg.norm(p0 - elozo) > 1e-6:
            utak.append(akt)
            akt = []
        for t in (0.0, 0.5, 1.0):
            q = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
            x, y = px(q)
            pont = [round(x), round(y)]
            if not akt or akt[-1] != pont:
                akt.append(pont)
        elozo = p3
    if akt:
        utak.append(akt)
    return [u for u in utak if len(u) > 1]


def _vonal(mob) -> dict | None:
    if isinstance(mob, SZOVEG):
        return None
    tagok = [m for m in mob.get_family() if _korvonalas(m)]
    if not tagok:
        return None
    if isinstance(mob, Circle) and abs(mob.width - mob.height) < 1e-3 and tagok == [mob]:
        x, y = px(mob.get_center())
        return {"t": "kor", "k": [round(x), round(y)], "r": round(mob.width / 2 * SK)}
    if isinstance(mob, Line) and tagok and tagok[0] is mob:
        (x0, y0), (x1, y1) = px(mob.get_start()), px(mob.get_end())
        return {"t": "szakasz", "p": [[round(x0), round(y0)], [round(x1), round(y1)]]}
    utak = [u for m in tagok for u in _bezier_pontok(m)]
    return {"t": "torott", "p": utak} if utak else None


def _ket(x: float) -> int:
    return int(round(x / 2.0)) * 2


# ---------------------------------------------------------------- a napló

def _bejar(anims):
    for a in anims:
        yield a
        if isinstance(a, AnimationGroup):
            yield from _bejar(a.animations)


class Naplo:
    def __init__(self, jelenet, szigoru: bool = True):
        self.jelenet = jelenet
        self.szigoru = szigoru
        self.lepesek: list[dict] = []
        self.akt: dict | None = None
        self.allapot: dict[str, dict] = {}   # az utolsó pillanatkép
        self._kapcs_latott: set[str] = set()

    # --- nevek ---------------------------------------------------------------

    def nev(self, mob) -> str:
        a = adat(mob)
        if a is not None and a.get("nev"):
            return a["nev"]
        if a is None:
            a = {"forras": "sajat"}
            _REG[id(mob)] = (mob, a)
        _AUTO[0] += 1
        alap = a.get("kat") or type(mob).__name__
        t = tartalom(mob)
        nev = f"{alap}#{_AUTO[0]}" + (f" „{t[:24]}”" if t else "")
        a["auto"] = True
        _nev_foglal(mob, nev, a)
        return nev

    @staticmethod
    def _reg_utod(mob) -> bool:
        for m in mob.get_family()[1:]:
            a = adat(m)
            if a is not None and a.get("jelolt"):
                return True
        return False

    def _atomi(self, mob) -> bool:
        a = adat(mob)
        if isinstance(mob, SZOVEG) or (a is not None and a.get("jelolt")) or len(mob.points) > 0:
            return not self._reg_utod(mob) or len(mob.points) > 0
        return False

    def atomi_nevek(self, mob) -> list[str]:
        if self._atomi(mob):
            return [self.nev(mob)]
        return [n for c in mob.submobjects for n in self.atomi_nevek(c)]

    # --- pillanatkép ---------------------------------------------------------

    def pillanatkep(self) -> dict[str, dict]:
        ki: dict[str, dict] = {}
        for felso in self.jelenet.mobjects:
            self._jar(felso, None, None, felso, ki)
        return ki

    def _jar(self, m, csoport, reg_os, felso, ki) -> None:
        a = adat(m)
        if a is not None and a.get("csoport"):
            csoport = a["csoport"]
        if reg_os is None and a is not None and a.get("nev") and not a.get("auto"):
            reg_os = a["nev"]
        if self._atomi(m):
            nev = self.nev(m)
            if nev not in ki:
                ki[nev] = self._rekord(m, nev, csoport or reg_os or self.nev(felso))
            return
        for c in m.submobjects:
            self._jar(c, csoport, reg_os, felso, ki)

    def _rekord(self, mob, nev: str, csoport: str) -> dict:
        a = adat(mob) or {}
        tagok, op = _lathato_tagok(mob)
        d = _doboz(tagok)
        t = tartalom(mob)
        r = {"obj": nev, "kat": None, "fajta": type(mob).__name__, "csoport": csoport,
             "forras": a.get("forras", "sajat"), "lathato": d is not None, "doboz": d}
        w = (d[2] - d[0]) if d else 0
        h = (d[3] - d[1]) if d else 0
        if isinstance(mob, SZOVEG):
            if "font0" not in a:
                f0 = a.get("font") or getattr(mob, "font_size", None)
                a["font0"] = (float(f0) if f0 else None, float(mob.height))
            f0, h0 = a["font0"]
            if f0 and h0 > 1e-6:
                r["font"] = round(f0 * float(mob.height) / h0, 1)
        if tagok:
            m0 = tagok[0]
            fo = m0.get_fill_opacities() if isinstance(m0, VMobject) else []
            if len(fo) and float(np.max(fo)) > LATHATO:
                r["szin"] = m0.get_fill_color().to_hex()
            elif isinstance(m0, VMobject):
                r["szin"] = m0.get_stroke_color().to_hex()
        r["atl"] = round(op, 2)
        if t is not None:
            r["tartalom"] = t
            sz, szor = szamok(t)
            if sz:
                r["szamok"] = sz
            if szor:
                r["szor"] = szor
        r["kat"] = self._kat(mob, a, t, w, h)
        v = _vonal(mob)
        if v:
            r["vonal"] = v
        c = a.get("cimke")
        cimke = c if c is None or isinstance(c, str) else self.nev(c)
        if not isinstance(mob, SZOVEG):
            r["alairas"] = {"osztaly": a.get("alak") or type(mob).__name__,
                            "csucs": len(mob.get_vertices()) if isinstance(mob, Polygram) else None,
                            "meret": [_ket(w), _ket(h)], "minta": a.get("minta"),
                            "korvonal": round(float(mob.get_stroke_width()), 1) if isinstance(mob, VMobject) else 0.0,
                            "cimke": cimke}
        if a.get("szo"):
            r["szo"] = a["szo"]
        if a.get("vonatkozik"):
            r["vonatkozik"] = sorted({n for v in a["vonatkozik"]
                                      for n in ([v] if isinstance(v, str) else self.atomi_nevek(v))})
        if cimke is not None:
            r["cimke"] = cimke
        for k in KAPCSOLOK:
            if a.get(k):
                r[k] = a[k]
        return r

    @staticmethod
    def _kat(mob, a, t, w, h) -> str:
        if a.get("kat"):
            return a["kat"]
        if isinstance(mob, DecimalNumber):
            return "szam"
        if isinstance(mob, (SingleStringMathTex, MathTexPart)):
            return "szam" if _csak_szam(t) else "keplet"
        if isinstance(mob, SZOVEG):
            return "szoveg"
        if getattr(mob, "has_tip", None) and mob.has_tip():
            return "nyil"
        if isinstance(mob, Line):
            return "vonal"
        if isinstance(mob, Dot) or (0 < max(w, h) < KIS_ALAK * PX_W):
            return "jelolo"
        if isinstance(mob, VMobject) and _korvonalas(mob) and float(np.max(mob.get_fill_opacities())) < 0.5:
            return "keret"
        return "alak"

    # --- lépések és play-ek -------------------------------------------------

    def lepes_kezd(self, t: dict) -> None:
        self.akt = {"id": t["id"], "kezd_kocka": t["kezd_kocka"], "veg_kocka": t["veg_kocka"], "elemek": [],
                    "megjelenik": [], "eltunik": [], "mozog": [], "atalakul": [], "szinvaltas": [],
                    "kapcsolok": [], "utolso_valtozas": None, "allapot": {}}

    def elott(self, anims) -> dict:
        """A play előtt: a nyers Transform és a kore_rajzol előkészítése (pillanatkép itt nem kell)."""
        csere, kore = [], []
        for an in _bejar(anims):
            k = getattr(an, "_vt_kore", None)
            if k is not None:
                keret, elemek = k
                kore.append((keret, [(e, doboz_mob(e)) for e in elemek]))
            if isinstance(an, Transform) and not an.replace_mobject_with_target_in_scene \
                    and getattr(an, "target_mobject", None) is not None:
                src, cel = an.mobject, an.target_mobject
                if cel is src:
                    continue
                if isinstance(src, SZOVEG) and isinstance(cel, SZOVEG):
                    if tartalom(cel) is not None and tartalom(src) != tartalom(cel):
                        if self.szigoru:
                            raise VideotarHiba(
                                f"nyers {type(an).__name__} szöveges objektumon ({self.nev(src)} → "
                                f"„{tartalom(cel)}”): utána a régi szöveg maradna a nyilvántartásban; a szöveg- "
                                f"és számcsere egyetlen útja az atir(regi, uj)")
                        csere.append((src, cel))
                elif adat(cel) is not None and adat(cel).get("jelolt"):
                    csere.append((src, cel))
        return {"csere": csere, "kore": kore}

    def utan(self, ctx: dict, k0: int, k1: int, anims, info: dict) -> None:
        for src, cel in ctx["csere"]:
            ca = adat(cel) or {}
            sa = _jelol(src, forras="sajat")
            sa_adat = adat(sa)
            if isinstance(src, SZOVEG) and isinstance(cel, SZOVEG):
                sa_adat["tartalom"] = tartalom(cel)
            for k, v in ca.items():
                if k not in ("nev", "forras", "auto", "lecserelt", "font0", "csoport"):
                    sa_adat[k] = v
            if ca.get("nev") and not ca.get("auto"):
                ca["lecserelt"] = True
                sa_adat.pop("auto", None)
                _nev_foglal(src, ca["nev"], sa_adat)
        for keret, elemek in ctx["kore"]:
            for e, d0 in elemek:
                d1 = doboz_mob(e)
                if d0 and d1 and max(abs(x - y) for x, y in zip(d0, d1)) > MOZGAS_PX:
                    raise VideotarHiba(f"K7: kore_rajzol({self.nev(keret)}) ugyanabban a play-ben, amelyben "
                                       f"{self.nev(e)} mozog; előbb a helyére (külön lépéselem), aztán köré rajzolni")
        uj = self.pillanatkep()
        self._kulonbseg(self.allapot, uj, k0, k1, info.get("kotes"))
        self.allapot = uj
        if self.akt is None:
            return
        tipus = ", ".join(dict.fromkeys(type(a).__name__ for a in anims)) or "wait"
        elem = {"kezd_kocka": k0, "veg_kocka": k1, "tipus": tipus,
                "celok": sorted({n for a in anims for n in self.atomi_nevek(a.mobject)
                                 if getattr(a, "mobject", None) is not None and type(a).__name__ != "Wait"}),
                "rovidites": round(float(info.get("rovidites", 1.0)), 4)}
        kotes = info.get("kotes")
        if kotes:
            elem[kotes[0]] = kotes[1]
        self.akt["elemek"].append(elem)
        if anims and tipus != "Wait":
            self.akt["utolso_valtozas"] = k1

    def _kulonbseg(self, a: dict, b: dict, k0: int, k1: int, kotes) -> None:
        if self.akt is None:
            return
        akt = self.akt
        for nev in sorted(b):
            rb, ra = b[nev], a.get(nev)
            if rb["lathato"]:
                for k in KAPCSOLOK:
                    if rb.get(k) and (nev, k) not in self._kapcs_latott:
                        self._kapcs_latott.add((nev, k))
                        akt["kapcsolok"].append({"obj": nev, "kapcsolo": k, "indok": rb[k]})
            if rb["lathato"] and (ra is None or not ra["lathato"] or ra.get("tartalom") != rb.get("tartalom")):
                ok = "uj" if ra is None else ("atlatszosag" if not ra["lathato"] else "tartalom")
                e = {"obj": nev, "kocka": k0, "veg_kocka": k1, "kat": rb["kat"], "ok": ok, "csoport": rb["csoport"],
                     "kotes": kotes[0] if kotes else None}
                if kotes:
                    e["kotes_szo"] = kotes[1]
                for k in ("tartalom", "szamok", "szor", "szo"):
                    if k in rb:
                        e[k] = rb[k]
                if ok == "tartalom" and ra.get("szamok"):     # a K2 csak az újonnan megjelenő számot nézi
                    e["elozo_szamok"] = ra["szamok"]
                akt["megjelenik"].append(e)
            elif rb["lathato"] and ra is not None:
                if (ra.get("alairas") or {}).get("osztaly") != (rb.get("alairas") or {}).get("osztaly") or \
                        (ra.get("alairas") or {}).get("minta") != (rb.get("alairas") or {}).get("minta"):
                    akt["atalakul"].append({"obj": nev, "tol": k0, "ig": k1})
                    continue
                if max(abs(x - y) for x, y in zip(ra["doboz"], rb["doboz"])) > MOZGAS_PX:
                    akt["mozog"].append({"obj": nev, "tol": k0, "ig": k1})
                if ra.get("szin") != rb.get("szin"):
                    akt["szinvaltas"].append({"obj": nev, "kocka": k0, "veg_kocka": k1})
        for nev in sorted(a):
            if a[nev]["lathato"] and (nev not in b or not b[nev]["lathato"]):
                akt["eltunik"].append({"obj": nev, "kocka": k0, "veg_kocka": k1})

    def allapot_ment(self, kulcs: str) -> None:
        latszik = [{k: v for k, v in r.items() if k != "lathato" and v is not None}
                   for _, r in sorted(self.allapot.items()) if r["lathato"]]
        self.akt["allapot"][kulcs] = latszik

    def lepes_zar(self) -> None:
        self.allapot_ment("vege")
        for k in ("megjelenik", "eltunik", "szinvaltas"):
            self.akt[k].sort(key=lambda e: (e["kocka"], e["obj"]))
        for k in ("mozog", "atalakul"):
            self.akt[k].sort(key=lambda e: (e["tol"], e["obj"]))
        self.lepesek.append(self.akt)
        self.akt = None

    def ir(self, ut: Path, fej: dict) -> None:
        szoveg = json.dumps(dict(fej, lepesek=self.lepesek), ensure_ascii=False, indent=1) + "\n"
        tmp = ut.with_name(ut.name + ".tmp")
        tmp.write_text(szoveg, encoding="utf-8")
        os.replace(tmp, ut)


def sima(s: str) -> str:
    """Kisbetű, ékezet nélkül, csak betű és számjegy (a szóillesztéshez)."""
    s = unicodedata.normalize("NFD", str(s).lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))
