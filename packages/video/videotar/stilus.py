"""Stílus: paletta, betűméret-skála, biztonsági sáv, szöveg-segéd és a paletta gépi próbája.

A szín csak megerősít; a jelentést az alak, a minta vagy a felirat hordozza (mérce, 1. szabály).
A kategóriaszínek páronként színtévesztés-szimulációban (deuteranopia, protanopia) és
világosságban is elválnak; ezt a `paletta_hibak()` méri, a teszt egyszer lefuttatja.
"""

from __future__ import annotations

import itertools
import math

from manim import Text, config

HATTER = "#0E1117"
KEK = "#58C4DD"
SARGA = "#F4D345"
ZOLD = "#3F9142"
PIROS = "#EE6A96"
SZURKE = "#8A8F98"
FEHER = "#ECECEC"
KATEGORIA_SZINEK = (KEK, SARGA, ZOLD, PIROS)

MERET = {"S": 28, "M": 34, "L": 44, "XL": 56}   # a legkisebb 28 (K5: 24 alatt hiba)
SAV = 0.05                                       # biztonsági sáv a kép szélén (K3)

config.background_color = HATTER


def betumeret(meret) -> float:
    """A `MERET` kulcsa ("S", "M", "L", "XL") vagy szám."""
    return float(MERET[meret]) if isinstance(meret, str) else float(meret)


def szoveg(s: str, meret="M", nev: str | None = None, szin=FEHER, **kw) -> Text:
    """Text a skála méretével, regisztrálva (a napló a nevén követi)."""
    from .naplo import _jelol
    t = Text(s, font_size=betumeret(meret), color=szin, **kw)
    return _jelol(t, nev=nev, forras="videotar")


# ---------------------------------------------------------------- a paletta próbája

# Machado–Oliveira–Fernandes (2009), 1,0-s súlyosság, lineáris RGB-n
_PROT = ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998))
_DEUT = ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881))
MIN_DE_SZIMULALT = 20.0   # CIE76 ΔE a szimulált színek között
MIN_DL = 8.0              # L* különbség


def _linearis(hexa: str) -> tuple[float, float, float]:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    h = hexa.lstrip("#")
    return tuple(lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))


def _szimulal(rgb, matrix):
    return tuple(min(1.0, max(0.0, sum(matrix[i][j] * rgb[j] for j in range(3)))) for i in range(3))


def lab(rgb) -> tuple[float, float, float]:
    """Lineáris sRGB → CIELAB (D65)."""
    r, g, b = rgb
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def paletta_hibak(szinek=KATEGORIA_SZINEK) -> list[str]:
    """A színpárok, amelyek színtévesztésben vagy világosságban nem válnak el eléggé."""
    hibak = []
    for a, b in itertools.combinations(szinek, 2):
        ra, rb = _linearis(a), _linearis(b)
        dl = abs(lab(ra)[0] - lab(rb)[0])
        if dl < MIN_DL:
            hibak.append(f"{a}–{b}: világosság-különbség {dl:.1f} < {MIN_DL}")
        for nev, m in (("protanopia", _PROT), ("deuteranopia", _DEUT)):
            de = math.dist(lab(_szimulal(ra, m)), lab(_szimulal(rb, m)))
            if de < MIN_DE_SZIMULALT:
                hibak.append(f"{a}–{b}: {nev} ΔE {de:.1f} < {MIN_DE_SZIMULALT}")
    return hibak


__all__ = ["HATTER", "KEK", "SARGA", "ZOLD", "PIROS", "SZURKE", "FEHER", "KATEGORIA_SZINEK", "MERET", "SAV",
           "betumeret", "szoveg", "paletta_hibak"]
