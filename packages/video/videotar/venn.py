"""Két halmaz Venn-ábrája alaphalmazzal.

Elemi régiók: "a-b" (csak A), "ab" (metszet), "b-a" (csak B), "kivul" (az alaphalmaz a körökön
kívül). Összetett kulcsok: "a" (A), "b" (B), "aub" (unió); több kulcs együtt is megadható
(a B komplementere: regio("a-b", "kivul")). A kör és a betűje `cimke=`-viszonnyal regisztrált
(K6b: a feliratos kör nem „csak színben” különbözik), és egy tartalmi csoport (K9).
"""

from __future__ import annotations

import numpy as np
from manim import LEFT, ORIGIN, RIGHT, Circle, Difference, FadeIn, Intersection, MathTex, RoundedRectangle, \
    Text, Union

from .kiemeles import kiemel, kore_rajzol
from .naplo import VideotarHiba, _jelol
from .stilus import FEHER, KEK, SARGA, betumeret

ELEMI = ("a-b", "ab", "b-a", "kivul")
OSSZETETT = {"a": ("a-b", "ab"), "b": ("ab", "b-a"), "aub": ("a-b", "ab", "b-a")}


class Venn2:
    def __init__(self, nevek=("A", "B"), cimkek=None, kozep=ORIGIN, r: float = 1.6, alaphalmaz: bool = True,
                 nev: str = "venn", szinek=(KEK, SARGA), u_nev: str = "U", tobblet: float = 1.6):
        self.nev, self.r, self._kiemelesek = nev, r, 0
        c = np.array(kozep, dtype=float)
        self.c, self.d = c, 0.6 * r
        self.kozep = {"a": c + LEFT * self.d, "b": c + RIGHT * self.d}
        self.kor, self.betu, self.cimke = {}, {}, {}
        irany = {"a": np.array([-1.0, 1.0, 0]) / np.sqrt(2), "b": np.array([1.0, 1.0, 0]) / np.sqrt(2)}
        self.szel = 2 * (self.d + r) + tobblet          # tobblet: a körökön kívüli sáv a két oldalon együtt
        self.mag = 2 * r + 1.2
        for i, k in enumerate("ab"):
            cs = f"{nev}_{k}"
            kor = Circle(radius=r).set_stroke(szinek[i], 4).move_to(self.kozep[k]).set_z_index(1)
            betu = MathTex(nevek[i], font_size=betumeret("L"), color=szinek[i])
            betu.move_to(self.kozep[k] + (r + 0.45) * irany[k]).set_z_index(3)
            _jelol(betu, nev=f"{nev}_betu_{k}", csoport=cs)
            _jelol(kor, nev=f"{nev}_kor_{k}", cimke=betu, csoport=cs, kat="keret")
            self.kor[k], self.betu[k] = kor, betu
            if cimkek:
                t = Text(cimkek[i], font_size=betumeret("M"), color=szinek[i])
                t.move_to(np.array([self.kozep[k][0], c[1] + self.mag / 2 + 0.4, 0]))
                # hosszú feliratnál a két felirat nem érhet össze: a középvonaltól kifelé tolva
                tul = t.get_right()[0] - (c[0] - 0.2) if k == "a" else (c[0] + 0.2) - t.get_left()[0]
                if tul > 0:
                    t.shift((LEFT if k == "a" else RIGHT) * tul)
                self.cimke[k] = _jelol(t, nev=f"{nev}_cimke_{k}", csoport=cs)
        self.keret = self.u = None
        if alaphalmaz:
            self.keret = RoundedRectangle(corner_radius=0.25, width=self.szel, height=self.mag)
            self.keret.set_stroke(FEHER, 2).move_to(c)
            self.u = MathTex(u_nev, font_size=betumeret("L"))
            self.u.move_to(c + np.array([-self.szel / 2 + 0.4, self.mag / 2 - 0.4, 0])).set_z_index(3)
            _jelol(self.u, nev=f"{nev}_betu_u", csoport=f"{nev}_u")
            _jelol(self.keret, nev=f"{nev}_alaphalmaz", cimke=self.u, csoport=f"{nev}_u", kat="keret")
        # régiónként: a felirat (szám) helye lent, az elemek horgonya fent
        lent, fent = c[1] - 0.7, c[1] + 0.4
        self._felirat = {"a-b": np.array([c[0] - r, lent, 0]), "ab": np.array([c[0], lent, 0]),
                         "b-a": np.array([c[0] + r, lent, 0]),
                         "kivul": c + np.array([self.szel / 2 - 0.55, -self.mag / 2 + 0.45, 0])}
        self._elemhely = {"a-b": np.array([c[0] - r, fent, 0]), "ab": np.array([c[0], fent - 0.25, 0]),
                          "b-a": np.array([c[0] + r, fent, 0]),
                          "kivul": c + np.array([-self.szel / 2 + 0.6, -self.mag / 2 + 0.5, 0])}

    # --- rajz -------------------------------------------------------------------

    def kor_rajzol(self, kulcs: str, tartalom=()) -> list:
        """A kör (az elemei köré: előbb a helyükre!) és a betűje, a felirata."""
        ki = [kore_rajzol(self.kor[kulcs], tartalom), FadeIn(self.betu[kulcs])]
        if kulcs in self.cimke:
            ki.append(FadeIn(self.cimke[kulcs]))
        return ki

    def alaphalmaz_keret(self, tartalom=()) -> list:
        if self.keret is None:
            raise VideotarHiba(f"{self.nev}: alaphalmaz=False mellett nincs alaphalmaz-keret")
        return [kore_rajzol(self.keret, tartalom), FadeIn(self.u)]

    # --- régiók -----------------------------------------------------------------

    @staticmethod
    def _kulcsok(kulcsok) -> list[str]:
        ki = []
        for k in kulcsok:
            if k in OSSZETETT:
                ki += [x for x in OSSZETETT[k] if x not in ki]
            elif k in ELEMI:
                if k not in ki:
                    ki.append(k)
            else:
                raise VideotarHiba(f"ismeretlen régió: {k!r} (elemi: {', '.join(ELEMI)}; összetett: a, b, aub)")
        return ki

    def _elemi(self, k: str):
        a, b = self.kor["a"].copy(), self.kor["b"].copy()
        if k == "ab":
            return Intersection(a, b)
        if k == "a-b":
            return Difference(a, b)
        if k == "b-a":
            return Difference(b, a)
        if self.keret is None:
            raise VideotarHiba(f"{self.nev}: a „kivul” régióhoz alaphalmaz kell")
        return Difference(self.keret.copy(), Union(a, b))

    def regio(self, *kulcsok):
        """A régió(k) alakja (a kiemeléshez)."""
        el = self._kulcsok(kulcsok)
        if el == ["a-b", "ab"]:
            return self.kor["a"].copy()
        if el == ["ab", "b-a"]:
            return self.kor["b"].copy()
        if el == ["a-b", "ab", "b-a"]:
            return Union(self.kor["a"].copy(), self.kor["b"].copy())
        alakok = [self._elemi(k) for k in el]
        return alakok[0] if len(alakok) == 1 else Union(*alakok)

    def regio_kiemel(self, *kulcsok, vonatkozik=()):
        self._kiemelesek += 1
        return kiemel(self.regio(*kulcsok), vonatkozik, nev=f"{self.nev}_kiemel{self._kiemelesek}_{'+'.join(kulcsok)}")

    def bent(self, kulcs: str, p, margo: float = 0.25) -> bool:
        """A pont az elemi régióban van-e, a határvonalaktól legalább `margo` távolságra."""
        da = np.linalg.norm(np.asarray(p)[:2] - self.kozep["a"][:2])
        db = np.linalg.norm(np.asarray(p)[:2] - self.kozep["b"][:2])
        be, ki = self.r - margo, self.r + margo
        if kulcs == "ab":
            return da < be and db < be
        if kulcs == "a-b":
            return da < be and db > ki
        if kulcs == "b-a":
            return db < be and da > ki
        if kulcs == "kivul":
            dx, dy = abs(p[0] - self.c[0]), abs(p[1] - self.c[1])
            return dx < self.szel / 2 - margo - 0.1 and dy < self.mag / 2 - margo - 0.1 and da > ki and db > ki
        raise VideotarHiba(f"bent(): csak elemi régió lehet, nem {kulcs!r}")

    def regio_pont(self, kulcs: str):
        """Az elemi régió feliratának (számának) helye."""
        if kulcs not in ELEMI:
            raise VideotarHiba(f"regio_pont(): csak elemi régió lehet ({', '.join(ELEMI)}), nem {kulcs!r}")
        return self._felirat[kulcs].copy()

    def regio_szam(self, kulcs: str, ertek, ra: str | None = None, nev: str | None = None, meret="L"):
        """Szám a régió felirathelyén (megjelenítése a hívóé, Szora-val a kimondott szavára)."""
        m = MathTex(str(ertek), font_size=betumeret(meret)).move_to(self.regio_pont(kulcs)).set_z_index(3)
        return _jelol(m, nev=nev, ra=ra)

    def hanyszor(self, kulcs: str, n: int, nev: str | None = None, meret="L"):
        """„n×” a régió felirathelyén (0×–3×); a kimondott -szor/-szer szóra köss (Szora("kétszer"))."""
        if not 0 <= int(n) <= 3:
            raise VideotarHiba(f"hanyszor(): 0 és 3 közötti szám kell, nem {n}")
        m = MathTex(f"{int(n)}" + r"\times", font_size=betumeret(meret)).move_to(self.regio_pont(kulcs))
        return _jelol(m.set_z_index(3), nev=nev)

    def helyek(self, kulcs: str, n: int, lepes: float = 0.42) -> list:
        """n rácspont a régióban, a régió elemhorgonyához legközelebbiek (teljes, tartalomból adódó
        sorrend: távolság, majd felülről lefelé, balról jobbra)."""
        h = self._elemhely[kulcs]
        k = int(max(self.szel, self.mag) / lepes) + 1     # az egész téglalap
        pontok = [h + np.array([i * lepes, j * lepes, 0.0]) for i in range(-k, k + 1) for j in range(-k, k + 1)]
        foglalt = [m for m in (*self.betu.values(), self.u) if m is not None]   # a betűk és az U helye
        pontok = [p for p in pontok if self.bent(kulcs, p) and not any(
            abs(p[0] - m.get_center()[0]) < m.width / 2 + 0.3 and abs(p[1] - m.get_center()[1]) < m.height / 2 + 0.3
            for m in foglalt)]
        pontok.sort(key=lambda p: (round(float(np.linalg.norm(p - h)), 6), -round(float(p[1]), 6), round(float(p[0]), 6)))
        if len(pontok) < n:
            raise VideotarHiba(f"{self.nev}: a(z) {kulcs} régióban kevés a hely: {len(pontok)} < {n}")
        return pontok[:n]

    def elemek_helyre(self, elemek: list, regiok: list[str], lepes: float = 0.42) -> list:
        """Mozgatás a régiókba: elemek[i] a regiok[i] elemi régióba (rácspontokra)."""
        if len(elemek) != len(regiok):
            raise VideotarHiba("elemek_helyre(): az elemek és a régiók száma eltér")
        db: dict[str, int] = {}
        for k in regiok:
            db[k] = db.get(k, 0) + 1
        helyek = {k: self.helyek(k, n, lepes) for k, n in db.items()}
        sorszam: dict[str, int] = {}
        ki = []
        for e, k in zip(elemek, regiok):
            i = sorszam.get(k, 0)
            sorszam[k] = i + 1
            ki.append(e.animate.move_to(helyek[k][i]))
        return ki


__all__ = ["Venn2", "ELEMI", "OSSZETETT"]
