"""Számolás és számláló: minden szám a saját kimondott szavára, az eredmény a horgonyra.

    sz = Szamolas(["6", "+ 5", "- 2"], "9", hely=DOWN, nev="szam1", pipa=True)
    return [sz.lepesek()]   # „Hat plusz öt, mínusz kettő, az kilenc.”
A számot tartalmazó tag Szora-elem (a k-adik azonos értékű tag a k-adik ilyen szóra); a szám
nélküli tag a lépés elején. Az eredmény a lépés szabad {} horgonyára jön (az értékének egyeznie
kell), különben az érték utolsó előfordulására; ha az nem a tagok után van, a render hibával áll le.
"""

from __future__ import annotations

import numpy as np
from manim import ORIGIN, RIGHT, ChangeDecimalToValue, Circle, Create, Integer, Line, MathTex, Text, VGroup, \
    VMobject, Write

from .kiemeles import atir
from .naplo import _jelol, szamok
from .stilus import FEHER, PIROS, ZOLD, betumeret
from .utem import Eredmeny, Szora


def _ertek(tex: str):
    sz, _ = szamok(tex)
    return abs(sz[0]) if sz else None


class Szamolas:
    def __init__(self, tagok: list[str], eredmeny: str, hely=ORIGIN, meret="L", nev: str = "szamolas",
                 pipa: bool = False):
        self.nev, self.tagok, self.eredmeny = nev, list(tagok), eredmeny
        fs = betumeret(meret)
        self.mob = MathTex(*self.tagok, "=", eredmeny, font_size=fs).move_to(hely)
        _jelol(self.mob, nev=nev, kat="szamolas", csoport=nev)
        for i in range(len(self.tagok)):
            _jelol(self.mob[i], nev=f"{nev}_{i + 1}", csoport=nev, font=fs)
        _jelol(self.mob[-2], nev=f"{nev}_egyenlo", csoport=nev, font=fs)
        _jelol(self.mob[-1], nev=f"{nev}_eredmeny", csoport=nev, font=fs, kat="eredmeny")
        self.pipa = None
        if pipa:
            self.pipa = pipa_jel(self.mob.get_right() + RIGHT * 0.5, nev=f"{nev}_pipa", csoport=nev)

    def lepesek(self, rt: float = 0.5) -> list:
        ki, hanyadik = [], {}
        for i, tag in enumerate(self.tagok):
            def fv(m=self.mob[i]):
                return Write(m)
            v = _ertek(tag)
            if v is None:
                ki.append((rt, fv))
            else:
                hanyadik[v] = hanyadik.get(v, 0) + 1
                ki.append(Szora(v, rt, fv, hanyadik=hanyadik[v]))

        def eredmeny():
            a = [Write(self.mob[-2]), Write(self.mob[-1])]
            return a + ([Create(self.pipa)] if self.pipa is not None else [])
        ki.append(Eredmeny(_ertek(self.eredmeny), rt, eredmeny))
        return ki


class Szamlalo:
    """Egész számláló. `fut(veg)`: folyamatos számolás (a kapu a végét méri a kimondáshoz);
    `valt(uj)`: ugrás az atir-ral."""

    def __init__(self, kezd: int = 0, hely=ORIGIN, meret="L", nev: str = "szamlalo"):
        self.nev, self.meret = nev, meret
        self.mob = Integer(kezd, font_size=betumeret(meret)).move_to(hely)
        _jelol(self.mob, nev=nev, kat="szamlalo")

    def fut(self, veg: int):
        return ChangeDecimalToValue(self.mob, veg)

    def valt(self, uj: int):
        m = Integer(uj, font_size=betumeret(self.meret)).move_to(self.mob)
        a = atir(self.mob, m)
        self.mob = m
        return a


def pipa_jel(poz=ORIGIN, meret: float = 0.4, nev: str | None = None, csoport: str | None = None):
    """Zöld pipa (alakja is pipa, nem csak a színe)."""
    m = VMobject().set_points_as_corners([[-0.5, 0.0, 0], [-0.15, -0.4, 0], [0.55, 0.45, 0]])
    m.set_stroke(ZOLD, 7).set_fill(opacity=0).scale(meret).move_to(poz)
    return _jelol(m, nev=nev, kat="jelolo", alak="pipa", csoport=csoport)


pipa = pipa_jel


def kerdojel(poz=ORIGIN, meret="XL", nev: str | None = None):
    return _jelol(Text("?", font_size=betumeret(meret), color=FEHER).move_to(poz), nev=nev)


def hibas_kor(mob, nev: str | None = None):
    """A hibás eredmény jele: kör a szám körül, és mellette, a körön kívül egy X (az alakja is
    jelez, nem csak a piros szín; a számot nem húzza át, így nem fed rá). vonatkozik: mob."""
    r = max(mob.width, mob.height) / 2 + 0.2
    k = Circle(radius=r).set_stroke(PIROS, 5).move_to(mob)
    x = k.get_center() + np.array([r + 0.35, r * 0.6, 0])
    h = 0.17
    jel = VGroup(Line(x + np.array([-h, -h, 0]), x + np.array([h, h, 0])),
                 Line(x + np.array([-h, h, 0]), x + np.array([h, -h, 0]))).set_stroke(PIROS, 5)
    return _jelol(VGroup(k, jel), nev=nev, kat="kiemeles", alak="hibas_kor", vonatkozik=[mob])
