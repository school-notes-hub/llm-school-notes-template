"""A második kapukör szintetikus regressziói; nincs tanulói szöveg vagy bemenet."""
import math

import pytest

from test_kapu import _l, _mu, _o, _k4
import kapu


def munka(lepesek):
    mu = _mu(lepesek)
    mu.tmap = {l["id"]: {"kezd_kocka": i * 180, "veg_kocka": (i + 1) * 180,
                          "szavak": [{"szo": "előbb", "szo_s": i * 6 + .2, "forras": "whisper"},
                                     {"szo": "utóbb", "szo_s": i * 6 + 4, "forras": "whisper"}]}
               for i, l in enumerate(lepesek)}
    mu.hmap, mu.kivetel = {}, {}
    return mu


def megj(nev, kat="keplet", **x):
    return {"obj": nev, "kat": kat, "csoport": nev, "kocka": 186, "veg_kocka": 210,
            "kotes": None, "ok": "uj", **x}


@pytest.mark.parametrize("ok", ["uj", "tartalom", "atlatszosag"])
def test_uj_keplet_elfogadhato_de_megkulonboztetheto(ok):
    """A teljes új képlet akkor is új, ha egyes jelei korábban már látszottak."""
    a = _o("tag", "keplet", [200, 200, 260, 240], forras="sajat", tartalom="u")
    b = _o("uj", "keplet", [200, 200, 340, 240], forras="sajat", tartalom="(u;v)")
    mu = munka([_l("s01-01", [a], megjelenik=[megj("tag", kocka=0, tartalom="u")]),
                _l("s01-02", [b], megjelenik=[megj("uj", ok=ok, tartalom="(u;v)")])])
    mu.kivetel = {"elfogad": [{"lepes": "s01-02", "kod": "K2b", "obj": "uj", "indok": "ismert tagok"}]}
    ls = kapu.k2(mu)
    assert kapu.kivetelek(mu, ls) == []
    x = next(x for x in ls if x["lepes"] == "s01-02")
    assert x.get("uj_keplet") and x["elfogadva"] == "ismert tagok"
    # Az azonos teljes képlet visszatérése és a nyitó színpad továbbra is elbírálható.
    mu.lepesek[0]["megjelenik"][0]["tartalom"] = "(u;v)"
    ls = kapu.k2(mu)
    assert not kapu.kivetelek(mu, ls)
    assert next(x for x in ls if x["lepes"] == "s01-02").get("elfogadva")


def test_uj_keplet_szohoz_kotve_rendben():
    o = _o("uj", "keplet", [200, 200, 340, 240], forras="sajat")
    e = megj("uj", tartalom="(u;v)", kotes="szora", kotes_szo="előbb", szo="előbb")
    mu = munka([_l("s01-01", []), _l("s01-02", [o], megjelenik=[e])])
    assert kapu.k2(mu) == []
    e["szo"] = "hiányzó"
    assert kapu.k2(mu) == []  # az explicit kötés a régi szo előtt áll


def test_szogiv_ra_nem_menti_fel_az_origocimke_metszeset():
    p = [[round(440 + 61 * math.cos(t)), round(540 - 61 * math.sin(t))]
         for t in [i * 1.5 * math.pi / 32 for i in range(33)]]
    iv = _o("mozgo_abra", "alak", [379, 479, 501, 601], {"t": "torott", "p": [p]},
            csoport="szinpad", ra="a pont a körön van")
    jel = _o("origocimke", "keplet", [394, 564, 422, 592], csoport="szinpad")
    assert any(x[1] == "origocimke" for x in _k4([_l("s01-02", [iv, jel])]))
    iv["vonatkozik"] = ["origocimke"]
    assert _k4([_l("s01-02", [iv, jel])]) == []


