"""Képlet tagonként szóra kötve (K2b): minden tag a kimondott szavára jelenik meg.

    k = Keplet([(r"|A \\cup B|", "unió"), ("=", "egyenlő"), ("|A|", "A"), ("+", "plusz"),
                ("|B|", "B"), ("-", "mínusz"), (r"|A \\cap B|", "metszet")], hely=UP * 2, meret="L", nev="kepl")
    return [k.lepesek()]          # egy lépés: minden tag a saját szaván
A szo=None tag a lépés elején jelenik meg (ha a tag ott hangzik el); minden tagnál kötelező a szó
vagy a kifejezett None. Ugyanaz a szó többször: (tag, ("A", 2)) a második „A”-ra köt.
"""

from __future__ import annotations

from manim import ORIGIN, MathTex, Write

from .naplo import VideotarHiba, _jelol
from .stilus import FEHER, betumeret
from .utem import Szora


class Keplet:
    def __init__(self, tagok: list[tuple], hely=ORIGIN, meret="L", nev: str = "keplet", szin=FEHER):
        for t in tagok:
            if not isinstance(t, tuple) or len(t) != 2:
                raise VideotarHiba(f"Keplet({nev}): a tag (tex, szo) pár legyen, a szó vagy None kifejezetten "
                                   f"(K2b): {t!r}")
        self.nev, self.tagok = nev, list(tagok)
        fs = betumeret(meret)
        self.mob = MathTex(*[t for t, _ in tagok], font_size=fs, color=szin).move_to(hely)
        _jelol(self.mob, nev=nev, kat="keplet", csoport=nev)
        for i, (tex, szo) in enumerate(tagok):
            s = szo[0] if isinstance(szo, tuple) else szo
            _jelol(self.mob[i], nev=f"{nev}_{i + 1}", kat="keplet", szo=s, csoport=nev, font=fs)

    def __getitem__(self, i):
        return self.mob[i]

    def lepesek(self, rt: float = 0.5, anim=Write) -> list:
        """A tagok lépéselemei sorban: a szóval jelölt tag Szora-elem, a None-os sima (rt, fv)."""
        ki = []
        for i, (_, szo) in enumerate(self.tagok):
            def fv(m=self.mob[i]):
                return anim(m)
            if szo is None:
                ki.append((rt, fv))
            elif isinstance(szo, tuple):
                ki.append(Szora(szo[0], rt, fv, hanyadik=szo[1]))
            else:
                ki.append(Szora(szo, rt, fv))
        return ki
