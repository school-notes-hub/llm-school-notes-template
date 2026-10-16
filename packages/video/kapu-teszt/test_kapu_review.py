"""Az Opus review 1–9. leletének szintetikus regressziói."""
import copy
import math

import pytest

from test_kapu import _l, _o, TESZT
from test_kapu_masodik import munka, megj, sugar
import kapu
import tabla


def tabla_munka(mu, tmp_path):
    mu.m, mu.naplo, mu.minoseg = tmp_path, {"jelenet": "Proba"}, "480p30"
    mu.terv = {"kocka_osszes": len(mu.lepesek) * 180}
    mu.kezi = {}
    mu.ids = list(mu.tmap)
    mu.narr_lepes = {sid: {"jelenet": "Proba", "text": "Előbb nézd, utóbb követjük."} for sid in mu.ids}
    mu.tl = [{"id": sid, **t} for sid, t in mu.tmap.items()]
    mu.lmap = {l["id"]: l for l in mu.lepesek}
    for l, t in zip(mu.lepesek, mu.tl):
        l.update(kezd_kocka=t["kezd_kocka"], veg_kocka=t["veg_kocka"], szinvaltas=[], kapcsolok=[], utolso_valtozas=None)
    return mu


def tabla_k(leletek, **x):
    return {"jelenet": "Proba", "zold": True, "szamok": {"hiba": 0, "figy": len(leletek)},
            "allapot": "", "leletek": leletek, "ervenytelen_kivetelek": [], "jelzesek": [], **x}


def test_1_kotetlen_valtozas_csak_a_lepessorban(tmp_path):
    a = _o("rajz", "alak", [100, 100, 200, 200])
    mu = tabla_munka(munka([_l("s01-01", []), _l("s01-02", [a], megjelenik=[megj("rajz", "alak")])]), tmp_path)
    assert kapu.k1_kotetlen(mu) == []
    adatok = [e for e in kapu.szinkron_adatok(mu) if not e["kotes_szo"]]
    tabla.ir(mu, tabla_k([], kotetlen_valtozasok=adatok))
    szoveg = (tmp_path / "tabla.txt").read_text()
    sor = next(s for s in szoveg.splitlines() if s.startswith("s01-02 "))
    assert "kötetlen: rajz +0,2 (megjelenés)" in sor
    assert "FIGY K1" not in szoveg


@pytest.mark.parametrize("tipus", ["szora", "horgony"])
@pytest.mark.parametrize("esemeny", ["megjelenés", "mozgás"])
def test_2_szakaszkotes_oroklodik_de_csak_elore_es_lepesen_belul(tipus, esemeny):
    a = _o("alak", "alak", [100, 100, 200, 200])
    elem = {"kezd_kocka": 186, "veg_kocka": 201, tipus: "előbb"}
    kov = {"kezd_kocka": 240, "veg_kocka": 255}
    e = megj("alak", "alak", kocka=240, veg_kocka=255)
    args = {"megjelenik": [e]} if esemeny == "megjelenés" else {"mozog": [{"obj": "alak", "tol": 240, "ig": 255}]}
    mu = munka([_l("s01-01", [a]), _l("s01-02", [a], elemek=[elem, kov], **args)])
    # A második play több mint 1 s-mal később indul: ettől még helyes a szakaszkötés.
    assert kapu.k1_kotetlen(mu) == []
    adat = kapu.szinkron_adatok(mu)[0]
    assert (adat["kotes_szo"], adat["kotes_kocka"]) == ("előbb", 186)
    # Az újabb kötés vált, és annak tényleges eltérését mérjük.
    kov[tipus] = "utóbb"
    assert "előtt" in kapu.k1_kotetlen(mu)[0]["uzenet"]
    # A jövőbeli kötést és az előző lépés kötését nem lehet örökölni.
    mu.lepesek[1]["elemek"] = [{"kezd_kocka": 270, "veg_kocka": 280, tipus: "utóbb"}]
    assert not kapu.szinkron_adatok(mu)[0]["kotes_szo"]
    mu.lepesek.append(_l("s01-03", [a], **args))
    assert not kapu.szinkron_adatok(mu)[-1]["kotes_szo"]


@pytest.mark.parametrize("kat", ["alak", "keplet"])
@pytest.mark.parametrize("szo", ["utóbb", "hiányzó"])
def test_3_k1_a_kotest_k2b_a_most_is_kimondott_sajat_szot_meri(kat, szo):
    a = _o("alak", kat, [100, 100, 200, 200], forras="sajat", szo=szo)
    e = megj("alak", kat, kotes="szora", kotes_szo="előbb", szo=szo, tartalom="u+v")
    mu = munka([_l("s01-01", []), _l("s01-02", [a], megjelenik=[e])])
    assert kapu.k1_kotetlen(mu) == []
    if szo == "utóbb":
        assert kapu.k2(mu)[0]["sulyossag"] == "hiba"
        assert "3,8 s-mal a „utóbb” előtt látszik" in kapu.k2(mu)[0]["uzenet"]
    else:
        assert kapu.k2(mu) == []
    e["kotes_szo"] = None
    # A most is kimondott saját szó kötés nélkül is mérhető; az elavult szó nem jelez.
    assert bool(kapu.k2(mu)) == (szo == "utóbb")
    e["kotes_szo"] = "utóbb"
    assert any("előtt" in x["uzenet"] for x in kapu.k2(mu))


