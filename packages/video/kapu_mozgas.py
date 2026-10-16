"""A kapu geometriai segédei és mozgásmérése a rendernapló végállapotaiból.

A köztes pálya nélkül csak igazolható elmozdulást mérünk. A mérési hiány adat,
nem kapulelet. A küszöbök figyelmeztetéshez használt eszközbeállítások.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kapu import Munka

LATHATO = 0.05
MOZGAS_FOK_S, EGYEDUL_FOK_S = 60, 120
MOZGAS_MIN_PX, MOZGAS_MIN_FOK = 24, 10
ELTOLAS_MIN_S = 0.5


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


def _pont_doboz(q, d) -> float:
    dx, dy = max(d[0] - q[0], 0, q[0] - d[2]), max(d[1] - q[1], 0, q[1] - d[3])
    return (dx * dx + dy * dy) ** 0.5


def _bovit(d, px) -> list:
    return [d[0] - px, d[1] - px, d[2] + px, d[3] + px]


def _kozep(d) -> tuple[float, float]:
    return (d[0] + d[2]) / 2, (d[1] + d[3]) / 2


def _elozo_vege(mu: Munka) -> dict[str, dict[str, dict]]:
    """Lépésenként az előző lépés végállapota (obj → objektum): ez a lépés kezdőképe."""
    ki, elozo = {}, {}
    for l in mu.lepesek:
        ki[l["id"]] = elozo
        elozo = {o["obj"]: o for o in l["allapot"]["vege"] if o.get("atl", 1.0) > LATHATO}
    return ki


def _tav(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _egyenesek(o: dict) -> list:
    """Hosszú, egyenes részutak; a pontot vagy betűt alkotó kis vonások nélkül."""
    return [(p[0], p[-1]) for p in _vonalak(o.get("vonal"))
            if _tav(p[0], p[-1]) >= 48 and all(_pont_szakasz(q, p[0], p[-1]) <= 2 for q in p)]


def _azonos_szakasz(a, b) -> bool:
    return ((_tav(a[0], b[0]) <= 2 and _tav(a[1], b[1]) <= 2) or
            (_tav(a[0], b[1]) <= 2 and _tav(a[1], b[0]) <= 2))


def _forgatas(a: dict, b: dict) -> tuple | None:
    """Csak a sugár két állása közti kisebb szög; a szögív nem útbizonyíték."""
    jeloltek = []
    ea, eb = _egyenesek(a), _egyenesek(b)
    va = [e for e in ea if not any(_azonos_szakasz(e, f) for f in eb)]
    vb = [e for e in eb if not any(_azonos_szakasz(e, f) for f in ea)]
    for p, q in va:
        for u, v in vb:
            for c, x, d, y in ((p, q, u, v), (p, q, v, u), (q, p, u, v), (q, p, v, u)):
                if _tav(c, d) > 2 or abs(_tav(c, x) - _tav(d, y)) > 3:
                    continue
                ax, ay, bx, by = x[0] - c[0], x[1] - c[1], y[0] - d[0], y[1] - d[1]
                szog = abs(math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by)))
                jeloltek.append((_tav(c, x), szog, c))
    mozgo = [j for j in jeloltek if j[1] >= MOZGAS_MIN_FOK]
    return max(mozgo or jeloltek) if jeloltek else None


def _eltolas(a: dict, b: dict) -> float | None:
    """Azonos alak eltolása. A növekvő görbe dobozának közepe nem mozgó pont."""
    da, db = a["doboz"], b["doboz"]
    if any(abs((da[j + 2] - da[j]) - (db[j + 2] - db[j])) > 3 for j in (0, 1)):
        return None
    dx, dy = db[0] - da[0], db[1] - da[1]
    va, vb = _vonalak(a.get("vonal")), _vonalak(b.get("vonal"))
    if len(va) != len(vb) or any(len(p) != len(q) for p, q in zip(va, vb)):
        return None
    if any(_tav((p[0] + dx, p[1] + dy), q) > 4 for u, v in zip(va, vb) for p, q in zip(u, v)):
        return None
    return _tav(_kozep(da), _kozep(db))


def _kis_zart_utak(o: dict) -> list:
    ki = []
    for p in _vonalak(o.get("vonal")):
        if len(p) < 4 or _tav(p[0], p[-1]) > 2:
            continue
        d = [min(q[0] for q in p), min(q[1] for q in p), max(q[0] for q in p), max(q[1] for q in p)]
        if 4 <= min(d[2] - d[0], d[3] - d[1]) and max(d[2] - d[0], d[3] - d[1]) <= 60:
            ki.append(_kozep(d))
    return ki


def mozgasi_meresek(mu: Munka) -> list[dict]:
    """A rendernapló tényleges időtartama és geometriája, név- és tantárgyfüggetlenül.
    A régi napló play-enként nem őriz köztes állapotot: csak az egyértelmű, egyetlen
    mozgás két végállapotából számolunk, és alsó becslésnek nevezzük. Ismeretlen út
    nem lesz mért nulla. Az azonos sugárállásból teljes fordulat nem igazolható."""
    ki, elozok = [], _elozo_vege(mu)
    for l in mu.lepesek:
        veg = {o["obj"]: o for o in l["allapot"]["vege"]}
        darab = Counter(s["obj"] for s in l["mozog"])
        for s in l["mozog"]:
            nev = s["obj"]
            a, b = elozok[l["id"]].get(nev), veg.get(nev)
            if not a or not b or a.get("kat") == "kiemeles":
                continue
            dt = (s["ig"] - s["tol"]) / mu.fps
            if dt <= 0:
                continue
            m = {"lepes": l["id"], "obj": nev, "tol": s["tol"], "ig": s["ig"], "ido_s": round(dt, 4),
                 "forras": "végállapotok; alsó becslés"}
            ut = _eltolas(a, b) if darab[nev] == 1 else None
            forgas = _forgatas(a, b) if darab[nev] == 1 and not (ut and ut >= MOZGAS_MIN_PX) else None
            szog = forgas[1] if forgas else None
            if szog is not None and szog >= MOZGAS_MIN_FOK:
                # Két külön képrészben futó jel (például körpont és grafikonpont), vagy
                # egyidejű másik tartalmi mozgás: két dolgot kell együtt követni.
                pontok = _kis_zart_utak(b)
                # Kitöltött, vonás nélküli körpontot a régi napló nem bont ki. A sugár
                # mellett másik képrészbe érő görbe/vetítés is két kép követését jelenti.
                tavoli_palya = any(_tav(q, forgas[2]) > max(2.5 * forgas[0], 1920 / 4)
                                  for p in _vonalak(b.get("vonal")) for q in p)
                paros = tavoli_palya or any(_tav(p, q) > 120 for i, p in enumerate(pontok) for q in pontok[i + 1:]) or any(
                    t["obj"] != nev and t["tol"] < s["ig"] and t["ig"] > s["tol"] and
                    not _szoveg(mu.attr.get(t["obj"], {})) and mu.attr.get(t["obj"], {}).get("kat") != "kiemeles"
                    and (doboz := mu.attr.get(t["obj"], {}).get("doboz"))
                    and _pont_doboz(_kozep(doboz), _bovit(b["doboz"], 120)) > 0
                    for t in l["mozog"])
                m.update(fok=round(szog, 2), fok_s=round(szog / dt, 2),
                         kuszob_fok_s=MOZGAS_FOK_S if paros else EGYEDUL_FOK_S)
            if ut is not None and ut > MOZGAS_MIN_PX:
                m.update(ut_px=round(ut, 2), px_s=round(ut / dt, 2), min_ido_s=ELTOLAS_MIN_S)
            if "fok_s" not in m and "px_s" not in m:
                if darab[nev] > 1 or (ut is None and (szog is None or szog < 1)):
                    m["nem_mert"] = "a köztes pálya hiányzik; a doboz változása lehet alakváltozás is"
                else:
                    continue  # igazoltan apró igazítás
            ki.append(m)
    return ki


