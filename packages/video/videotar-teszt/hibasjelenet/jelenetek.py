"""HibasJelenet: minden renderben mérhető K-szabályt (és a K2 négy esetét) pontosan egyszer sért,
lépésenként egyet. Az elvárt kódlista: elvart-kapu.json (a 2. lépés kapujának elfogadási próbája).

    cd videotar-teszt/hibasjelenet && ../../manim.sh -ql --fps 30 --save_sections jelenetek.py HibasJelenet
"""

from manim import (Arrow, Circle, Create, Dot, FadeIn, FadeOut, GrowArrow, MathTex, Square, Text, Transform, VGroup,
                   Write)

from videotar import FEHER, KEK, PIROS, ZOLD, Horgony, Szora, VideoJelenet, jelol, kiemel, kore_rajzol, korvonal


class HibasJelenet(VideoJelenet):
    JELENETEK = ["h01"]
    SZIGORU_TRANSFORM = False   # csak itt: a napló a nyers Transform utáni új számot is lássa (h01-03)

    def jelenet_h01(self):
        pont1 = jelol(Dot([3, 1, 0], radius=0.12), nev="h_pont1")
        kor = jelol(Circle(radius=1.3).set_stroke(KEK, 4).move_to([-4, 0.3, 0]), nev="h_kor")
        pontok = VGroup(*[Dot(p, radius=0.08) for p in ([-4.4, 0.75, 0], [-3.6, 0.75, 0], [-4, 0.3, 0])])
        szam = jelol(MathTex("3", font_size=44).move_to([-4, -0.45, 0]), nev="h_szam")
        negy = MathTex("4", font_size=44).move_to([-4, -0.45, 0])
        het = jelol(MathTex("7", font_size=44).move_to([3, 1, 0]), nev="h_het")
        egyszer = jelol(MathTex(r"1\times", font_size=44).move_to([3, 1, 0]), nev="h_egyszer")
        egy = jelol(MathTex("1", font_size=44).move_to([3, 1, 0]), nev="h_egy")
        tag = jelol(MathTex(r"-\,|A \cap B|", font_size=44).move_to([3, 0.3, 0]), nev="h_tag")
        kilogo = Text("kilógó", font_size=34)
        kilogo = jelol(kilogo.move_to([7.6 - kilogo.width / 2, 0, 0]), nev="h_kilogo")
        felirat = jelol(Text("felirat", font_size=34).move_to([2, 0, 0]), nev="h_felirat", csoport="h_k4")
        nyil = jelol(Arrow([0.5, -1, 0], [3.5, 1, 0], buff=0, color=FEHER), nev="h_nyil", csoport="h_k4")
        apro = jelol(Text("apró", font_size=20).move_to([3, 0, 0]), nev="h_apro")
        kor_kek = jelol(Circle(radius=0.5).set_stroke(KEK, 4).move_to([1.5, 0, 0]), nev="h_kor_kek")
        kor_piros = jelol(Circle(radius=0.5).set_stroke(PIROS, 4).move_to([4, 0, 0]), nev="h_kor_piros")
        pont2 = jelol(Dot([1.5, 0, 0], radius=0.12), nev="h_pont2")
        keret = jelol(Square(side_length=1.0).set_stroke(FEHER, 3).move_to([3.5, 0, 0]), nev="h_keret",
                      vonatkozik=[pont2])
        mondat = jelol(Text("Ez a mondat a képen", font_size=34).move_to([2.5, 0, 0]), nev="h_mondat")
        kulcs = jelol(Circle(radius=0.8).set_stroke(ZOLD, 4).move_to([3, 0, 0]), nev="h_kulcs")
        cimke = jelol(Text("címke", font_size=34).move_to([3, -1.6, 0]), nev="h_cimke", vonatkozik=[kulcs])
        ra_a = jelol(Text("régió", font_size=34).move_to([-2, -2, 0]), nev="h_ra_a", csoport="h_ra",
                     ra="a körvonal mellett")
        ra_b = jelol(Text("felirat", font_size=34).move_to([-1.6, -2, 0]), nev="h_ra_b", csoport="h_ra")
        kis_pont = jelol(Dot([0, 0, 0], radius=0.15), nev="h_kis_pont")
        return [
            # 01 K1: a horgonyos pont a kezi.json −0,8 s-os eltolása miatt 0,9 s-mal a szó előtt
            [Horgony("figyelj", 0.5, lambda: FadeIn(pont1))],
            # 02 rendben: pontok, köréjük a kör, a 3 a „három” szóra
            [(0.8, lambda: [FadeOut(pont1), FadeIn(pontok)]), (0.8, lambda: kore_rajzol(kor, [pontok])),
             Szora(3, 0.5, lambda: FadeIn(szam))],
            # 03 K2 (előbb, a próba s11-03-ja): nyers Transform 3 → 4 a lépés elején, a „négyre” a végén
            [(1.0, lambda: [kiemel(kor, vonatkozik=[pontok]), Transform(szam, negy)])],
            # 04 K2 (lépéshatár): a 7 csak a következő lépésben hangzik el
            [(0.8, lambda: FadeIn(het))],
            # 05 a „hét” itt hangzik el, új kép nincs
            [],
            # 06 K2 (n× -szor/-szer szó nélkül): figyelmeztetés
            [(0.8, lambda: [FadeOut(het), FadeIn(egyszer)])],
            # 07 K2 („egy” lehet névelő): figyelmeztetés
            [(0.8, lambda: [FadeOut(egyszer), FadeIn(egy)])],
            # 08 K9 + K2b (a próba s04-07-je): a képlettag kötetlenül, a „levonjuk” előtt kb. 2 s-mal
            [(1.0, lambda: [FadeOut(egy), korvonal(kor, vonatkozik=[kor])]), (1.2, lambda: Write(tag))],
            # 09 K3: kilóg a képből
            [(0.8, lambda: self.mind_ki() + [FadeIn(kilogo)])],
            # 10 K4: saját kódú nyíl metszi a feliratot
            [(0.8, lambda: [FadeOut(kilogo), FadeIn(felirat), GrowArrow(nyil)])],
            # 11 K5: 20-as betű
            [(0.8, lambda: [FadeOut(felirat), FadeOut(nyil), FadeIn(apro)])],
            # 12 K6b: két felirat nélküli kör, csak a színük más
            [(0.6, lambda: [FadeOut(apro), Create(kor_kek)]), Szora("színben", 0.6, lambda: Create(kor_piros))],
            # 13 K7 (naplóalapú): a keret megjelenése alatt a pont még mozog
            [(0.6, lambda: [FadeOut(kor_kek), FadeOut(kor_piros), FadeIn(pont2)]),
             (1.2, lambda: [pont2.animate.move_to([3.5, 0, 0]), Create(keret)])],
            # 14 K8: a narráció 5 egymást követő szava a képen
            [(0.8, lambda: [FadeOut(pont2), FadeOut(keret), FadeIn(mondat)])],
            # 15 K10: a hang „hat”-ot mond a „kilenc” helyett (szintetikus Whisper-eltérés)
            [(0.6, lambda: FadeOut(mondat))],
            # 16 K12: kulcspont, de a kép a lépés végéig változik
            [(30.0, lambda: Create(kulcs))],
            # 17 K9: vonatkozik-os saját szöveg a lépés közepén, kötetlenül (a vonatkozik csak a kiemelést,
            # a keretet és a nyilat menti fel; a szöveg tartalom)
            [(0.6, lambda: []), (0.6, lambda: FadeIn(cimke))],
            # 18 K4: a ra= szöveg egy másik feliratra csúszik (a ra csak a vonalmetszés alól ment fel)
            [(0.8, lambda: [FadeOut(kulcs), FadeOut(cimke), FadeIn(ra_a), FadeIn(ra_b)])],
            # 19 K13 hiba: a kép kiürül, és a lépés végéig üres marad
            [(0.6, lambda: [FadeOut(ra_a), FadeOut(ra_b)])],
            # 20 K13 figyelmeztetés: csak egy kis pont a fekete képen (a kép 99,9–99,95%-a sötét)
            [(0.6, lambda: FadeIn(kis_pont))],
        ]
