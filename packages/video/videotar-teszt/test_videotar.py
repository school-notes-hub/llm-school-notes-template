"""A videotar tesztjei render nélkül (néhány mp). A render-naplókat, ha megvannak, a séma és a
geometriai önellenőrzés szerint is méri."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from manim import RIGHT, Arrow, Circle, Line, Square, Text, Transform

import geometria
import szintetikus
from videotar import (Kategoriak, Keplet, Szamolas, Szora, Venn2, VideotarHiba, atir, derekszog, jelol, kore_rajzol,
                      naplo, sema)
from videotar.stilus import paletta_hibak
from videotar.utem import Eredmeny, Horgony, VideoJelenet, szo_keres

ITT = Path(__file__).resolve().parent


class Jelenet:
    """A Naplo-nak elég a jelenet objektumlistája: render nélkül így mérhető."""

    def __init__(self, *mobok):
        self.mobjects = list(mobok)


@pytest.fixture(autouse=True)
def tiszta_regiszter():
    naplo.uj_regiszter()
    naplo.AKTIV = None
    yield


def napló(*mobok, szigoru=True):
    n = naplo.Naplo(Jelenet(*mobok), szigoru=szigoru)
    n.lepes_kezd({"id": "x01-01", "kezd_kocka": 0, "veg_kocka": 30})
    return n


# ---------------------------------------------------------------- stílus, K6a, kapcsolók

def test_paletta_szintevesztesben_es_vilagossagban_elvalik():
    assert paletta_hibak() == []
    assert paletta_hibak(("#83C167", "#FC6255"))   # a próba zöld–piros párja deuteranopiában összefolyt


def test_k6a_csak_szin():
    with pytest.raises(VideotarHiba, match="K6a"):
        Kategoriak({"a": ("kor", "#58C4DD", None), "b": ("kor", "#F4D345", None)})
    Kategoriak({"a": ("kor", "#58C4DD", None), "b": ("kor", "#F4D345", "keretes")})


@pytest.mark.parametrize("kw", [{"ra": ""}, {"kivul": "  "}, {"szamellenorzes": ""}])
def test_ures_indoku_kapcsolo_hiba(kw):
    with pytest.raises(VideotarHiba, match="indok"):
        jelol(Circle(), **kw)


def test_nev_foglalt():
    jelol(Circle(), nev="k")
    with pytest.raises(VideotarHiba, match="foglalt"):
        jelol(Square(), nev="k")


# ---------------------------------------------------------------- futásidejű hibák

def test_kore_rajzol_mozgasra_hibat_dob():
    elem = Square(0.3)
    keret = Circle(radius=1)
    n = napló(elem, keret)
    a = kore_rajzol(keret, [elem])
    ctx = n.elott([a])
    elem.shift(RIGHT)                      # ugyanabban a play-ben mozog
    with pytest.raises(VideotarHiba, match="K7"):
        n.utan(ctx, 0, 10, [a], {})


def test_kore_rajzol_allo_elemre_rendben():
    elem, keret = Square(0.3), Circle(radius=1)
    n = napló(elem, keret)
    a = kore_rajzol(keret, [elem])
    n.utan(n.elott([a]), 0, 10, [a], {})
    rek = n.allapot[naplo.adat(keret)["nev"]]
    assert rek["vonatkozik"] == [naplo.adat(elem)["nev"]]


def test_nyers_transform_szovegen_hiba():
    regi = Text("3")
    with pytest.raises(VideotarHiba, match="atir"):
        napló(regi).elott([Transform(regi, Text("4"))])


def test_nyers_transform_utan_a_naplo_az_uj_szoveget_latja():
    regi = jelol(Text("3"), nev="szam")
    n = napló(regi, szigoru=False)
    n.utan({"csere": [], "kore": []}, 0, 1, [], {})
    uj = Text("4")
    a = Transform(regi, uj)
    ctx = n.elott([a])
    regi.become(uj)                        # a Transform vége: a régi objektum az új pontjaival
    n.utan(ctx, 1, 10, [a], {})
    assert n.allapot["szam"]["tartalom"] == "4" and n.allapot["szam"]["szamok"] == [4]
    assert n.akt["megjelenik"][-1]["ok"] == "tartalom"


def test_atir_orokli_a_nevet_es_tartalomvaltozas():
    regi = jelol(Text("1"), nev="szamlalo", ra="szám a régióban")
    jel = Jelenet(regi)
    n = naplo.Naplo(jel)
    n.lepes_kezd({"id": "x01-01", "kezd_kocka": 0, "veg_kocka": 30})
    n.utan({"csere": [], "kore": []}, 0, 1, [], {})
    uj = Text("2")
    atir(regi, uj)
    jel.mobjects = [uj]
    n.utan({"csere": [], "kore": []}, 1, 5, [], {"kotes": ("szora", "kettő")})
    e = n.akt["megjelenik"][-1]
    assert (e["obj"], e["ok"], e["tartalom"], e["kotes"]) == ("szamlalo", "tartalom", "2", "szora")
    assert n.allapot["szamlalo"]["ra"] == "szám a régióban"


# ---------------------------------------------------------------- pillanatkép

def test_doboz_es_vonal_pixelben():
    kor, sz, neg = Circle(radius=1), Line([-1, 0, 0], [1, 0, 0]), Square(2).shift(RIGHT * 3)
    n = napló(kor, sz, neg)
    k = n.pillanatkep()
    rk = k[naplo.adat(kor)["nev"]]
    assert rk["vonal"] == {"t": "kor", "k": [960, 540], "r": 135} and rk["doboz"] == [825, 405, 1095, 675]
    assert k[naplo.adat(sz)["nev"]]["vonal"] == {"t": "szakasz", "p": [[825, 540], [1095, 540]]}
    assert k[naplo.adat(neg)["nev"]]["vonal"]["t"] == "torott"
    assert rk["kat"] == "keret" and k[naplo.adat(sz)["nev"]]["kat"] == "vonal"


def test_esemenyek_megjelenik_mozog_eltunik():
    a, b = jelol(Square(0.3), nev="a"), jelol(Circle(0.2), nev="b")
    jel = Jelenet(a)
    n = naplo.Naplo(jel)
    n.lepes_kezd({"id": "x01-01", "kezd_kocka": 0, "veg_kocka": 30})
    n.utan({"csere": [], "kore": []}, 0, 5, [], {})
    jel.mobjects = [a, b]
    a.shift(RIGHT)
    n.utan({"csere": [], "kore": []}, 5, 10, [], {"kotes": ("horgony", "metszet")})
    jel.mobjects = [b]
    n.utan({"csere": [], "kore": []}, 10, 12, [], {})
    n.lepes_zar()
    lep = n.lepesek[0]
    assert [(e["obj"], e["kocka"], e["kotes"]) for e in lep["megjelenik"]] == [("a", 0, None), ("b", 5, "horgony")]
    assert lep["mozog"] == [{"obj": "a", "tol": 5, "ig": 10}]
    assert lep["eltunik"] == [{"obj": "a", "kocka": 10, "veg_kocka": 12}]
    assert [o["obj"] for o in lep["allapot"]["vege"]] == ["b"]


def test_jeloletlen_objektum_automatikus_nevet_kap_es_csoportot():
    from manim import VGroup
    g = VGroup(Arrow([0, 0, 0], [1, 0, 0]), Text("x"))
    k = napló(g).pillanatkep()
    assert sorted(k) == ["Arrow#1", "Text#3 „x”"]
    assert {r["csoport"] for r in k.values()} == {"VGroup#2"} and k["Arrow#1"]["kat"] == "nyil"


@pytest.mark.parametrize("s,ertek,szor", [
    ("19", [19], []), ("- 6", [6], []), ("-3", [-3], []), ("x=-3", [-3], []), ("5-3", [5, 3], []),
    (r"1\times", [1], [1]), ("2,5", [2.5], []), (r"\{1, 2, 3\}", [1, 2, 3], []), (r"|A \cup B|", [], [])])
def test_szamok(s, ertek, szor):
    assert naplo.szamok(s) == (ertek, szor)


# ---------------------------------------------------------------- ütemező (render nélkül)

SZAVAK = [{"szo": w, "ertek": e, "kocka": k, "szo_s": k / 30, "forras": "whisper"} for w, e, k in
          [("Mínusz", None, 3), ("négy", 4, 9), ("az", None, 15), ("négy", 4, 20), ("uniója", None, 26)]]


def test_szo_keres():
    assert szo_keres(SZAVAK, 4, 2, "s")["kocka"] == 20
    assert szo_keres(SZAVAK, 4, "utolso", "s")["kocka"] == 20
    assert szo_keres(SZAVAK, "unió", 1, "s")["kocka"] == 26       # legalább 4 betűs tő
    assert szo_keres(SZAVAK, "mínusz", 1, "s")["kocka"] == 3
    with pytest.raises(VideotarHiba, match="3. előfordulása"):
        szo_keres(SZAVAK, 4, 3, "s")


def _terv(text, horgonyok=None):
    return {"id": "s01-01", "kezd_kocka": 0, "veg_kocka": 40, "anim_kocka": 0, "text": text,
            "horgonyok": horgonyok or {}, "szavak": SZAVAK}


def test_kotesek_sorrendje_es_horgonyszerzodes():
    fv = lambda: []  # noqa: E731
    ki = VideoJelenet._kotesek(None, _terv("Mínusz négy, az négy, uniója."),
                               [(0.5, fv), Szora(4, 0.5, fv), Szora("unió", 0.5, fv)])
    assert ki == {1: ("szora", "négy", 9), 2: ("szora", "uniója", 26)}
    with pytest.raises(VideotarHiba, match="nem az előző kötés"):
        VideoJelenet._kotesek(None, _terv("x"), [Szora("unió", 0.5, fv), Szora(4, 0.5, fv)])
    with pytest.raises(VideotarHiba, match="horgonyszerződés"):
        VideoJelenet._kotesek(None, _terv("Az {unió}.", {"unió": 26}), [(0.5, fv)])
    ki = VideoJelenet._kotesek(None, _terv("Mínusz {négy}", {"négy": 9}), [Eredmeny(4, 0.5, fv)])
    assert ki == {0: ("horgony", "négy", 9)}
    with pytest.raises(VideotarHiba, match="horgonyszó értéke"):
        VideoJelenet._kotesek(None, _terv("Mínusz {négy}", {"négy": 9}), [Eredmeny(5, 0.5, fv)])
    assert VideoJelenet._kotesek(None, _terv("x"), [Eredmeny(4, 0.5, fv)]) == {0: ("szora", "négy", 20)}
    assert VideoJelenet._kotesek(None, _terv("A {négy}", {"négy": 9}), [Horgony("négy", 0.5, fv)]) == \
        {0: ("horgony", "négy", 9)}


# ---------------------------------------------------------------- elemek

def test_keplet_tagonkent_kotelezo_szo():
    with pytest.raises(VideotarHiba, match="K2b"):
        Keplet([("|A|",)])
    k = Keplet([(r"|A \cup B|", "unió"), ("=", None), ("|A|", ("A", 2))], nev="k")
    lep = k.lepesek()
    assert isinstance(lep[0], Szora) and lep[0].mit == "unió" and isinstance(lep[1], tuple)
    assert (lep[2].mit, lep[2].hanyadik) == ("A", 2)
    assert naplo.adat(k[0])["szo"] == "unió" and naplo.adat(k[0])["csoport"] == "k"


def test_szamolas_lepesei():
    lep = Szamolas(["8", "- 3", "- 3"], "2", nev="sz").lepesek()
    assert [(e.mit, e.hanyadik) for e in lep[:3]] == [(8, 1), (3, 1), (3, 2)]
    assert isinstance(lep[3], Eredmeny) and lep[3].mit == 2


def test_venn2_regiok_es_helyek():
    v = Venn2(nev="v")
    for k in ("a-b", "ab", "b-a", "kivul"):
        assert v.bent(k, v.regio_pont(k), margo=0.0)
        h = v.helyek(k, 3)
        assert all(v.bent(k, p) for p in h) and [list(p) for p in h] == [list(p) for p in v.helyek(k, 3)]
    for kulcs in (("a",), ("aub",), ("a-b", "kivul"), ("ab",)):
        assert len(v.regio(*kulcs).points) > 0
    with pytest.raises(VideotarHiba, match="ismeretlen régió"):
        v.regio("c")
    assert naplo.adat(v.kor["a"])["cimke"] is v.betu["a"]


# ---------------------------------------------------------------- szintetikus bemenet, séma, render-naplók

def test_szintetikus_bemenet_determinisztikus_es_semahu(tmp_path):
    for d in ("tesztjelenet", "hibasjelenet"):
        for n in ("narracio.json", "kezi.json"):
            if (ITT / d / n).exists():
                shutil.copy(ITT / d / n, tmp_path / n)
        szintetikus.main(tmp_path)
        elso = {n: (tmp_path / n).read_bytes() for n in ("hangido.json", "szavak.json", "idoterv.json")}
        szintetikus.main(tmp_path)
        assert elso == {n: (tmp_path / n).read_bytes() for n in elso}
        assert sema.hibak(json.loads(elso["idoterv.json"]), "idoterv") == []
        assert sema.hibak(json.loads(elso["szavak.json"]), "szavak") == []
        (tmp_path / "kezi.json").unlink(missing_ok=True)


def test_szamnev():
    assert [szintetikus.szamnev(w) for w in ("tizenkét", "négyre", "hármat", "kétszer", "nulláról", "egyiket",
                                              "háromszöget", "egyenlő", "tizenegyet")] == \
        [12, 4, 3, 2, 0, None, None, None, 11]


def test_elvart_kodlista():
    e = json.loads((ITT / "hibasjelenet" / "elvart-kapu.json").read_text(encoding="utf-8"))
    kulcsok = [(x["lepes"], x["kod"], x["obj"] or "") for x in e["leletek"]]
    from kapu import kodkulcs                    # a kapu sorrendje: lépés, kód a KOD_SOR szerint (K12 < K13), obj.
    assert kulcsok == sorted(kulcsok, key=lambda k: (k[0], kodkulcs(k[1]), k[2])) and \
        len({k[:2] for k in kulcsok}) == len(kulcsok)
    kodok = {x["kod"] for x in e["leletek"]} | {x["kod"] for x in e["renderen_kivul"]}
    assert kodok == {"K1", "K2", "K2b", "K3", "K4", "K5", "K6a", "K6b", "K7", "K8", "K8a", "K9", "K10", "K11", "K12", "K13"}
    narr = json.loads((ITT / "hibasjelenet" / "narracio.json").read_text(encoding="utf-8"))
    lepesek = {f"{j['id']}-{i:02d}" for j in narr for i in range(1, len(j["lepesek"]) + 1)}
    assert {x["lepes"] for x in e["leletek"]} <= lepesek


@pytest.mark.parametrize("d", ["tesztjelenet", "hibasjelenet"])
def test_render_naplo_semahu_es_geometria(d):
    ut = ITT / d / "render_naplo.json"
    if not ut.exists():
        pytest.skip("nincs render (render.sh)")
    adat = json.loads(ut.read_text(encoding="utf-8"))
    assert sema.hibak(adat) == []
    vart = [] if d == "tesztjelenet" else \
        [("h01-09", "K3", "h_kilogo"), ("h01-10", "K4", "h_felirat"), ("h01-11", "K5", "h_apro")]
    assert geometria.leletek(adat) == vart


def test_play_csak_az_utemezon_at():
    import types
    with pytest.raises(VideotarHiba, match="közvetlenül"):
        VideoJelenet.play(types.SimpleNamespace(_utemezo=False))
    with pytest.raises(VideotarHiba, match="közvetlenül"):
        VideoJelenet.wait(types.SimpleNamespace(_utemezo=False))


# ---------------------------------------------------------------- derékszögjel (magyar jelölés)

def _forgat(v, fok):
    import numpy as np
    t = np.radians(fok)
    return np.array([np.cos(t) * v[0] - np.sin(t) * v[1], np.sin(t) * v[0] + np.cos(t) * v[1], 0.0])


@pytest.mark.parametrize("u1,u2", [
    ((1, 0, 0), (0, 1, 0)),             # tengelyes
    ((0, 1, 0), (1, 0, 0)),             # fordított sorrend
    ((-1, 0, 0), (0, -1, 0)),           # harmadik síknegyed
    ((1, 1, 0), (-1, 1, 0)),            # ferde (45°)
    (tuple(_forgat((1, 0, 0), 37)), tuple(_forgat((0, 1, 0), 37) * 2.5)),     # ferde, eltérő hosszú szárvektorok
    (tuple(_forgat((0, 1, 0), 200)), tuple(_forgat((1, 0, 0), 200))),        # ferde, fordított sorrend
    ((3, 4), (-4, 3)),                  # 2D-s vektorok
])
def test_derekszog_iv_a_belso_90_fokos_tartomanyban_pont_a_szogfelezon(u1, u2):
    import numpy as np
    c, r = np.array([1.0, -0.5, 0.0]), 0.4
    m = derekszog(c, u1, u2, r=r, nev="dsz")
    iv, pont = m.submobjects
    a = np.array(u1 + (0,) * (3 - len(u1)), dtype=float)[:3]
    b = np.array(u2 + (0,) * (3 - len(u2)), dtype=float)[:3]
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    for p in iv.points:                                         # az ív minden pontja a két szár között, r-en
        d = p - c
        assert d @ a > -1e-6 and d @ b > -1e-6
        assert abs(np.linalg.norm(d) - r) < 0.01 * r
    vegek = [iv.get_start() - c, iv.get_end() - c]              # az ív a két száron kezdődik és végződik
    assert any(np.allclose(v, a * r, atol=1e-6) for v in vegek) and any(np.allclose(v, b * r, atol=1e-6) for v in vegek)
    d = pont.get_center() - c                                   # a pont a szögfelezőn, a sugár felénél
    f = (a + b) / np.linalg.norm(a + b)
    assert np.allclose(d, f * r * 0.5, atol=1e-6) and d @ a > 0 and d @ b > 0


def test_derekszog_regisztralt_jelolo_es_hibak():
    from manim import UP
    m = derekszog([0, 0, 0], RIGHT, UP, nev="dsz", csoport="abra")
    k = napló(m).pillanatkep()
    assert list(k) == ["dsz"] and k["dsz"]["kat"] == "jelolo" and k["dsz"]["alairas"]["osztaly"] == "derekszog"
    assert k["dsz"]["csoport"] == "abra"
    with pytest.raises(VideotarHiba, match="nem derékszöget"):
        derekszog([0, 0, 0], RIGHT, [1, 1, 0])                 # 45°: derékszögjel nem kerülhet rá
    with pytest.raises(VideotarHiba, match="nullvektor"):
        derekszog([0, 0, 0], RIGHT, [0, 0, 0])
    with pytest.raises(VideotarHiba, match="nem véges"):
        derekszog([0, 0, 0], RIGHT, [float("nan"), 1, 0])      # NaN-irány: nem néma szemét-ív
    with pytest.raises(VideotarHiba, match="nem véges"):
        derekszog([0, float("inf"), 0], RIGHT, UP)
    for r in (0, -0.3, float("nan")):
        with pytest.raises(VideotarHiba, match="sugár"):
            derekszog([0, 0, 0], RIGHT, UP, r=r)
