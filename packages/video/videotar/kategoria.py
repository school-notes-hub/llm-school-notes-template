"""Kategóriás elemek: a kategóriát az alak (és a minta) hordozza, a szín csak megerősít (K6a).

    kat = Kategoriak({"sport": ("haromszog", KEK, None), "zene": ("negyzet", SARGA, None),
                      "mindketto": ("haromszog", ZOLD, "keretes")})
    e = kat.elem("sport", poz, nev="t01", csoport="tanulok")
    kat.atalakit(e, "zene")      # morph: alak és szín együtt vált
"""

from __future__ import annotations

from manim import ORIGIN, PI, Circle, RegularPolygon, Square, Transform, Triangle, VGroup

from .naplo import VideotarHiba, _jelol

ALAKOK = ("kor", "haromszog", "negyzet", "otszog", "rombusz")
MINTAK = (None, "keretes", "ures")


def _alak(alak: str, meret: float):
    if alak == "kor":
        return Circle(radius=meret / 2)
    if alak == "haromszog":
        return Triangle().scale_to_fit_width(meret * 1.1)
    if alak == "negyzet":
        return Square(side_length=meret * 0.9)
    if alak == "otszog":
        return RegularPolygon(5).scale_to_fit_width(meret)
    return Square(side_length=meret * 0.75).rotate(PI / 4)   # rombusz


class Kategoriak:
    def __init__(self, katok: dict[str, tuple], meret: float = 0.3):
        self.katok, self.meret = {}, meret
        latott: dict[tuple, str] = {}
        for nev, (alak, szin, minta) in katok.items():
            if alak not in ALAKOK:
                raise VideotarHiba(f"ismeretlen alak: {alak!r} (lehet: {', '.join(ALAKOK)})")
            if minta not in MINTAK:
                raise VideotarHiba(f"ismeretlen minta: {minta!r} (lehet: None, keretes, ures)")
            if (alak, minta) in latott:
                raise VideotarHiba(f"K6a: a(z) {nev!r} és a(z) {latott[(alak, minta)]!r} kategória csak színben "
                                   f"különbözne (alak: {alak}, minta: {minta}); adj más alakot vagy mintát")
            latott[(alak, minta)] = nev
            self.katok[nev] = (alak, szin, minta)

    def _rajz(self, kat: str):
        if kat not in self.katok:
            raise VideotarHiba(f"ismeretlen kategória: {kat!r}")
        alak, szin, minta = self.katok[kat]
        a = _alak(alak, self.meret)
        if minta == "ures":
            a.set_fill(opacity=0).set_stroke(szin, 4)
        else:
            a.set_fill(szin, 1).set_stroke(width=0)
        if minta == "keretes":
            a.scale(0.75).move_to(ORIGIN)
            a = VGroup(a, Square(side_length=self.meret * 1.15).set_stroke(szin, 3).set_fill(opacity=0))
        return a

    def elem(self, kat: str, poz=ORIGIN, nev: str | None = None, csoport: str | None = None):
        alak, _, minta = self.katok.get(kat, (None, None, None))
        m = self._rajz(kat).move_to(poz)
        return _jelol(m, nev=nev, kat="jelolo", alak=alak, minta=minta, kategoria=kat, csoport=csoport)

    def atalakit(self, elem, uj_kat: str):
        """Morph az új kategória alakjára és színére (Transform; a napló az új alakot rögzíti)."""
        alak, _, minta = self.katok.get(uj_kat, (None, None, None))
        uj = self._rajz(uj_kat).move_to(elem.get_center())
        _jelol(uj, kat="jelolo", alak=alak, minta=minta, kategoria=uj_kat)
        return Transform(elem, uj)
