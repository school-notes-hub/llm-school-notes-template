"""A kapu (K1–K12), a tábla, a lapok és a lépéskulcs próbái a tesztjelenetek renderjén.

Elfogadási próba: a TesztJelenet-en a kapu zöld; a HibasJelenet-en a (lépés, kód, súlyosság) lista
pontosan az elvart-kapu.json-é. Futtatás: kapu-teszt/kapu-teszt.sh (szükség esetén --render).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

GYOKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GYOKER))
import kapu  # noqa: E402
import lapok  # noqa: E402
from szamnev import ertek, ertekek  # noqa: E402

TESZT = GYOKER / "videotar-teszt" / "tesztjelenet"
HIBAS = GYOKER / "videotar-teszt" / "hibasjelenet"
KIMENET = ["kapu.json", "tabla.txt", "szoveg.md", "lepeskulcs.json", "lapok", "kockak", "kivagat"]


def harmasok(k):
    return [(x["lepes"], x["kod"], x["sulyossag"]) for x in k["leletek"]]


def test_hibasjelenet_pontosan_az_elvart_leletek():
    elvart = json.loads((HIBAS / "elvart-kapu.json").read_text(encoding="utf-8"))["leletek"]
    k = kapu.kapu(HIBAS)
    assert harmasok(k) == [(x["lepes"], x["kod"], x["sulyossag"]) for x in elvart]
    assert [x["obj"] for x in k["leletek"]] == [x["obj"] for x in elvart]
    assert not k["zold"]


def test_tesztjelenet_zold():
    k = kapu.kapu(TESZT)
    assert k["zold"], [x for x in k["leletek"] if x["sulyossag"] == "hiba"]
    assert k["szamok"]["hiba"] == 0


def _pillanat(m: Path) -> dict:
    ki = {}
    for n in KIMENET:
        p = m / n
        for f in sorted([p] if p.is_file() else p.rglob("*") if p.exists() else []):
            if f.is_file():
                ki[str(f.relative_to(m))] = f.read_bytes()
    return ki


@pytest.mark.parametrize("m", [TESZT, HIBAS], ids=["teszt", "hibas"])
def test_futtat_atadas_bajtra_azonos_es_kilepesi_kod(m):
    kod1, sorok = kapu.futtat(m, atadas=True)
    a = _pillanat(m)
    kod2, _ = kapu.futtat(m, atadas=True)
    b = _pillanat(m)
    assert kod1 == kod2 == (0 if m == TESZT else 1)
    assert a.keys() == b.keys() and all(a[x] == b[x] for x in a), [x for x in a if a[x] != b.get(x)]
    assert any(x.startswith("lapok/") for x in a) and "tabla.txt" in a
    # összefoglaló: a kapu-rész legfeljebb 12 figyelmeztetéssor
    assert sum(s.startswith(" FIGY") for s in sorok) <= 12 and len(sorok) <= 30
    # tábla ≤ 10 e token (kb. 3,2 karakter/token)
    assert len((m / "tabla.txt").read_text(encoding="utf-8")) / 3.2 < 10_000


def test_lapok_formatuma():
    from PIL import Image
    kapu.futtat(HIBAS, atadas=True)
    lapfajlok = sorted((HIBAS / "lapok").glob("*.png"))
    assert [p.name for p in lapfajlok] == ["01-h01.png", "02-h01-b.png", "03-h01-c.png"]
    assert all(Image.open(p).size == (1920, 1140) for p in lapfajlok[:2])
    assert Image.open(lapfajlok[2]).size == (1920, 380)                 # az utolsó lap a használt rácsra vágva
    kiv = sorted(p.name for p in (HIBAS / "kivagat").glob("*.png"))
    assert kiv == ["h01-10-h_felirat.png", "h01-12-h_kor_kek.png", "h01-13-h_keret.png", "h01-18-h_ra_a.png"]
    assert all(Image.open(HIBAS / "kivagat" / n).size[0] >= 600 for n in kiv)


def test_kivetelek():
    mu = kapu.Munka(HIBAS)
    hibak = [x for x in kapu.kapu_munkan(mu)["leletek"] if x["sulyossag"] == "hiba"]
    mu.kivetel = {"elfogad": [{"lepes": "h01-10", "kod": "K4", "obj": "h_felirat", "indok": "szándékos áthúzás"},
                              {"lepes": "h01-09", "kod": "K3", "obj": "h_kilogo", "indok": "hibát az író nem fogadhat el"},
                              {"lepes": "h01-12", "kod": "K6b", "obj": "h_kor_kek", "indok": " "}],
                  "teves_hiba": [{"lepes": x["lepes"], "kod": x["kod"], "obj": x["obj"], "indok": "téves?"} for x in hibak]}
    k = kapu.kapu_munkan(mu)
    assert next(x for x in k["leletek"] if x["kod"] == "K4")["elfogadva"] == "szándékos áthúzás"
    assert {e["ok"] for e in k["ervenytelen_kivetelek"]} == {"csak figyelmeztetésre vonatkozhat", "indok nélkül"}
    assert not k["zold"] and k["atadhato"]
    mu.kivetel = {"felulbiral": [{"lepes": x["lepes"], "kod": x["kod"], "obj": x["obj"], "indok": "eszközhiba"} for x in hibak]}
    k = kapu.kapu_munkan(mu)                       # az író 480p-s futása: a felülbírálás nem számít
    assert not k["zold"] and not any(x.get("felulbiralva") for x in k["leletek"])
    assert {e["ok"] for e in k["ervenytelen_kivetelek"]} == {"csak a vezérlő, --atadas"}
    k = kapu.kapu_munkan(mu, vezerlo=True)         # --atadas / --vegleges
    assert k["zold"] and not k["ervenytelen_kivetelek"]
    felul = [s for s in kapu.osszefoglalo(k) if s.startswith(" FELÜLBÍRÁLVA")]
    assert len(felul) == len(hibak) and all(s.endswith(": eszközhiba") for s in felul)


def test_k2_bovitett_keplet_regi_szama_nem_uj():
    """Az atir-ral bővített képletben csak az új szám jelenik meg újként (multihalmaz-különbség)."""
    assert kapu.uj_szamok({"szamok": [15, 2, 15], "elozo_szamok": [15]}) == [2, 15]
    assert kapu.uj_szamok({"szamok": [15, 2], "elozo_szamok": [15]}) == [2]
    assert kapu.uj_szamok({"szamok": [15]}) == [15]
    # a napló a tartalomváltozáshoz beírja az előző számokat (a TesztJelenet számlálója)
    naplo = json.loads((TESZT / "render_naplo.json").read_text(encoding="utf-8"))
    tart = [e for l in naplo["lepesek"] for e in l["megjelenik"] if e["ok"] == "tartalom" and e.get("szamok")]
    assert tart and all("elozo_szamok" in e for e in tart)


def test_kivagat_legfeljebb_5_determinisztikus():
    mu = kapu.Munka(HIBAS)
    k = kapu.kapu_munkan(mu)
    minta = next(x for x in k["leletek"] if x["kod"] == "K4")
    k = copy.deepcopy(k)
    k["leletek"] += [dict(minta, lepes=f"h01-{n:02d}", obj=f"x{n}") for n in (16, 2, 5)]
    try:
        kapu.futtat(HIBAS, atadas=True)
        sor = lapok.atadas(mu, k)
        assert sor.endswith("kivágat 5 (+2 kivágat nélkül)"), sor
        assert sorted(p.name for p in (HIBAS / "kivagat").iterdir()) == \
            ["h01-02-x2.png", "h01-05-x5.png", "h01-10-h_felirat.png", "h01-12-h_kor_kek.png", "h01-13-h_keret.png"]
        utolso = (HIBAS / "tabla.txt").read_text(encoding="utf-8").splitlines()[-1]
        assert utolso.startswith("+2 kivágat nélkül") and "h01-16/x16 K4, h01-18/h_ra_a K4" in utolso
    finally:
        kapu.futtat(HIBAS, atadas=True)            # a mappa visszaáll a valódi átadásra


def test_k10_karakteres_arany():
    """Betűnév, szóhatár (összevonás, bontás) és egy elírt betű nem ad K10-et; a valódi eltérés igen."""
    class Mu:
        ids = ["x-01", "x-02", "x-03"]
        szavak_json = {
            "x-01": [{"szo": "Zé", "ertek": None, "whisper": "Z"}, {"szo": "elemszáma", "ertek": None, "whisper": "elemszáma"},
                     {"szo": "most", "ertek": None, "whisper": "most"}, {"szo": "tizenhét", "ertek": 17, "whisper": "17"}],
            "x-02": [{"szo": "min", "ertek": None, "whisper": "miniátszanak"},
                     {"szo": "játszanak", "ertek": None, "whisper": "miniátszanak"},
                     {"szo": "aszerint", "ertek": None, "whisper": "az szerint"}],
            "x-03": [{"szo": "a", "ertek": None, "whisper": "a"}, {"szo": "kutya", "ertek": None, "whisper": "macska"},
                     {"szo": "ugat", "ertek": None, "whisper": "nyávog"}]}
    l = kapu.k10(Mu())
    assert [(x["lepes"], x["kod"], x["sulyossag"]) for x in l] == [("x-03", "K10", "figy")]


def test_k10_egy_betus_szovaltozas():
    """Egy betű is más szó: „számokat” → „sámokat” (sz → s) figyelmeztetés a szópárral; a kiejtés szerinti
    Whisper-írás („halmazt” → „halmaszt”, „metszet” → „meccet”, „medszet”, „metzet”), a betűnév + toldalék
    („efnek” → „f nek”) és a szóhatár („aszerint” → „az szerint”) zaj marad."""
    def w(*parok):
        return [{"szo": a, "ertek": None, "whisper": b} for a, b in parok]

    class Mu:
        ids = ["x-01", "x-02"]
        szavak_json = {
            "x-01": w(("Írd", "Írd"), ("fel", "fel"), ("a", "a"), ("számokat", "sámokat"), ("sorban", "sorban")),
            "x-02": w(("A", "A"), ("halmazt", "halmaszt"), ("és", "és"), ("a", "a"), ("metszet", "meccet"),
                      ("vagy", "vagy"), ("metszet", "medszet"), ("és", "és"), ("efnek", "f nek"), ("pontosan", "pontosan"),
                      ("aszerint", "az szerint"), ("a", "a"), ("metszet", "metzet"), ("van", "van"), ("lyuk", "juk"))}
    l = kapu.k10(Mu())
    assert [(x["lepes"], x["kod"], x["sulyossag"]) for x in l] == [("x-01", "K10", "figy")]
    assert "„számokat” helyett „sámokat”" in l[0]["uzenet"]
    assert sum("helyett" in x["uzenet"] for x in l) == 1
    assert l[0]["szovaltozas"] == 1 and "k10_ketseges" in l[0]["uzenet"] and "lektor" not in l[0]["uzenet"]


def test_k10_szovaltozas_nem_fogadhato_el():
    """F1: a szóváltozás figyelmeztetését az író nem zárhatja le „elfogad”-dal; a karakteres eltérését igen."""
    class Mu:
        ids = ["x-01"]
        szavak_json = {"x-01": [{"szo": a, "ertek": None, "whisper": b} for a, b in
                                (("Írd", "Írd"), ("fel", "fel"), ("a", "a"), ("számokat", "sámokat"))]}
        kivetel = {"elfogad": [{"lepes": "x-01", "kod": "K10", "obj": None, "indok": "Whisper-zaj"}]}
    l = kapu.k10(Mu())
    rossz = kapu.kivetelek(Mu(), l)
    assert len(rossz) == 1 and "nem lehet elfogadni" in rossz[0]["ok"] and "elfogadva" not in l[0]


def test_ido_kerekites_percbe_visz():
    assert [kapu.ido(x) for x in (0, 5.34, 59.94, 59.96, 119.97, 125.0, 365.4)] == \
        ["0:00,0", "0:05,3", "0:59,9", "1:00,0", "2:00,0", "2:05,0", "6:05,4"]


def test_k13_ures_es_szinte_ures_kep(tmp_path):
    """K13 egy szintetikus videón: 2 s tartalom, 2 s fekete (hiba), 2 s fekete egy kis fehér jellel (figy),
    2 s tartalom, 0,5 s fekete (rövid: nem lelet). A szakasz a lépéseihez kötve, a lelet a kezdő lépésen."""
    mp4 = tmp_path / "v.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x180:r=10:d=2",
                    "-f", "lavfi", "-i", "color=black:s=320x180:r=10:d=2",
                    "-f", "lavfi", "-i", "color=black:s=320x180:r=10:d=2,drawbox=x=150:y=80:w=6:h=6:color=white:t=fill",
                    "-f", "lavfi", "-i", "testsrc=s=320x180:r=10:d=2", "-f", "lavfi", "-i", "color=black:s=320x180:r=10:d=0.5",
                    "-filter_complex", "[0:v][1:v][2:v][3:v][4:v]concat=n=5:v=1[v]", "-map", "[v]", "-c:v", "ffv1", str(mp4)],
                   check=True)
    sz = kapu.sotet_szakaszok(mp4, 8.5)
    assert [(round(a, 1), round(b, 1)) for a, b in sz["ures"]] == [(2.0, 4.0)]
    assert [(round(a, 1), round(b, 1)) for a, b in sz["majdnem"]] == [(2.0, 6.0)]

    class Mu:
        fps = 10.0
        tl = [{"id": "x-01", "kezd_kocka": 0, "veg_kocka": 30}, {"id": "x-02", "kezd_kocka": 30, "veg_kocka": 50},
              {"id": "x-03", "kezd_kocka": 50, "veg_kocka": 85}]
        ids = ["x-01", "x-02", "x-03"]
    l = kapu.k13(Mu(), {"ures": [(2.0, 4.0)], "majdnem": [(2.0, 6.0), (7.0, 8.2)]})
    assert [(x["lepes"], x["kod"], x["sulyossag"]) for x in l] == [("x-01", "K13", "hiba"), ("x-02", "K13", "figy"),
                                                                   ("x-03", "K13", "figy")]
    assert "üres kép 0:02,0–0:04,0 (2,0 s; x-01–x-02)" in l[0]["uzenet"]
    assert "szinte üres kép 0:04,0–0:06,0 (2,0 s; x-02–x-03)" in l[1]["uzenet"]
    assert "0:07,0–0:08,2 (1,2 s; x-03)" in l[2]["uzenet"]
    assert kapu.k13(Mu(), {"ures": [], "majdnem": [(2.0, 4.0)]})[0]["sulyossag"] == "figy"
    l = kapu.k13(Mu(), {"ures": [(2.0, 4.0)], "majdnem": [(2.0, 4.5)]})     # az üresen túl csak 0,5 s: nem külön jel
    assert len(l) == 1 and "szinte" not in l[0]["uzenet"]
    # F7: darabonként: két 0,6 s-os darab az üres két oldalán nem ad figyelmeztetést, egy 1,2 s-os igen
    l = kapu.k13(Mu(), {"ures": [(2.0, 4.0)], "majdnem": [(1.4, 4.6)]})
    assert [x["sulyossag"] for x in l] == ["hiba"] and "szinte" not in l[0]["uzenet"]
    l = kapu.k13(Mu(), {"ures": [(2.0, 4.0)], "majdnem": [(1.4, 5.2)]})
    assert [(x["lepes"], x["sulyossag"]) for x in l] == [("x-01", "hiba"), ("x-02", "figy")]
    assert "szinte üres kép 0:04,0–0:05,2 (1,2 s; x-02–x-03)" in l[1]["uzenet"]


def test_k13_hatter_sotet_a_kuszob_alatt():
    """A videotar háttérszíne (stilus.HATTER) a K13 küszöbe alatt van, különben az üres kép nem fekete, és a
    K13 nem látná. Luma szűk tartományban (16–235), BT.601 és BT.709 mátrixszal is; a blackdetect
    küszöbe 16 + pix_th · 219."""
    import re
    m = re.search(r'^HATTER = "#([0-9A-Fa-f]{6})"', (GYOKER / "videotar" / "stilus.py").read_text(encoding="utf-8"), re.M)
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    kuszob = 16 + kapu.K13_PIX * 219
    for kr, kg, kb in ((0.299, 0.587, 0.114), (0.2126, 0.7152, 0.0722)):
        assert 16 + 219 * (kr * r + kg * g + kb * b) / 255 < kuszob - 3


def test_k11_szintetikus():
    assert kapu.k11(5 * 60 * 30, 30, 60) == []
    assert [x["sulyossag"] for x in kapu.k11(7 * 60 * 30, 30, 60)] == ["figy"]
    assert [x["sulyossag"] for x in kapu.k11(5 * 60 * 30, 30, 81)] == ["figy"]
    assert [x["sulyossag"] for x in kapu.k11(8 * 60 * 30 + 31, 30, 60)] == ["hiba"]


def test_k8a_ffprobe(tmp_path):
    def mp4(nev, *x):
        p = tmp_path / nev
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=0.2:r=30", "-f", "lavfi",
                        "-i", "sine=d=0.2", *x, "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-shortest",
                        str(p)] if not x else
                       ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=0.2:r=30", "-f", "lavfi",
                        "-i", "sine=d=0.2", *x, "-shortest", str(p)], check=True)
        return p
    assert kapu.k8a(mp4("jo.mp4")) == []
    assert [x["kod"] for x in kapu.k8a(mp4("cimes.mp4", "-metadata", "title=Halmazok"))] == ["K8a"]


def test_valtozott_lepes_es_rakovetkezoje():
    mu = kapu.Munka(TESZT)
    uj = lapok.lepeskulcs(mu)
    assert lapok.lepeskulcs(mu) == uj
    regi = copy.deepcopy(uj)
    regi["lepesek"]["t02-05"]["vege"] = "x"
    assert lapok.valtozott_lepesek(uj, regi, mu.ids) == {"t02-05", "t02-06"}
    assert lapok.valtozott_lepesek(uj, uj, mu.ids) == set()


def test_szamnev():
    for szo, v in [("tizenkét", 12), ("hatot", 6), ("kétszer", 2), ("hármat", 3), ("néggyel", 4), ("Egy", 1),
                   ("egyenlő", None), ("négyzet", None), ("harmadik", None), ("9-et", 9), ("huszonöt", 25), ("fél", 0.5)]:
        assert ertek(szo) == v, szo
    assert ertekek("mínusz három".split()) == [-3, None]
    assert ertekek("két egész öt tized".split()) == [2.5, None, None, None]
    assert ertekek("mínusz tizenkét egész négy tized".split()) == [-12.4, None, None, None, None]
    assert ertekek("mínusz kettő és fél".split()) == [-2.5, None, None, None]
    assert ertekek("hat mínusz két egész öt tized".split()) == [6, None, 2.5, None, None, None]


def test_whisper_tizedes_es_iksz():
    from lanc.szavak import betu, whisper_ertek
    assert whisper_ertek("4 7") == 4.7 and whisper_ertek("4 7 -tel") == 4.7 and whisper_ertek("2 85") == 2.85
    assert whisper_ertek("320") == 320 and whisper_ertek("") is None
    assert whisper_ertek("Minusz 12 4") == -12.4 and whisper_ertek("-gyel 0 65") == 0.65 and whisper_ertek("-5 4") == -5.4
    assert betu("iksz") == betu("x") == "x"


def test_szamnev_egy_olvaso():
    """A kapu a lánc olvasóját használja: „hat mínusz három” 6 és 3 (nem −3 a „mínusz”-on), a „hatás”,
    „hátra”, „egyre” nem szám, és a kapu szavanként ugyanazt látja, amit a lánc."""
    import szamnev
    from lanc import szavak as sz
    assert ertekek("hat mínusz három".split()) == [6, None, 3]
    assert ertekek("az eredmény mínusz három".split()) == [None, None, -3, None]
    for szo in ("hatás", "hátra", "egyre", "mínusz", "egyik", "harmadik"):
        assert ertek(szo) is None, szo
    assert szamnev.szoros("kétszer") and not szamnev.szoros("kettő") and not szamnev.szoros("szer")
    for szo in ("tizenkét", "hatot", "kétszer", "eggyel", "hússzal", "2,5", "hatás", "egyre", "nulláról"):
        assert ertek(szo) == sz.egy_szo(szo)[0], szo


def test_k10_whisper_szo_nelkul_figy():
    """Ha a Whisper egy lépésre egyetlen szót sem adott, az nem „a hang mást mond” hiba, hanem figyelmeztetés."""
    class Mu:
        ids = ["x-01"]
        szavak_json = {"x-01": [{"szo": "két", "ertek": 2, "whisper": None}, {"szo": "kör", "ertek": None, "whisper": None}]}
        kivetel = {"elfogad": [{"lepes": "x-01", "kod": "K10", "obj": None, "indok": "csend"}]}
    l = kapu.k10(Mu())
    assert [(x["kod"], x["sulyossag"]) for x in l] == [("K10", "figy")]
    assert "lektor" not in l[0]["uzenet"] and "k10_ketseges" in l[0]["uzenet"] and l[0]["nincs_szo"]
    rossz = kapu.kivetelek(Mu(), l)                   # elfogadni nem lehet: a tulajdonos hallgatja meg
    assert len(rossz) == 1 and "nem lehet elfogadni" in rossz[0]["ok"] and "elfogadva" not in l[0]


# --- a lektor által talált kapurések (statikai videók): K4, K7, szinkron --------------------------------
# A geometria a lektori ítéletek videóinak régi változataiból (render_naplo.json, 1920×1080 px).

def _mu(lepesek: list[dict]) -> kapu.Munka:
    """Ál-munkamappa a szabályfüggvényeknek: lépések (allapot, megjelenik, eltunik, mozog, atalakul)."""
    mu = object.__new__(kapu.Munka)
    mu.fps, mu.lepesek = 30.0, lepesek
    mu.attr = {}
    for l in lepesek:
        for k in sorted(l["allapot"]):
            for o in l["allapot"][k]:
                mu.attr[o["obj"]] = o
    return mu


def _o(obj, kat, doboz, vonal=None, csoport=None, **x) -> dict:
    o = {"obj": obj, "kat": kat, "csoport": csoport or obj, "doboz": doboz, **x}
    if vonal:
        o["vonal"] = vonal
    if kat in ("keplet", "szoveg", "szam"):
        o["font"] = 34.0
    return o


def _l(sid, vege, **x) -> dict:
    return {"id": sid, "allapot": {"vege": vege}, "megjelenik": [], "eltunik": [], "mozog": [], "atalakul": [],
            "elemek": [], **x}


def _teglalap(d) -> dict:
    x0, y0, x1, y1 = d
    return {"t": "torott", "p": [[[x1, y0], [x0, y0], [x0, y1], [x1, y1], [x1, y0]]]}


def _k4(lepesek) -> list[tuple]:
    return sorted((x["lepes"], x["obj"], x["uzenet"].split(" (")[0].split(" →")[0]) for x in kapu.k345(_mu(lepesek))
                  if x["kod"] == "K4")


def test_k4_meretvonal_a_cimke_szelen():
    """Egy kész videó lépése (lektori lelet): a b méretvonal 2 px-re a címke dobozán belül fut a jobb oldali F betűin (a 4 px-es
    belső sávon kívül, ezért eddig nem volt lelet). A 37 px-re álló b címke nem lelet."""
    b_kar = _o("b_kar", "alak", [1041, 601, 1365, 628], {"t": "torott", "p": [[[1041, 614], [1203, 614], [1365, 614]],
                                                                            [[1041, 628], [1041, 614], [1041, 601]]]})
    vege = [b_kar, _o("jobb_F", "keplet", [1098, 612, 1132, 644]), _o("b_cimke", "keplet", [1194, 651, 1212, 685])]
    assert _k4([_l("s04-04", vege)]) == [("s04-04", "jobb_F", "a(z) b_kar vonala a szöveg szélén fut")]


def test_k4_keret_ra_csak_a_sajat_celjara():
    """Egy kész videó lépése (lektori lelet): a d fókuszkeretének (`ra`) felső éle átfut a „d+b” címkén. A keret `ra`-ja csak
    a saját céljait (d címke, méretvonal) menti fel, más feliratot nem; a `vonatkozik` nélküli vonal-`ra` egyetlen feliratot sem."""
    keret = _o("fokusz_37", "keret", [589, 790, 1061, 921], _teglalap([589, 790, 1061, 921]),
               vonatkozik=["d_cimke", "teljes_tavolsag"], ra="a keret körülveszi a már álló méretet")
    vege = [keret, _o("d_cimke", "keplet", [814, 867, 836, 901]), _o("d_plusz_b_2", "keplet", [892, 763, 923, 795])]
    assert _k4([_l("s05-05", vege)]) == [("s05-05", "d_plusz_b_2", "a(z) fokusz_37 vonala metszi a szöveget")]
    keret = dict(keret, vonatkozik=None)
    assert _k4([_l("s05-05", [keret, *vege[1:]])]) == [("s05-05", "d_plusz_b_2", "a(z) fokusz_37 vonala metszi a szöveget")]


def test_k4_cimke_a_test_korvonalan():
    """Egy kész videó lépése (lektori lelet): a „3 m” címke 3 px-lel átlépi a téglalap test jobb élét."""
    test_b = _o("test_b", "keret", [662, 367, 1258, 848], _teglalap([662, 367, 1258, 848]))
    vege = [test_b, _o("jobb_kar_ertek", "keplet", [1185, 409, 1261, 442]), _o("bal", "keplet", [1100, 409, 1180, 442])]
    assert _k4([_l("s04-10", vege)]) == [("s04-10", "jobb_kar_ertek", "a(z) test_b vonala a szöveg szélén fut")]


def test_k4_fokuszkeretek_osszeernek():
    """Egy kész videó lépése (lektori lelet): a két erőkar külön kerete 26 px-re egymásba lóg; 3 px-nél kisebb rés is lelet; a
    beágyazott keret, a távoli keret és a halmazkör (kör, a tartalom része) nem."""
    def k(nev, d):
        return _o(nev, "keret", d, _teglalap(d), vonatkozik=[nev + "_cel"])
    lepes = [_l("s02-01", [k("f0", [595, 587, 838, 641]), k("f1", [812, 587, 1054, 641])]),
             _l("s02-02", [k("f0", [595, 587, 700, 641]), k("f1", [702, 587, 1054, 641])]),
             _l("s02-03", [k("f0", [595, 587, 700, 641]), k("f1", [710, 587, 1054, 641]), k("f2", [600, 590, 650, 630])]),
             _l("s02-04", [_o("kor_a", "keret", [371, 392, 803, 824], {"t": "kor", "k": [587, 608], "r": 216}, vonatkozik=["t1"]),
                           _o("kor_b", "keret", [631, 392, 1063, 824], {"t": "kor", "k": [847, 608], "r": 216}, vonatkozik=["t2"])])]
    assert _k4(lepes) == [("s02-01", "f0", "a(z) f1 keretével egymásba lóg"), ("s02-02", "f0", "a(z) f1 keretével összeér")]


def test_k4_keret_ele_egy_vonalon_fut():
    """Egy kész videó lépése (lektori lelet): a G fókuszkeretének felső éle 177 px (itt a lekerekítés nélkül 185 px) hosszan a rúd sávjában fut. A keretet
    merőlegesen keresztező vonal (nyíl) és a keret mentén futó kiemelés nem lelet."""
    keret = _o("fok_11", "keret", [1242, 375, 1543, 535], _teglalap([1242, 375, 1543, 535]), vonatkozik=["nyil_G"])
    rud = _o("rud", "alak", [501, 370, 1419, 386], _teglalap([501, 370, 1419, 386]))
    nyil = _o("nyil_G", "nyil", [1253, 386, 1288, 524], {"t": "szakasz", "p": [[1270, 386], [1270, 524]]})
    seged = _o("seged", "vonal", [1300, 300, 1300, 600], {"t": "szakasz", "p": [[1300, 300], [1300, 600]]})
    kiem = _o("kiem", "kiemeles", [1242, 375, 1543, 535], _teglalap([1242, 375, 1543, 535]))
    assert _k4([_l("s03-12", [keret, rud, nyil, seged, kiem])]) == \
        [("s03-12", "fok_11", "a keret éle 185 px hosszan a(z) rud vonalán fut")]
    assert _k4([_l("s03-12", [keret, nyil, seged, kiem])]) == []


def test_k7_ures_keret():
    """Egy kész videó lépése (lektori lelet): a „hiányzó nyomaték” eltűnik, a fókuszkerete marad (üres keret). A videóban
    nem szereplő célnév (például halmazterület kulcsa) nem lelet."""
    cel = _o("hianyzo_nyomatek", "keplet", [1530, 280, 1660, 330])
    keret = _o("fokusz_30", "keret", [1516, 268, 1673, 339], _teglalap([1516, 268, 1673, 339]), vonatkozik=["hianyzo_nyomatek"])
    idegen = _o("kiemel", "kiemeles", [10, 10, 50, 50], vonatkozik=["ab"])
    mu = _mu([_l("s03-12", [cel, keret, idegen]), _l("s04-01", [keret, idegen])])
    assert [(x["lepes"], x["obj"]) for x in kapu.k7(mu)] == [("s04-01", "fokusz_30")]
    # összefüggő lépéssoronként egyszer
    mu = _mu([_l("s03-12", [cel, keret]), _l("s04-01", [keret]), _l("s04-02", [keret]), _l("s04-03", [keret])])
    assert [(x["lepes"], x["obj"], "s04-03-ig" in x["uzenet"]) for x in kapu.k7(mu)] == [("s04-01", "fokusz_30", True)]
    # névváltó csere (ReplacementTransform): az új objektum a keret dobozában áll, a keret nem üres
    uj = _o("M_ertek", "keplet", [1530, 280, 1660, 330])
    megj = [{"obj": "M_ertek", "kocka": 0, "veg_kocka": 10, "kat": "keplet", "ok": "uj"}]
    mu = _mu([_l("s03-12", [cel, keret]), _l("s04-01", [keret, uj], megjelenik=megj), _l("s04-02", [keret, uj])])
    assert kapu.k7(mu) == []
    # nagy háttérelem (a keret mögött régóta álló test), amelynek a közepe a keretbe esik: a keret mégis üres
    test = _o("test", "alak", [1200, 100, 1900, 600])
    mu = _mu([_l("s03-12", [cel, keret, test]), _l("s04-01", [keret, test])])
    assert [(x["lepes"], x["obj"]) for x in kapu.k7(mu)] == [("s04-01", "fokusz_30")]


def test_k7_vonal_a_mozgo_elem_vegso_helyen():
    """Egy kész videó lépése (lektori lelet): az O pont 1 s alatt a két erő közé megy, és ugyanebben az animációban jelennek meg a
    belső karok, amelyeknek a végvonása már a pont végső oszlopában áll. A kiinduló helyről a végsőig húzott nyom
    (a mozgást követi) nem lelet."""
    pont0, pont1 = _o("kulso_pont", "jelolo", [1463, 530, 1483, 550]), _o("kulso_pont", "jelolo", [734, 530, 754, 550])
    kar = _o("belso_bal_kar", "alak", [609, 601, 744, 628], {"t": "torott", "p": [[[609, 614], [676, 614], [744, 614]],
                                                                                  [[744, 628], [744, 614], [744, 601]]]})
    nyom = _o("nyom", "vonal", [744, 540, 1473, 540], {"t": "szakasz", "p": [[1473, 540], [744, 540]]})
    mozog = [{"obj": "kulso_pont", "tol": 7985, "ig": 8015}]
    for uj, vart in ((kar, ["belso_bal_kar"]), (nyom, [])):
        mu = _mu([_l("s05-05", [pont0]), _l("s05-06", [pont1, uj], mozog=mozog,
                                          megjelenik=[{"obj": uj["obj"], "kocka": 7985, "veg_kocka": 8015, "kat": uj["kat"], "ok": "uj"}])])
        assert [x["obj"] for x in kapu.k7(mu)] == vart


def test_szinkron_kapcsolt_jel_eltunik_mozgas_kozben():
    """Egy kész videó lépése (lektori lelet): a nyíl forog, az erőkar és a derékszögjel közben (nem követve) eltűnik. Nem
    lelet, ha az erőkar a lépésben maga is követi a mozgást, vagy ha ugyanolyan fajtájú új elem jelenik meg vele
    egy időben (áttűnéses csere)."""
    nyil = _o("ero_nyil", "nyil", [834, 328, 999, 524], {"t": "szakasz", "p": [[834, 328], [999, 524]]}, csoport="ero")
    kar = _o("erokar_szakasz", "vonal", [420, 328, 834, 675], {"t": "szakasz", "p": [[420, 675], [834, 328]]}, csoport="erokar")
    tavol = _o("mas", "vonal", [100, 100, 200, 100], {"t": "szakasz", "p": [[100, 100], [200, 100]]})
    elt = [{"obj": "erokar_szakasz", "kocka": 7241, "veg_kocka": 7295}, {"obj": "mas", "kocka": 7241, "veg_kocka": 7295}]
    mozog = [{"obj": "ero_nyil", "tol": 7241, "ig": 7295}]

    def futtat(**x):
        return [(f["lepes"], f["kod"], f["obj"]) for f in kapu.k1_kapcsolt(_mu([_l("s06-04", [nyil, kar, tavol]),
                                                                                _l("s06-05", [nyil], eltunik=elt, **x)]))]
    assert futtat(mozog=mozog) == [("s06-05", "K1", "erokar_szakasz")]
    assert futtat(mozog=mozog + [{"obj": "erokar_szakasz", "tol": 7241, "ig": 7270}]) == []
    uj = _o("erokar_2", "vonal", [400, 300, 800, 600], {"t": "szakasz", "p": [[400, 600], [800, 300]]})
    mu = _mu([_l("s06-04", [nyil, kar, tavol]), _l("s06-05", [nyil, uj], eltunik=elt, mozog=mozog,
                                                   megjelenik=[{"obj": "erokar_2", "kocka": 7241, "veg_kocka": 7295}])])
    assert kapu.k1_kapcsolt(mu) == []
    # a mozgó nyílhoz kötött új vonal (a végén a nyíl vonalán áll) is csere; a kép másik sarkában megjelenő nem
    kotott = _o("erokar_3", "vonal", [420, 500, 900, 675], {"t": "szakasz", "p": [[999, 524], [1500, 900]]})
    tavoli = _o("mas_vonal", "vonal", [1500, 900, 1700, 950], {"t": "szakasz", "p": [[1500, 900], [1700, 950]]})
    for e, vart in ((kotott, []), (tavoli, [("s06-05", "K1", "erokar_szakasz")])):
        mu = _mu([_l("s06-04", [nyil, kar, tavol]), _l("s06-05", [nyil, e], eltunik=elt, mozog=mozog,
                                                       megjelenik=[{"obj": e["obj"], "kocka": 7241, "veg_kocka": 7295}])])
        assert [(f["lepes"], f["kod"], f["obj"]) for f in kapu.k1_kapcsolt(mu)] == vart


# --- Címke–vonal rés, címke–cél sorrend, konténerkerekítés -------------------------

@pytest.mark.parametrize("doboz", [[631, 629, 654, 654], [631, 426, 654, 451], [623, 527, 654, 553]])
def test_k4_hat_pixeles_res_nem_eleg(doboz):
    """A három jel nem metszi a vonalat, mégis rátapad. A távolabb tett jel már rendben van."""
    vonal = _o("el", "vonal", [660, 289, 660, 791], {"t": "szakasz", "p": [[660, 791], [660, 289]]})
    cimke = _o("jel", "keplet", doboz)
    assert [(x[0], x[1]) for x in _k4([_l("s01-01", [vonal, cimke])])] == [("s01-01", "jel")]
    assert "rés 6 px < 12 px" in kapu.k345(_mu([_l("s01-01", [vonal, cimke])]))[0]["uzenet"]
    cimke["doboz"] = [doboz[0] - 20, doboz[1], doboz[2] - 20, doboz[3]]
    assert _k4([_l("s01-01", [vonal, cimke])]) == []


def test_k4_res_geometria_es_szandekos_jeloles():
    cimke = _o("jel", "keplet", [500, 500, 530, 530])
    vonal = _o("el", "vonal", [542, 400, 542, 600], {"t": "szakasz", "p": [[542, 400], [542, 600]]})
    assert _k4([_l("s01-01", [vonal, cimke])]) == []  # pontosan 12 px
    vonal["vonal"] = {"t": "szakasz", "p": [[538, 538], [600, 600]]}
    assert kapu._vonal_doboz_tav(vonal["vonal"], cimke["doboz"]) == pytest.approx(128 ** 0.5)
    assert _k4([_l("s01-01", [vonal, cimke])])
    assert "rés 11,3 px < 12 px" in kapu.k345(_mu([_l("s01-01", [vonal, cimke])]))[0]["uzenet"]
    vonal["vonal"] = {"t": "szakasz", "p": [[539, 539], [600, 600]]}
    assert _k4([_l("s01-01", [vonal, cimke])]) == []  # a bővített téglalap sarka nem elég
    kor = {"t": "kor", "k": [500, 500], "r": 40}
    assert kapu._vonal_doboz_tav(kor, [500, 500, 510, 510]) == pytest.approx(40 - 200 ** 0.5)
    # Az aláhúzás, a saját csoport törtvonala és a kiemelés kisebb rése szándékos.
    vonal["vonal"] = {"t": "szakasz", "p": [[500, 536], [530, 536]]}
    for jel in [dict(vonal, vonatkozik=["jel"]), dict(vonal, csoport="jel"), dict(vonal, kat="kiemeles")]:
        assert _k4([_l("s01-01", [jel, cimke])]) == []
    # A kapcsolat csak a közelséget menti fel; a metszés továbbra is lelet.
    vonal.update(vonatkozik=["jel"], vonal={"t": "szakasz", "p": [[500, 515], [530, 515]]})
    assert _k4([_l("s01-01", [vonal, cimke])])


@pytest.mark.parametrize("cel,vart", [("idegen", True), ("cimke", False), ("sor", False), ("tag", False)])
def test_k4_deklaralt_jeloles_csak_a_sajat_celjait_menti(cel, vart):
    """Az idegen címke melletti nyílra is kell rés; a cél és annak csoportja mentes."""
    cimke = _o("cimke", "keplet", [560, 380, 595, 420], csoport="sor")
    tag = _o("tag", "keplet", [450, 380, 480, 420], csoport="sor")
    nyil = _o("nyil", "nyil", [600, 300, 600, 500],
              {"t": "szakasz", "p": [[600, 300], [600, 500]]}, vonatkozik=[cel])
    leletek = _k4([_l("s01-01", [nyil, cimke, tag])])
    assert [x[1] for x in leletek] == (["cimke"] if vart else [])


@pytest.mark.parametrize("deklaralt,res,vart", [
    pytest.param(True, 6, True, id="jeloles-tapad"),
    pytest.param(True, 8, False, id="jeloles-hatar"),
    pytest.param(True, 10, False, id="jeloles-olvashato"),
    pytest.param(True, 12, False, id="jeloles-tag-res"),
    pytest.param(False, 6, True, id="vonal-tapad"),
    pytest.param(False, 8, True, id="vonal-nyolc"),
    pytest.param(False, 10, True, id="vonal-tiz"),
    pytest.param(False, 12, False, id="vonal-hatar"),
])
def test_k4_deklaralt_jeloles_reskuszobe(deklaralt, res, vart):
    """Idegen címke és jelölés között 8 px elég; önálló vonalnál továbbra is 12 px kell."""
    cimke = _o("cimke", "keplet", [560, 380, 595, 420])
    d = [595 + res, 350, 670, 450]
    vonal = _o("vonal", "keret" if deklaralt else "vonal", d, _teglalap(d),
               vonatkozik=["masik"] if deklaralt else [])
    leletek = kapu.rendez(kapu.k345(_mu([_l("s01-01", [vonal, cimke])])))
    assert [(x["kod"], x["obj"]) for x in leletek] == ([("K4", "cimke")] if vart else [])
    if vart:
        assert f"rés {res} px < {8 if deklaralt else 12} px" in leletek[0]["uzenet"]


def test_k4_jeloles_nem_fedi_el_a_masik_kozeli_vonalat():
    """A megengedett jelölésrés mögül előkerül a továbbra is túl közeli önálló vonal."""
    cimke = _o("cimke", "keplet", [560, 380, 595, 420])
    d = [605, 350, 670, 450]
    keret = _o("a_keret", "keret", d, _teglalap(d), vonatkozik=["masik"])
    vonal = _o("z_vonal", "vonal", [550, 350, 550, 450], {"t": "szakasz", "p": [[550, 350], [550, 450]]})
    leletek = kapu.rendez(kapu.k345(_mu([_l("s01-01", [keret, vonal, cimke])])))
    assert len(leletek) == 1
    assert "z_vonal vonalához túl közel áll (rés 10 px < 12 px)" in leletek[0]["uzenet"]


def test_k4_kozelseg_nem_fedi_el_az_erintkezest():
    cimke = _o("jel", "keplet", [500, 500, 530, 530])
    kozeli = _o("a_kozeli", "vonal", [536, 400, 536, 600], {"t": "szakasz", "p": [[536, 400], [536, 600]]})
    erinto = _o("z_erinto", "vonal", [530, 400, 530, 600], {"t": "szakasz", "p": [[530, 400], [530, 600]]})
    leletek = kapu.rendez(kapu.k345(_mu([_l("s01-01", [cimke, kozeli, erinto])])))
    assert len(leletek) == 1 and "z_erinto vonala a szöveg szélén" in leletek[0]["uzenet"]


def _megj(o, kezd, veg):
    return {"obj": o["obj"], "kat": o["kat"], "csoport": o["csoport"], "ok": "uj", "kocka": kezd, "veg_kocka": veg}


def _cimke_sor(kulon_lepes=0, tagok=2, sor_y=400, cimke_y=780, deklaralt=False, cimke_kezd=0):
    """Önálló címke, szavanként felépülő sor, majd aláhúzás; nincs tanulói szöveg."""
    sor = [_o(f"tag{i}", "keplet", [840 + i * 60, sor_y, 880 + i * 60, sor_y + 40], csoport="sor")
           for i in range(tagok)]
    kozep = (sor[0]["doboz"][0] + sor[-1]["doboz"][2]) // 2
    cimke = _o("cimke", "szoveg", [kozep - 80, cimke_y, kozep + 80, cimke_y + 40], tartalom="rövid címke")
    if deklaralt:
        cimke["vonatkozik"] = ["sor"]
    jel = _o("alahuzas", "vonal", [840, sor_y + 60, 1000, sor_y + 60], vonatkozik=["sor"])
    kezd = kulon_lepes * 120
    es = [_megj(o, kezd + 30 + i * 20, kezd + 40 + i * 20) for i, o in enumerate(sor)]
    lepesek = [_l(f"s01-{i+1:02d}", [cimke], kezd_kocka=i*120, veg_kocka=(i+1)*120) for i in range(kulon_lepes)]
    lepesek.append(_l(f"s01-{kulon_lepes+1:02d}", [cimke, *sor, jel], megjelenik=es,
                     kezd_kocka=kezd, veg_kocka=kezd+120))
    lepesek[0]["megjelenik"].append(_megj(cimke, cimke_kezd, cimke_kezd+6))
    return lepesek


@pytest.mark.parametrize("kulon,tagok,sor_y,cimke_y", [
    pytest.param(2, 4, 150, 70, id="ket-lepessel-elobb"),
    pytest.param(0, 4, 610, 780, id="negy-tag"),
    pytest.param(0, 2, 610, 770, id="ket-tag-kozelebb"),
    pytest.param(0, 1, 610, 780, id="egy-tag"),
    pytest.param(0, 2, 610, 780, id="ket-tag"),
    pytest.param(0, 4, 380, 770, id="negy-tag-tavolabb"),
    pytest.param(0, 2, 380, 770, id="ket-tag-tavolabb"),
])
@pytest.mark.parametrize("deklaralt", [False, True], ids=["terbeli", "deklaralt"])
def test_k7_korai_cimke_elrendezesei(kulon, tagok, sor_y, cimke_y, deklaralt):
    """A lektori esetek hét különböző elrendezése, deklarált és becsült célkapcsolattal."""
    ls = _cimke_sor(kulon, tagok, sor_y, cimke_y, deklaralt)
    lelet = kapu.k7(_mu(ls))
    assert [(x["lepes"], x["obj"]) for x in lelet] == [("s01-01", "cimke")]
    assert ("térbeli becslés" in lelet[0]["uzenet"]) is not deklaralt
    assert f"tag{tagok-1}" in lelet[0]["uzenet"]  # a teljes sor végét várja meg


@pytest.mark.parametrize("deklaralt", [False, True])
@pytest.mark.parametrize("kezd,vart", [(30, True), (59, False), (60, False), (70, False)])
def test_k7_cimke_csak_a_kesz_sor_utan(deklaralt, kezd, vart):
    ls = _cimke_sor(deklaralt=deklaralt, cimke_kezd=kezd)
    assert bool(kapu.k7(_mu(ls))) is vart  # egy kocka tűrés, a cél végéhez mérve


def test_k7_becsleshez_jeloles_es_kozeli_sor_kell():
    ls = _cimke_sor()
    ls[0]["allapot"]["vege"] = ls[0]["allapot"]["vege"][:-1]
    assert kapu.k7(_mu(ls)) == []  # a puszta térbeli közelség nem bizonyít kapcsolatot
    ls = _cimke_sor(sor_y=100)
    assert kapu.k7(_mu(ls)) == []  # túl messze van
    ls = _cimke_sor()
    ls[0]["allapot"]["vege"][0]["tartalom"] = "Mi lesz az eredmény?"
    assert kapu.k7(_mu(ls)) == []  # a kérdés megelőzheti a választ
    ls = _cimke_sor()
    mas = _o("masik", "keplet", [840, 520, 940, 560], csoport="masik")
    ls[0]["allapot"]["vege"].extend([mas, _o("jel2", "vonal", [840, 570, 940, 570], vonatkozik=["masik"])])
    ls[0]["allapot"]["vege"][0]["doboz"] = [810, 470, 970, 490]
    assert kapu.k7(_mu(ls)) == []  # két egyformán közeli sor: a kapu nem találgat


def test_k7_eltunt_es_ujra_megjeleno_cel():
    cel = _o("cel", "keplet", [800, 400, 900, 440])
    cimke = _o("cimke", "szoveg", [800, 600, 900, 640], vonatkozik=["cel"])
    ls = [_l("s01-01", [cel], megjelenik=[_megj(cel, 0, 10)]),
          _l("s01-02", [], eltunik=[{"obj": "cel", "kocka": 100, "veg_kocka": 110}]),
          _l("s01-03", [cel, cimke], megjelenik=[_megj(cimke, 200, 206), _megj(cel, 230, 240)])]
    assert [(x["lepes"], x["obj"]) for x in kapu.k7(_mu(ls))] == [("s01-03", "cimke")]
    ls[-1]["megjelenik"][0] = _megj(cimke, 240, 246)
    assert kapu.k7(_mu(ls)) == []


@pytest.mark.parametrize("cel,marad,erkezik,vart", [
    pytest.param("sor", True, None, None, id="eltunt-tag-nem-kell"),
    pytest.param("sor", False, None, "sor nincs a képen", id="ures-csoport"),
    pytest.param("sor", True, 350, "uj csak", id="uj-tagot-megvarja"),
    pytest.param("sor", False, 350, "uj csak", id="kesobb-erkezo-csoport"),
    pytest.param("sor", True, 400, None, id="elettartam-hatara"),
    pytest.param("sor", True, 500, None, id="kesoi-tag-nem-kell"),
    pytest.param("sor", False, 500, "sor nincs a képen", id="kesoi-tag-nem-potol"),
    pytest.param("regi", True, None, "regi nincs a képen", id="konkret-eltunt-cel-kell"),
])
def test_k7_csoportnak_csak_az_aktualis_tagjai_kellenek(cel, marad, erkezik, vart):
    """Az egyszerűsítéskor eltűnt tag nem hiány, de az üres csoport és a korai címke lelet."""
    tag = _o("tag", "keplet", [800, 400, 840, 440], csoport="sor")
    regi = _o("regi", "keplet", [850, 400, 890, 440], csoport="sor")
    uj = _o("uj", "keplet", [900, 400, 940, 440], csoport="sor")
    cimke = _o("cimke", "szoveg", [800, 500, 900, 540], vonatkozik=[cel])
    marado = [tag] if marad else []
    elt = [{"obj": o["obj"], "kocka": 130, "veg_kocka": 140} for o in [regi, *([] if marad else [tag])]]
    ls = [_l("s01-01", [tag, regi], megjelenik=[_megj(tag, 0, 10), _megj(regi, 10, 20)]),
          _l("s01-02", marado, eltunik=elt),
          _l("s01-03", [*marado, cimke], megjelenik=[_megj(cimke, 300, 310)])]
    if erkezik is not None:
        ls.append(_l("s01-04", [*marado, uj], megjelenik=[_megj(uj, erkezik, erkezik + 10)],
                     eltunik=[{"obj": "cimke", "kocka": 400, "veg_kocka": 410}]))
    leletek = kapu.k7(_mu(ls))
    if vart is None:
        assert leletek == []
    else:
        assert [(x["lepes"], x["obj"]) for x in leletek] == [("s01-03", "cimke")]
        assert vart in leletek[0]["uzenet"]


@pytest.mark.parametrize("stream,vart", [
    ({"r_frame_rate": "30/1", "nb_frames": "82", "duration": "2.732357"}, False),
    ({"r_frame_rate": "25/1", "nb_frames": "82", "duration": "3.28"}, True),
    ({"r_frame_rate": "30/1", "nb_frames": "82", "duration": "3.28"}, True),
    ({"r_frame_rate": "30/1", "nb_frames": "81", "duration": "2.732357"}, True),
    ({"r_frame_rate": "0/0", "nb_frames": "82", "duration": "2.732357"}, True),
    ({"r_frame_rate": "30/1", "nb_frames": "N/A", "duration": "N/A"}, True),
])
def test_k1_kontener_kerekitese_nem_sebesseghiba(tmp_path, monkeypatch, stream, vart):
    """A valódi regresszió: 82 kocka / 2,732357 s, az átlag 1259520/41969. A hibás fps/hossz továbbra is piros."""
    from types import SimpleNamespace
    mu = kapu.Munka(TESZT)
    index = json.loads((mu.media / "sections" / f"{mu.jelenet}.json").read_text())
    szekcio = next(s for s in index if s["nb_frames"] == "82")
    szekcio.update(avg_frame_rate="1259520/41969", duration="2.732357")
    mu.media = tmp_path
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / f"{mu.jelenet}.json").write_text(json.dumps(index))
    (tmp_path / "sections" / szekcio["video"]).touch()
    eredeti = kapu.subprocess.run

    def probe(args, **kwargs):
        if args[-1] == str(tmp_path / "sections" / szekcio["video"]):
            assert args[0] == "ffprobe"
            return SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [stream]}))
        return eredeti(args, **kwargs)

    monkeypatch.setattr(kapu.subprocess, "run", probe)
    hibak = kapu.k1(mu)
    assert bool(hibak) is vart
    if vart:
        assert len(hibak) == 1 and hibak[0]["kod"] == "K1" and hibak[0]["sulyossag"] == "hiba"


@pytest.mark.parametrize("atlag", ["0/0", "N/A", "", None, "25/1"])
def test_k1_ervenytelen_fps_vagy_hianyzo_szekcio_nem_zold(tmp_path, atlag):
    s = {"name": "s01-01", "nb_frames": "82", "avg_frame_rate": atlag, "video": "nincs.mp4"}
    assert kapu._szekcio_fps(s, tmp_path, 30) is not None
