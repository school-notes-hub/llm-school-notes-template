"""Nyitó- és zárókép: a lánc rendereli a --vegleges összefésülés előtt, nem az író kódja (minden videóban egyforma).

Bemenet környezeti változóban: NZ_CIM (téma), NZ_TANTARGY (tantárgy), NZ_UTOLSO (a fő videó utolsó kockája, png).
A hosszakat a lanc/nyitozaro.py adja (NZ_NYITO_S, NZ_ZARO_S); a kapu ezt a két részt nem látja (K8, K11).
"""
import os

from manim import DOWN, FadeIn, FadeOut, ImageMobject, Scene, Text, VGroup, config

from videotar.stilus import FEHER, MERET, SZURKE

CIM, TANTARGY = os.environ["NZ_CIM"], os.environ["NZ_TANTARGY"]
NYITO_S, ZARO_S = float(os.environ["NZ_NYITO_S"]), float(os.environ["NZ_ZARO_S"])


def cimkep() -> VGroup:
    """A tantárgy kicsiben, alatta a téma címe nagyban; a hosszú cím két sorba törik, és a képbe fér."""
    cim = Text(CIM, font_size=MERET["XL"], color=FEHER)
    szelesseg = config.frame_width * 0.86
    if cim.width > szelesseg and " " in CIM:
        szavak = CIM.split()
        i = min(range(1, len(szavak)), key=lambda k: abs(len(" ".join(szavak[:k])) - len(" ".join(szavak[k:]))))
        cim = Text(" ".join(szavak[:i]) + "\n" + " ".join(szavak[i:]), font_size=MERET["XL"], color=FEHER,
                   line_spacing=1.1)
    if cim.width > szelesseg:
        cim.scale_to_fit_width(szelesseg)
    targy = Text(TANTARGY, font_size=MERET["M"], color=SZURKE)
    return VGroup(targy, cim).arrange(DOWN, buff=0.45).move_to([0, 0, 0])


class Nyito(Scene):
    def construct(self):
        k = cimkep()
        self.play(FadeIn(k), run_time=0.6)
        self.wait(NYITO_S - 1.1)
        self.play(FadeOut(k), run_time=0.5)


class Zaro(Scene):
    def construct(self):
        kep = ImageMobject(os.environ["NZ_UTOLSO"]).set_height(config.frame_height)
        self.add(kep)
        self.play(FadeOut(kep), run_time=1.0)
        k = cimkep()
        self.play(FadeIn(k), run_time=0.8)
        self.wait(ZARO_S - 1.8 - 0.7)
        self.play(FadeOut(k), run_time=0.7)