def test_regi_alahuzas_es_egysegtorles_csak_egyertelmu_sajat_cimke_mellett_mentes():
    jel = _o("jel", "keplet", [400, 300, 600, 340])
    for y in (320, 346):
        vonal = _o("kiemelo", "vonal", [510, y, 550, y], {"t": "szakasz", "p": [[510, y], [550, y]]}, ra="saját jelölés")
        assert _k4([_l("s01-02", [vonal, jel])]) == []
        # A cél nem egyértelmű: a ra nem rejthet el egymásra került feliratokat.
        idegen = _o("idegen", "keplet", [500, 310, 565, 350])
        assert _k4([_l("s01-02", [vonal, jel, idegen])])


def test_kotetlen_mozgas_a_masodik_tagmondat_ele_elofuthat():
    a = _o("pont", "jelolo", [200, 200, 220, 220])
    b = dict(a, doboz=[500, 200, 520, 220])
    mozog = [{"obj": "pont", "tol": 186, "ig": 225}]
    elem = {"kezd_kocka": 186, "veg_kocka": 225, "tipus": "Transform", "celok": ["pont"]}
    mu = munka([_l("s01-01", [a]), _l("s01-02", [b], mozog=mozog, elemek=[elem])])
    ls = kapu.k1_kotetlen(mu)
    assert ls == []
    assert not kapu.szinkron_adatok(mu)[0]["kotes_szo"]
    b["szo"] = "utóbb"
    assert kapu.k1_kotetlen(mu) == []  # a megjelenés régi szava nem mozgáskötés
    assert not kapu.szinkron_adatok(mu)[0]["kotes_szo"]
    elem["szora"] = "utóbb"
    assert "előtt" in kapu.k1_kotetlen(mu)[0]["uzenet"]
    mozog[0].update(tol=297, ig=336)
    elem.update(kezd_kocka=297, veg_kocka=336, szora="utóbb")
    assert kapu.k1_kotetlen(mu) == []


def test_egyetlen_kotetlen_rajzot_nem_kot_meg_a_kesobbi_cimke():
    abra = _o("szerkesztes", "alak", [300, 300, 600, 600])
    cimke = _o("jel", "keplet", [400, 200, 450, 240])
    es = [megj("szerkesztes", "alak"), megj("jel", kocka=297, kotes="szora", kotes_szo="utóbb")]
    mu = munka([_l("s01-01", []), _l("s01-02", [abra, cimke], megjelenik=es)])
    assert kapu.k9(mu) == []  # a régi darabszám-szabály nem találta
    assert kapu.k1_kotetlen(mu) == []
    assert [x["obj"] for x in kapu.szinkron_adatok(mu) if not x["kotes_szo"]] == ["szerkesztes"]
    es[0].update(kocka=297, kotes="szora", kotes_szo="utóbb")
    assert kapu.k1_kotetlen(mu) == []
    # A jelenet nyitó színpada csendben előre állhat.
    mu = munka([_l("s01-01", [abra], megjelenik=[megj("szerkesztes", "alak")])])
    assert kapu.k1_kotetlen(mu) == []


def sugar(fok, paros=False):
    c = [500, 540]
    q = [round(c[0] + 236 * math.cos(math.radians(fok))), round(c[1] - 236 * math.sin(math.radians(fok)))]
    paths = [[c, q]]
    # A szögív is látszik; önmagában nem bizonyítja, hogy a sugár elfordult.
    if fok:
        paths.append([[round(c[0] + 65 * math.cos(math.radians(fok * i / 80))),
                       round(c[1] - 65 * math.sin(math.radians(fok * i / 80)))] for i in range(81)])
    if paros:
        for x, y in (q, [1200, q[1]]):
            paths.append([[x - 8, y - 8], [x + 8, y - 8], [x + 8, y + 8], [x - 8, y + 8], [x - 8, y - 8]])
    pts = [p for line in paths for p in line]
    box = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    return _o("mozgo", "alak", box, {"t": "torott", "p": paths})