def test_4_elfogadott_uj_keplet_kulon_fejlecsor(tmp_path):
    a = _o("vaz", "keplet", [100, 100, 200, 200], forras="sajat")
    mu = tabla_munka(munka([_l("s01-01", []), _l("s01-02", [a], megjelenik=[megj("vaz", tartalom="u=")])]), tmp_path)
    mu.kivetel = {"elfogad": [{"lepes": "s01-02", "kod": "K2b", "obj": "vaz", "indok": "üres sorváz"}]}
    leletek = kapu.k2(mu)
    assert kapu.kivetelek(mu, leletek) == []
    tabla.ir(mu, tabla_k(leletek))
    assert "új képlet elfogadva: s01-02/vaz/üres sorváz" in (tmp_path / "tabla.txt").read_text().splitlines()


@pytest.mark.parametrize("attrib", [None, {"kat": "alak"}])
def test_5_eltuno_mozgo_elem_doboz_nelkul_sem_omlik_ossze(attrib):
    mu = munka([_l("s01-01", [sugar(0)]), _l("s01-02", [sugar(90)],
                mozog=[{"obj": "mozgo", "tol": 180, "ig": 189}, {"obj": "eltuno", "tol": 180, "ig": 185}])])
    if attrib is not None:
        mu.attr["eltuno"] = attrib
    meres = kapu.mozgasi_meresek(mu)[0]
    assert meres["fok"] == pytest.approx(90, abs=1)
    assert meres["kuszob_fok_s"] == 120
    assert kapu.k14(mu)[0]["obj"] == "mozgo"


def alak(utak):
    pontok = [q for p in utak for q in p]
    return _o("mozgo", "alak", [min(p[0] for p in pontok), min(p[1] for p in pontok),
                                 max(p[0] for p in pontok), max(p[1] for p in pontok)], {"t": "torott", "p": utak})


def mozgas(a, b, kockak=30):
    return munka([_l("s01-01", [a]), _l("s01-02", [b], mozog=[{"obj": "mozgo", "tol": 180, "ig": 180 + kockak}])])


def test_6_eltero_sugaru_iv_nem_noveli_a_forgast():
    def sugar_iv(fok, r):
        a = sugar(fok)
        a["vonal"]["p"][1] = [[500 + r * math.cos(math.radians(fok * i / 80)),
                                  540 - r * math.sin(math.radians(fok * i / 80))] for i in range(81)]
        return a
    mu = mozgas(sugar_iv(36.9, 96), sugar_iv(143.1, 52))
    assert kapu.mozgasi_meresek(mu)[0]["fok"] == pytest.approx(106.2, abs=.5)
    assert kapu.k14(mu) == []  # 106,2°/s < 120°/s


def test_6_valtozatlan_tengelypar_nem_forgatas():
    tengelyek = [[[500, 540], [800, 540]], [[500, 540], [500, 240]]]
    def pont(x, y):
        return [[x - 8, y - 8], [x + 8, y - 8], [x + 8, y + 8], [x - 8, y + 8], [x - 8, y - 8]]
    mu = mozgas(alak(tengelyek + [pont(600, 400)]), alak(tengelyek + [pont(610, 385)]), 15)
    assert not any("fok" in m for m in kapu.mozgasi_meresek(mu))
    assert kapu.k14(mu) == []


@pytest.mark.parametrize("torles", [False, True])
def test_6_allo_sugar_melletti_teljes_kor_nem_teljes_fordulat(torles):
    a, b = sugar(0), sugar(360)
    mu = mozgas(b, a, 9) if torles else mozgas(a, b)
    assert not any("fok" in m for m in kapu.mozgasi_meresek(mu))
    assert kapu.k14(mu) == []


def test_6_azonos_sugaru_de_elteto_iv_is_csak_szogegyezessel_szamit():
    a, b = sugar(30), sugar(90)
    b["vonal"]["p"][1] = copy.deepcopy(sugar(180)["vonal"]["p"][1])
    assert kapu.mozgasi_meresek(mozgas(a, b))[0]["fok"] == pytest.approx(60, abs=1)


def test_7_nem_mert_palya_adat_de_nem_lelet():
    a = _o("mozgo", "alak", [100, 100, 200, 200])
    b = dict(a, doboz=[100, 100, 500, 200])
    mu = mozgas(a, b)
    m = kapu.mozgasi_meresek(mu)
    assert m[0]["nem_mert"] and "px_s" not in m[0] and "fok_s" not in m[0]
    assert kapu.k14(mu) == []


