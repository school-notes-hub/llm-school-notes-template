"""Szögjelek a magyar iskolai jelölés szerint.

A derékszög jele a csúcs köré rajzolt körív (mint a többi szögjelé), benne egy pont; a négyzetes sarok az
angol jelölés, nálunk nem szabványos (mérce: a derékszög jele). A két szár iránya bármilyen lehet (nem csak
tengelyirányú), és a sorrendjük nem számít: az ív mindig a két szár közti 90°-os tartományban fut.
"""

from __future__ import annotations

import numpy as np
from manim import Arc, Dot, VGroup

from .naplo import VideotarHiba, _jelol
from .stilus import FEHER

DEREKSZOG_TURES_FOK = 2.0     # ennél jobban eltérő szárak közé a derékszögjel hamis lenne


def _irany(u, nev: str) -> np.ndarray:
    v = np.zeros(3)
    a = np.asarray(u, dtype=float).ravel()
    v[:min(3, a.size)] = a[:3]
    v[2] = 0.0
    h = float(np.linalg.norm(v))
    if not np.isfinite(v).all() or h < 1e-9:
        raise VideotarHiba(f"derekszog: a(z) {nev} szárirány nullvektor vagy nem véges ({a.tolist()})")
    return v / h


def derekszog(csucs, u1, u2, r: float = 0.35, szin=FEHER, vastag: float = 3, nev: str | None = None,
              csoport: str | None = None, vonatkozik=()):
    """Derékszögjel: negyedkörív a `csucs` körül `r` sugárral az `u1` és `u2` szárirány között, a
    szögfelezőn a sugár felénél egy pont. VGroup(ív, pont), regisztrálva (jelölő, alak: derekszog).

    `u1`, `u2`: a két szár iránya a csúcsból (vektor, pl. `RIGHT`, `B - A`); a sorrendjük mindegy.
    Ha a két irány nem merőleges (±2°), VideotarHiba: nem derékszögre derékszögjel nem kerülhet.
    `vonatkozik`: a szárak objektumai (K7: azok már a helyükön vannak, amikor a jel megjelenik)."""
    if not (np.isfinite(r) and r > 0):
        raise VideotarHiba(f"derekszog: a sugár pozitív, véges szám legyen (r={r})")
    a, b = _irany(u1, "első"), _irany(u2, "második")
    kezd = float(np.arctan2(a[1], a[0]))
    nyilas = float(np.arctan2(a[0] * b[1] - a[1] * b[0], float(np.dot(a, b))))   # előjeles, (−π, π]
    if abs(abs(np.degrees(nyilas)) - 90.0) > DEREKSZOG_TURES_FOK:
        raise VideotarHiba(f"derekszog: a két szár {abs(np.degrees(nyilas)):.1f}°-ot zár be, nem derékszöget")
    c = np.zeros(3)
    p = np.asarray(csucs, dtype=float).ravel()
    c[:min(3, p.size)] = p[:3]
    if not np.isfinite(c).all():
        raise VideotarHiba(f"derekszog: a csúcs nem véges ({p.tolist()})")
    iv = Arc(radius=r, start_angle=kezd, angle=nyilas, arc_center=c, color=szin, stroke_width=vastag)
    f = (a + b) / np.linalg.norm(a + b)
    pont = Dot(c + f * r * 0.5, radius=max(0.03, r * 0.11), color=szin)
    return _jelol(VGroup(iv, pont), nev=nev, kat="jelolo", alak="derekszog", csoport=csoport, vonatkozik=vonatkozik)


__all__ = ["derekszog"]
