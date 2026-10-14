"""TesztJelenet: a halmazos elemtár minden eleme és egy saját kódú rész (nyers Arrow, Text, Line,
jelol-lal és jelölés nélkül). A kapunak zöldnek kell lennie.

    cd videotar-teszt/tesztjelenet && ../../manim.sh -ql --fps 30 --save_sections jelenetek.py TesztJelenet
"""

from manim import DOWN, DL, DR, Arrow, FadeIn, FadeOut, Create, Line, MathTex, SurroundingRectangle, Text, VGroup

from videotar import (FEHER, KEK, MERET, SARGA, SZURKE, ZOLD, Horgony, Kategoriak, Keplet, Szamlalo, Szamolas,
                      Szora, Venn2, VideoJelenet, atir, hibas_kor, jelol, kerdojel, pulzal, villan)

TANULOK = ["sport"] * 4 + ["mindketto"] * 2 + ["zene"] * 3 + ["semmi"] * 3
REGIO = {"sport": "a-b", "mindketto": "ab", "zene": "b-a", "semmi": "kivul"}


class TesztJelenet(VideoJelenet):
    JELENETEK = ["t01", "t02", "t03"]

    def tanulok(self, *katok):
        return [t for t, k in zip(self.tan, TANULOK) if k in katok]

    def jelenet_t01(self):
        self.kat = Kategoriak({"tanulo": ("kor", SZURKE, None), "sport": ("haromszog", KEK, None),
                               "zene": ("negyzet", SARGA, None), "mindketto": ("haromszog", ZOLD, "keretes")})
        self.tan = [self.kat.elem("tanulo", [-2.5 + (i % 6), 0.4 - 0.8 * (i // 6), 0], nev=f"tanulo_{i + 1:02d}",
                                  csoport="tanulok") for i in range(12)]
        self.szl = Szamlalo(0, hely=[5.0, 2.8, 0], nev="szamlalo")
        return [
            [(0.8, lambda: FadeIn(VGroup(*self.tan))), Szora("nulláról", 0.5, lambda: FadeIn(self.szl.mob))],
            [Szora(12, 0.7, lambda: self.szl.fut(12))],
            [(0.9, lambda: [self.kat.atalakit(t, "sport") for t in self.tanulok("sport", "mindketto")])],
            [(0.9, lambda: [self.kat.atalakit(t, "zene") for t in self.tanulok("zene")])],
            [(0.9, lambda: [self.kat.atalakit(t, "mindketto") for t in self.tanulok("mindketto")])],
        ]

    def jelenet_t02(self):
        v = self.venn = Venn2(("A", "B"), cimkek=("sport", "zene"), kozep=[0, -0.4, 0], r=1.6, nev="venn")
        regiok = [REGIO[k] for k in TANULOK]
        self.szam = {"ab": v.regio_szam("ab", 2, nev="szam_ab", ra="szám a metszetben, a jelölők alatt"),
                     "a-b": v.regio_szam("a-b", 4, nev="szam_a-b"), "b-a": v.regio_szam("b-a", 3, nev="szam_b-a"),
                     "kivul": v.regio_szam("kivul", 3, nev="szam_kivul")}
        # saját kód: jelölt nyíl, jelöletlen felirat és aláhúzás
        nyil = jelol(Arrow([3.6, -3.0, 0], [0.12, -1.42, 0], buff=0, stroke_width=4, color=FEHER), nev="nyil",
                     vonatkozik=self.tanulok("mindketto"))
        cim = Text("metszet", font_size=MERET["M"]).move_to([4.75, -3.0, 0])
        alahuz = Line(cim.get_corner(DL) + DOWN * 0.1, cim.get_corner(DR) + DOWN * 0.1, stroke_width=3)
        cimke = VGroup(cim, alahuz)
        return [
            [(1.4, lambda: v.elemek_helyre(self.tan, regiok) + [FadeOut(self.szl.mob)])],
            [(0.9, lambda: v.kor_rajzol("a", self.tanulok("sport", "mindketto")))],
            [(0.9, lambda: v.kor_rajzol("b", self.tanulok("zene", "mindketto")))],
            [(0.9, lambda: v.alaphalmaz_keret(self.tan + [v.kor["a"], v.kor["b"]]))],
            [Horgony("metszet", 0.6, lambda: v.regio_kiemel("ab", vonatkozik=self.tanulok("mindketto")), tart=True)],
            [(0.7, lambda: Create(nyil)), Szora("metszetben", 0.6, lambda: FadeIn(cimke)),
             Szora(2, 0.5, lambda: FadeIn(self.szam["ab"]))],
            [(0.6, lambda: v.regio_kiemel("a-b", vonatkozik=self.tanulok("sport"))),
             Szora(4, 0.5, lambda: FadeIn(self.szam["a-b"]))],
            [(0.6, lambda: v.regio_kiemel("b-a", vonatkozik=self.tanulok("zene"))),
             Szora(3, 0.5, lambda: FadeIn(self.szam["b-a"]))],
            [(0.6, lambda: v.regio_kiemel("kivul", vonatkozik=self.tanulok("semmi"))),
             Szora(3, 0.5, lambda: FadeIn(self.szam["kivul"]))],
            [(0.8, lambda: v.regio_kiemel("a-b", "kivul", vonatkozik=self.tanulok("sport", "semmi")))],
            [(0.6, lambda: v.regio_kiemel("aub", vonatkozik=self.tanulok("sport", "zene", "mindketto"))),
             Szora("kétszer", 0.6, self._ketszer)],
        ]

    def _ketszer(self):
        uj = self.venn.hanyszor("ab", 2)
        a = atir(self.szam["ab"], uj)
        self.szam["ab"] = uj
        return a

    def jelenet_t03(self):
        kerdo = kerdojel([0, 2.6, 0], nev="kerdojel")
        k = Keplet([(r"|A \cup B|", "unió"), ("=", "egyenlő"), ("|A|", ("A", 1)), ("+", "plusz"), ("|B|", "B"),
                    ("-", "mínusz"), (r"|A \cap B|", "metszet")], hely=[0, 1.2, 0], nev="kepl")
        sz = Szamolas(["6", "+ 5", "- 2"], "9", hely=[0, -0.4, 0], nev="szamolas", pipa=True)
        tizenegy = jelol(MathTex("11", font_size=MERET["L"]).move_to([0, -2.2, 0]), nev="szam_11")
        hk = hibas_kor(tizenegy, nev="hibas")
        return [
            [(0.8, lambda: self.mind_ki() + [FadeIn(kerdo)])],
            [(0.3, lambda: FadeOut(kerdo)), *k.lepesek(rt=0.4)],
            sz.lepesek(rt=0.5),
            [(0.8, lambda: pulzal(sz.mob[-1]) + [villan(SurroundingRectangle(sz.mob[-1], buff=0.15))])],
            [Szora(11, 0.5, lambda: FadeIn(tizenegy)), Szora("hibás", 0.6, lambda: Create(hk))],
        ]
