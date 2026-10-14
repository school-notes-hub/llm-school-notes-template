"""Kiemelés, köré rajzolás, eltüntetés, szövegcsere.

Kiemelés mindig vastag fehér körvonallal (és halvány kitöltéssel), nem csak színnel (mérce, 1.).
Köré rajzolni csak azt lehet, ami már a helyén van (mérce, 3.): a `kore_rajzol` hibát dob, ha a
keret megjelenésének play-jében a vonatkozott objektum mozog (K7, futásidejű).
A szöveg- és számcsere egyetlen útja az `atir` (ReplacementTransform, a napló a régi nevén követi).
"""

from __future__ import annotations

from manim import Create, FadeIn, FadeOut, ReplacementTransform, ShowPassingFlash
from manim import Indicate as _Indicate

from . import naplo as _naplo
from .naplo import _jelol, atnevez_csere
from .stilus import FEHER


def _tartos(mob) -> None:
    if _naplo.AKTIV is not None:
        _naplo.AKTIV._tartos_hozzaad(mob)


def kore_rajzol(keret, elemek=(), anim=Create, nev: str | None = None):
    """A keret megjelenése az `elemek` köré. Ha ugyanebben a play-ben bármelyik elem mozog: VideotarHiba."""
    elemek = list(elemek) if isinstance(elemek, (list, tuple)) else [elemek]
    _jelol(keret, nev=nev, forras="sajat", vonatkozik=elemek)
    a = anim(keret)
    a._vt_kore = (keret, elemek)
    return a


def kiemel(alak, vonatkozik=(), nev: str | None = None, op: float = 0.18):
    """Tartós kiemelés (vastag fehér körvonal + halvány kitöltés) a lépés végéig."""
    k = alak.copy().set_fill(FEHER, opacity=op).set_stroke(FEHER, 5, opacity=1).set_z_index(1)
    _jelol(k, kat="kiemeles")
    _tartos(k)
    return kore_rajzol(k, vonatkozik, anim=FadeIn, nev=nev)


def korvonal(alak, vonatkozik=(), nev: str | None = None):
    """Tartós körvonal-kiemelés (kitöltés nélkül) a lépés végéig."""
    k = alak.copy().set_fill(opacity=0).set_stroke(FEHER, 6, opacity=1).set_z_index(1)
    _jelol(k, kat="kiemeles")
    _tartos(k)
    return kore_rajzol(k, vonatkozik, anim=Create, nev=nev)


def villan(alak, szelesseg: float = 0.5):
    """Átfutó fehér körvonal (nem tartós; a play végén eltűnik)."""
    return ShowPassingFlash(alak.copy().set_fill(opacity=0).set_stroke(FEHER, 6), time_width=szelesseg)


def Indicate(mob, **kw):  # noqa: N802  (a Manim sárga alapszíne kategóriaszín lenne)
    kw.setdefault("color", FEHER)
    return _Indicate(mob, **kw)


def pulzal(*mobok, sk: float = 1.2) -> list:
    return [Indicate(m, scale_factor=sk) for m in mobok]


def eltuntet(*mobok) -> list:
    """FadeOut objektumonként (listát, VGroup-ot is elfogad)."""
    ki = []
    for m in mobok:
        if isinstance(m, (list, tuple)):
            ki += eltuntet(*m)
        else:
            ki.append(FadeOut(m))
    return ki


def atir(regi, uj, **kw):
    """Szöveg- vagy számcsere: `regi` helyére `uj` (ReplacementTransform). Az új objektum a régi
    nevét és jelöléseit örökli, így a napló tartalomváltozásként látja. Utána `uj`-t használd."""
    atnevez_csere(regi, uj)
    return ReplacementTransform(regi, uj, **kw)


__all__ = ["kore_rajzol", "kiemel", "korvonal", "villan", "Indicate", "pulzal", "eltuntet", "atir"]