@pytest.mark.parametrize("fok,paros,dt,gyors", [(35, True, .3, True), (90, True, .3, True),
                                             (90, True, 1.5, False), (120, False, 1, False),
                                             (90, False, .3, True)])
def test_forgatas_sebessege(fok, paros, dt, gyors):
    mu = munka([_l("s01-01", [sugar(0, paros)]), _l("s01-02", [sugar(fok, paros)],
                mozog=[{"obj": "mozgo", "tol": 180, "ig": 180 + round(dt * 30)}])])
    meres = kapu.mozgasi_meresek(mu)[0]
    assert meres["fok"] == pytest.approx(fok, abs=1)
    assert meres["kuszob_fok_s"] == (60 if paros else 120)
    assert bool(kapu.k14(mu)) == gyors


@pytest.mark.parametrize("dt,gyors", [(.3, True), (1, False)])
def test_eltolas_sebessege(dt, gyors):
    a = _o("test", "alak", [300, 300, 360, 360])
    b = dict(a, doboz=[780, 300, 840, 360])
    mu = munka([_l("s01-01", [a]), _l("s01-02", [b], mozog=[{"obj": "test", "tol": 180, "ig": 180 + round(dt * 30)}])])
    assert bool(kapu.k14(mu)) == gyors
    assert kapu.mozgasi_meresek(mu)[0]["ut_px"] == 480


def test_tobb_mozgas_koztes_allapot_nelkul_nem_lesz_mert_nullasebesseg():
    a, b = sugar(0), sugar(90)
    mu = munka([_l("s01-01", [a]), _l("s01-02", [b], mozog=[{"obj": "mozgo", "tol": 180, "ig": 189},
                                                         {"obj": "mozgo", "tol": 210, "ig": 219}])])
    assert all(x.get("nem_mert") for x in kapu.mozgasi_meresek(mu))
    assert kapu.k14(mu) == []


def test_koriv_nullan_atfordulasa_nem_hamis_hosszu_ut():
    mu = munka([_l("s01-01", [sugar(330)]), _l("s01-02", [sugar(30)],
                mozog=[{"obj": "mozgo", "tol": 180, "ig": 210}])])
    assert kapu.mozgasi_meresek(mu)[0]["fok"] == pytest.approx(60, abs=1)
    assert kapu.k14(mu) == []


def test_teljes_iv_torlese_nem_bizonyit_gyors_teljes_fordulatot():
    mu = munka([_l("s01-01", [sugar(360)]), _l("s01-02", [sugar(0)],
                mozog=[{"obj": "mozgo", "tol": 180, "ig": 189}])])
    assert not any("gyors mozgás" in x["uzenet"] for x in kapu.k14(mu))


def test_alakvaltozas_nem_eltolas_es_kiemeles_nem_gyors_mozgas():
    a = _o("test", "alak", [300, 300, 360, 360])
    b = dict(a, doboz=[300, 300, 840, 360])
    mu = munka([_l("s01-01", [a]), _l("s01-02", [b], mozog=[{"obj": "test", "tol": 180, "ig": 189}])])
    assert kapu.mozgasi_meresek(mu)[0].get("nem_mert")
    assert kapu.k14(mu) == []
    a["kat"] = b["kat"] = "kiemeles"
    assert kapu.k14(mu) == []


def test_csoport_hianyos_palyaja_nem_fedi_el_a_mert_gyors_tagot():
    a = _o("a", "alak", [200, 200, 240, 240], csoport="abra")
    b = _o("b", "alak", [300, 300, 340, 340], csoport="abra")
    mu = munka([_l("s01-01", [a, b]),
                _l("s01-02", [dict(a, doboz=[200, 200, 800, 240]), dict(b, doboz=[900, 300, 940, 340])],
                   mozog=[{"obj": n, "tol": 180, "ig": 189} for n in ("a", "b")])])
    ls = kapu.k14(mu)
    assert len(ls) == 1 and ls[0]["obj"] == "b" and "gyors mozgás" in ls[0]["uzenet"]
