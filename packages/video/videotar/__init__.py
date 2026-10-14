"""videotar – Manim-elemtár az oktatóvideókhoz (Manim CE 0.22). Az író olvasmánya: API.md.

Kötelező belőle az ütemező (VideoJelenet, Horgony, Szora) és a napló (jelol); a többi segédlet.
"""

from .kategoria import Kategoriak
from .keplet import Keplet
from .kiemeles import Indicate, atir, eltuntet, kiemel, kore_rajzol, korvonal, pulzal, villan
from .naplo import VideotarHiba, jelol
from .stilus import (FEHER, HATTER, KATEGORIA_SZINEK, KEK, MERET, PIROS, SARGA, SAV, SZURKE, ZOLD, betumeret,
                     szoveg)
from .szamolas import Szamlalo, Szamolas, hibas_kor, kerdojel, pipa
from .szogjel import derekszog
from .utem import VERZIO, Horgony, Szora, VideoJelenet
from .venn import Venn2

__all__ = ["Kategoriak", "Keplet", "Indicate", "atir", "eltuntet", "kiemel", "kore_rajzol", "korvonal", "pulzal",
           "villan", "VideotarHiba", "jelol", "FEHER", "HATTER", "KATEGORIA_SZINEK", "KEK", "MERET", "PIROS", "SARGA",
           "SAV", "SZURKE", "ZOLD", "betumeret", "szoveg", "Szamlalo", "Szamolas", "hibas_kor", "kerdojel", "pipa",
           "derekszog",
           "VERZIO", "Horgony", "Szora", "VideoJelenet", "Venn2"]