@pytest.mark.parametrize("ut,n,fps,figy", [(783, 30, 30, False), (100, 9, 30, True), (243, 8, 30, True),
                                          (25, 14, 30, True), (25, 15, 30, False), (24, 1, 30, False),
                                          (100, 7, 15, False), (100, 6, 15, True)])
def test_8_eltolasnal_minimum_ido_szamit(ut, n, fps, figy):
    a = _o("mozgo", "alak", [100, 100, 200, 200])
    b = dict(a, doboz=[100 + ut, 100, 200 + ut, 200])
    mu = mozgas(a, b, n)
    mu.fps = fps
    ls = kapu.k14(mu)
    assert bool(ls) == figy
    if ut > 24:
        assert kapu.mozgasi_meresek(mu)[0]["min_ido_s"] == .5
    if ls:
        assert "odaérés" not in ls[0]["uzenet"]


def test_9_kapu_egyszer_mer_es_ugyanaz_kerul_a_jsonba(monkeypatch):
    mu = kapu.Munka(TESZT)
    eredeti = kapu.mozgasi_meresek
    hivasok = []
    def mer(mu):
        hivasok.append(eredeti(mu))
        return hivasok[-1]
    monkeypatch.setattr(kapu, "mozgasi_meresek", mer)
    k = kapu.kapu_munkan(mu)
    assert len(hivasok) == 1
    assert k["mozgas_meres"] is hivasok[0]
    assert k["kotetlen_valtozasok"] == [e for e in kapu.szinkron_adatok(mu) if not e["kotes_szo"]]


@pytest.mark.parametrize("forras", ["esemeny", "attrib"])
@pytest.mark.parametrize("tipus", ["szora", "horgony"])
def test_review2_sajat_szo_orokolt_masik_szo_szakaszaban(forras, tipus):
    a = _o("tag", "keplet", [200, 200, 260, 240], forras="sajat")
    e = megj("tag", kocka=195, tartalom="u")
    (e if forras == "esemeny" else a)["szo"] = "utóbb"
    elemek = [{"kezd_kocka": 186, "veg_kocka": 192, tipus: "előbb"},
              {"kezd_kocka": 195, "veg_kocka": 201}]
    mu = munka([_l("s01-01", []), _l("s01-02", [a], megjelenik=[e], elemek=elemek)])
    ls = kapu.k2(mu)
    assert len(ls) == 1 and ls[0]["kod"] == "K2b" and ls[0]["sulyossag"] == "hiba"
    assert "3,5 s-mal a „utóbb” előtt látszik" in ls[0]["uzenet"]
    # A saját szó esetén a tag megjelenése számít, nem a szakasz korábbi kezdete.
    e["kocka"] = 300
    assert kapu.k2(mu) == []


@pytest.mark.parametrize("orokolt", [False, True])
def test_review2_elavult_szo_kotott_megjelenesnel_nem_hiany(orokolt):
    a = _o("tag", "keplet", [200, 200, 260, 240], forras="sajat", szo="régi")
    e = megj("tag", tartalom="u", kotes=None if orokolt else "szora", kotes_szo="ismeretlen")
    elem = {"kezd_kocka": 186, "veg_kocka": 201, "szora": "ismeretlen"}
    mu = munka([_l("s01-01", []), _l("s01-02", [a], megjelenik=[e], elemek=[elem] if orokolt else [])])
    assert kapu.k2(mu) == []  # a kötés szóideje sem ismert: ebből nincs mért eltérés
    e["kotes_szo"] = elem["szora"] = "utóbb"
    assert "3,8 s-mal a „utóbb” előtt látszik" in kapu.k2(mu)[0]["uzenet"]
    e["kotes_szo"] = elem["szora"] = "előbb"
    assert kapu.k2(mu) == []
    e["kotes"] = None
    mu.lepesek[1]["elemek"] = []
    assert "nincs ebben a lépésben" in kapu.k2(mu)[0]["uzenet"]


@pytest.mark.parametrize("iv_fok", [90, 92, 180, 450])
def test_review2_forgasszog_a_sugar_ket_allasatol_fugg(iv_fok):
    a, b = sugar(30), sugar(90)
    iv_nelkul_a, iv_nelkul_b = copy.deepcopy(a), copy.deepcopy(b)
    iv_nelkul_a["vonal"]["p"] = a["vonal"]["p"][:1]
    iv_nelkul_b["vonal"]["p"] = b["vonal"]["p"][:1]
    vart = kapu.mozgasi_meresek(mozgas(iv_nelkul_a, iv_nelkul_b))[0]["fok"]
    # A kicsit eltérő ív sem emelheti a szöget a korábbi 3°-os tűrésen belül.
    b["vonal"]["p"][1] = copy.deepcopy(sugar(iv_fok)["vonal"]["p"][1])
    assert kapu.mozgasi_meresek(mozgas(a, b))[0]["fok"] == vart
