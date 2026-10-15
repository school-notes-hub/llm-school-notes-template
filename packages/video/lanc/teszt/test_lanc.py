"""A lánc tesztjei (fizetős hívás nélkül). Futtatás:
  uv run --project ../school-notes2 python -m pytest -q lanc/teszt      (a packages/video mappából)
Az elfogadási próba (TesztJelenet → 0, HibasJelenet → 1 a várt kapulistával, összeomlás → 3, hiányzó
bemenet → 2) a video.sh-t futtatja a VIDEO_CSONK=1 csonkkal, kb. 30 s.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from array import array
from decimal import Decimal
from pathlib import Path

import pytest

GYOKER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GYOKER))
from lanc import hangok, szavak as sz  # noqa: E402

TESZT = GYOKER / "videotar-teszt"


@pytest.mark.parametrize("szo,ertek,szor", [
    ("harmincnyolcan", 38, False), ("kétszer", 2, True), ("ötször", 5, True), ("12-szer", 12, True),
    ("hárman", 3, False), ("ketten", 2, False), ("eggyel", 1, False), ("néggyel", 4, False), ("hússzal", 20, False),
    ("nulláról", 0, False), ("fél", 0.5, False), ("2,5", 2.5, False), ("-3", -3, False), ("3-at", 3, False),
    ("ezerkétszáz", 1200, False), ("kétszázhúsz", 220, False), ("hetet", 7, False), ("tizet", 10, False),
    ("egyik", None, False), ("hatás", None, False), ("hátra", None, False), ("egyre", None, False),
    ("harmadik", None, False), ("négyzet", None, False), ("egyenlő", None, False), ("tized", None, False),
])
def test_szamnev(szo, ertek, szor):
    assert sz.egy_szo(szo)[0] == ertek
    if ertek is not None:
        assert sz.egy_szo(szo)[1] is szor


@pytest.mark.parametrize("szoveg,kanon", [
    ("nulla egész öt", ["#0.5"]), ("két egész öt tized", ["#2.5"]), ("három egész huszonöt század", ["#3.25"]),
    ("két és fél méter", ["#2.5", "m"]), ("az eredmény mínusz három", ["az", "eredmeny", "#-3"]),
    ("hat mínusz három", ["#6", "minusz", "#3"]), ("kétszer", ["#2x"]),
])
def test_egysegek(szoveg, kanon):
    assert [u["kanon"] for u in sz.egysegek(szoveg.split())] == kanon


def w(szo, a, b):
    return {"word": " " + szo, "start": a, "end": b}


@pytest.mark.parametrize("szoveg,kanon", [
    ("meg hét: mínusz öt egész négy tized newtonméter", ["meg", "#7", "#-5.4", "nm"]),
    ("Ez hat. Mínusz három a másik.", ["ez", "#6", "#-3", "a", "masik"]),
    ("hat; mínusz három", ["#6", "#-3"]),
    ("hat mínusz három", ["#6", "minusz", "#3"]),                       # írásjel nélkül kivonás marad
    ("Hat plusz öt, mínusz kettő, az kilenc.", ["#6", "plusz", "#5", "minusz", "#2", "az", "#9"]),   # vessző: lánc
    ("{hat}: mínusz kilenc", ["#6", "#-9"]),                            # a horgony utáni kettőspont is határ
])
def test_szamolvaso_irasjellel(szoveg, kanon):
    """A számolvasó megkapja a narráció írásjeleit: mondathatár és kettőspont után a „mínusz” előjel."""
    szavak, jelek, _ = sz.narracio_szavai_jellel(szoveg)
    assert [u["kanon"] for u in sz.egysegek(szavak, jelek)] == kanon
    assert sz.narracio_szavai(szoveg)[0] == szavak


def test_szamolvaso_irasjel_az_illesztesben():
    """„… meg hét: mínusz öt egész négy tized”: a −5,4 a „mínusz” szón áll (az időzítő ehhez köt), Whisper nélkül
    és a kettőspontot hallott Whisperrel is; a Whisper „7:” után a „mínusz 5,4” is −5,4, számeltérés nincs."""
    text = "Mínusz tizenkét egész négy tized, meg hét: mínusz öt egész négy tized newtonméter."
    r = sz.illeszt(text, [], (0.0, 6.0), [])
    assert [(x["szo"], x["ertek"]) for x in r["szavak"] if x["ertek"] is not None] == \
        [("Mínusz", -12.4), ("hét", 7), ("mínusz", -5.4)]
    ws = [w("-12,4,", 0.1, 1.4), w("meg", 1.5, 1.8), w("7:", 1.9, 2.3), w("mínusz", 2.5, 2.9), w("5,4", 3.0, 3.9),
          w("newtonméter.", 4.0, 5.0)]
    r = sz.illeszt(text, ws, (0.1, 5.0), [])
    assert r["szameltérés"] is None
    assert [x["szo"] for x in sz.whisper_szavai([w("6:", 0, 1)])] == ["6"]


@pytest.mark.parametrize("text,szavak", [
    # egész szám: a Whisper vesszőt ír a kettőspont helyett, vagy semmit; a narráció dönt (előjel)
    ("Az erő hat: mínusz kilenc newton.", ["Az", "erő", "6,", "Minusz", "9", "newton."]),
    ("Az erő hat: mínusz kilenc newton.", ["Az", "erő", "6", "mínusz", "9", "newton"]),
    # a Whisper valós írásmódja: „7, Minusz 5 ,4” a tizedes törtre
    ("Mínusz tizenkét egész négy tized, meg hét: mínusz öt egész négy tized newtonméter.",
     ["Minusz", "12", "4,", "meg", "7,", "Minusz", "5", ",4", "newtonméter."]),
    # a narrációban vessző (láncolt művelet), a Whisperben pont: kivonás marad
    ("Hat plusz öt, mínusz kettő, az kilenc.", ["6", "plusz", "5.", "Mínusz", "2,", "az", "9."]),
    ("Hat plusz öt, mínusz kettő, az kilenc.", ["6", "plusz", "5", "mínusz", "2", "az", "9"]),
    # írásjel nélküli kivonás a narrációban, a Whisper kettőspontot ír: kivonás marad
    ("Tizenöt mínusz hat az kilenc.", ["15:", "mínusz", "6", "az", "9."]),
])
def test_szamolvaso_whisper_irasjele_nem_dont(text, szavak):
    """A Whisper saját írásjele nem dönti el a „mínusz” olvasatát: a narrációé dönt, így nincs fizetős újrapróba
    (hangok.szam_hibak üres, ez a kapu K10-szabálya is), egész számnál számeltérés sem."""
    from lanc import hangok
    ws = [w(x, i * 0.5, i * 0.5 + 0.4) for i, x in enumerate(szavak)]
    r = sz.illeszt(text, ws, (0.0, len(szavak) * 0.5), [])
    assert hangok.szam_hibak(r["szavak"]) == [], r["szavak"]
    if "egész" not in text:               # a Whisper a tizedes törtet két számra bontja (az egységsor ott eltér)
        assert r["szameltérés"] is None, r["szameltérés"]


def test_szamolvaso_vegyes_lepes_elofordulasonkent():
    """Egy lépésben kivonás és előjel is: a „mínusz” olvasata előfordulásonként dől el, így a „hat: mínusz egy”
    előjeles egysége a Whisper „minusz 1”-ével egyezik, a kivonások maradnak; nincs számeltérés."""
    from lanc import hangok
    text = "Hét mínusz kettő, öt mínusz négy, hat: mínusz egy."
    szavak = ["7", "minusz", "2,", "5", "minusz", "4,", "6", "minusz", "1."]
    r = sz.illeszt(text, [w(x, i * 0.5, i * 0.5 + 0.4) for i, x in enumerate(szavak)], (0.0, 4.5), [])
    assert r["szameltérés"] is None and hangok.szam_hibak(r["szavak"]) == []


@pytest.mark.parametrize("text,szavak", [
    ("Az erő hat: mínusz kilenc newton.", ["Az", "erő", "6,", "Minusz", "7", "newton."]),     # más szám
    ("Az erő hat: mínusz kilenc newton.", ["Az", "erő", "6,", "plusz", "9", "newton."]),      # más művelet
    ("Az erő hat: mínusz kilenc newton.", ["Az", "erő", "6", "9", "newton."]),                # kimaradt előjel
    ("Hét mínusz kettő, hat: mínusz egy.", ["7", "minusz", "2,", "6", "minusz", "8."]),        # vegyes, más szám
    ("Az eredmény mínusz három.", ["Az", "eredmény", "3."]),                                    # kimaradt előjel
])
def test_szamolvaso_valodi_szamhiba_megmarad(text, szavak):
    """A kétféle olvasat a valódi számhibát nem nyeli el: a hang mást mond, a lánc újrapróbál, a kapu K10-hibát ad."""
    from lanc import hangok
    r = sz.illeszt(text, [w(x, i * 0.5, i * 0.5 + 0.4) for i, x in enumerate(szavak)], (0.0, len(szavak) * 0.5), [])
    assert hangok.szam_hibak(r["szavak"]) != []


def test_whisper_ertek_elojeles_egesz():
    assert [sz.whisper_ertek(x) for x in ("Minusz 9", "mínusz 9", "-9", "9", "4 7", "Minusz 12 4", "-gyel 0 65", "3-at",
                                          "-5 4", "-gyel 6")] == [-9, -9, -9, 9, 4.7, -12.4, 0.65, 3, -5.4, 6]


def test_whisper_muvelet_es_osszevont_szo():
    """A Whisper „17-4”-e három szó, a „kéthalmaz” két szó: a számok nem vesznek el (K10 nem téves)."""
    r = sz.illeszt("Csak úszik tizenhét mínusz négy, vagyis tizenhárom gyerek.",
                   [w("Csak", 0.1, 0.3), w("úszik", 0.35, 0.9), w("17-4,", 1.0, 2.0), w("vagyis", 2.1, 2.4),
                    w("13", 2.5, 2.9), w("gyerek.", 3.0, 3.4)], (0.1, 3.4), [])
    assert r["szameltérés"] is None and all(x["forras"] == "whisper" for x in r["szavak"])
    r = sz.illeszt("Most a két halmaz metszetét rajzoljuk.",
                   [w("Most", 0.1, 0.3), w("a", 0.35, 0.4), w("kéthalmaz", 0.5, 1.4), w("meccetét", 1.5, 2.2),
                    w("rajzoljuk.", 2.3, 2.8)], (0.1, 2.8), [])
    assert r["szameltérés"] is None
    ket = next(x for x in r["szavak"] if x["szo"] == "két")
    assert ket["forras"] == "whisper" and ket["ertek"] == 2 and ket["kezd_s"] == 0.5


def test_illesztes_whisper_becsult_horgony():
    r = sz.illeszt("A {metszet} két egész öt, és kilenc pont.",
                   [w("A", 0.1, 0.2), w("metszet", 0.25, 0.7), w("2,5,", 0.8, 1.5), w("kilenc", 1.9, 2.2),
                    w("pont.", 2.3, 2.6)], (0.1, 2.6), [])
    sz_ = {x["szo"]: x for x in r["szavak"]}
    assert sz_["két"]["ertek"] == 2.5 and sz_["két"]["forras"] == "whisper" and sz_["két"]["kezd_s"] == 0.8
    assert sz_["és"]["forras"] == "becsult" and 1.5 <= sz_["és"]["kezd_s"] < 1.9 and sz_["és"]["whisper"] == ""
    assert r["horgonyok"]["metszet"]["kezd_s"] == 0.25 and r["szameltérés"] is None


def test_tobbszavas_hallott_szam_egy_szoban():
    r = sz.illeszt("Az eredmény mínusz három.", [w("Az", 0, .1), w("eredmény", .1, .5), w("mínusz", .6, .9),
                                                w("három.", .9, 1.2)], (0, 1.2), [])
    k = r["szavak"]
    assert (k[2]["ertek"], k[2]["whisper"], k[2]["kezd_s"]) == (-3, "-3", 0.6) and k[3]["kezd_s"] == 0.9


def test_illesztes_szameltérés_es_gyanus():
    r = sz.illeszt("Kilenc pont maradt.", [w("Hat", 0.9, 1.1), w("pont", 1.2, 1.4), w("maradt.", 1.5, 1.9)],
                   (0.1, 1.9), [[1.1, 1.6]])
    k = r["szavak"]
    assert k[0]["whisper"] == "Hat" and k[0]["forras"] == "gyanus"      # 0,8 s-mal a beszédkezdet után
    assert k[2]["forras"] == "gyanus"                                    # a 1,1–1,6 s-os szünet belsejében
    assert r["szameltérés"] == [[(9, False)], [(6, False)]]


def test_whisper_nelkul_minden_becsult():
    r = sz.illeszt("Ez a halmaz.", [], (0.1, 1.0), [])
    assert [x["forras"] for x in r["szavak"]] == ["becsult"] * 3
    assert r["szavak"][0]["kezd_s"] == 0.1 and r["szavak"][-1]["veg_s"] == 1.0


def test_beszed_szunetek():
    m = array("h", bytes(2 * 24000))
    for a, b in ((2400, 9600), (14400, 20000)):                       # beszéd 0,1–0,4 s és 0,6–0,833 s
        for i in range(a, b):
            m[i] = 300 if i % 2 else -300
    kezd, veg, szun = hangok.beszed_szunetek(m.tobytes())
    assert kezd == 0.1 and abs(veg - 0.84) < 0.011 and szun == [[0.4, 0.6]]


class Ál:
    """Hamis szolgáltató a K10-folyamathoz: a Whisper a `hallott` listából ad, sorban."""
    csonk = True

    def __init__(self, hallott):
        self.hallott, self.tts_keresek, self.whisper_hivas = list(hallott), [], 0
        self.szam = hangok.Szamlalo()

    def tts(self, sid, keres):
        self.tts_keresek.append(keres)
        m = array("h", [300, -300] * 12000)
        return m.tobytes()

    def whisper(self, sid, pcm, proba):
        self.whisper_hivas += 1
        szo = self.hallott.pop(0) if self.hallott else None
        return [w(szo, 0.0, 0.5), w("pont.", 0.6, 0.9)] if szo else None


def test_k10_ujraleiras_javit():
    s = Ál(["Hat", "Kilenc"])
    r = hangok.lepes(s, "a-01", "Kilenc pont.")
    assert r["k10"] == {"ujraleiras": 1} and len(s.tts_keresek) == 1 and r["szameltérés"] is None


def test_k10_uj_tts_tagolt_es_marad():
    s = Ál(["Hat", "Hat", "Hat"])
    r = hangok.lepes(s, "a-01", "Kilenc pont.")
    assert r["k10"]["ujraleiras"] == 1 and r["k10"]["uj_tts"] == 1 and "marad" in r["k10"]
    assert hangok.TAGOLT in s.tts_keresek[1]["instructions"] and len(s.tts_keresek) == 2


def test_k10_szovaltozas_ujraprobal_es_marad():
    """Szóváltozás („számokat” → „sámokat”): újraleírás, aztán új TTS a pontos ejtés kérésével (szám nélkül a
    tagolt mondat nem kell); ha marad, a k10 `szo_marad`-ja mutatja. Ha az újraleírás jó, nincs új TTS."""
    s = Ál(["sámokat", "sámokat", "sámokat"])
    r = hangok.lepes(s, "a-01", "Számokat pont.")
    assert r["k10"] == {"ujraleiras": 1, "uj_tts": 1, "szo_marad": [["Számokat", "sámokat"]]}
    assert hangok.PONTOS in s.tts_keresek[1]["instructions"] and hangok.TAGOLT not in s.tts_keresek[1]["instructions"]
    s = Ál(["sámokat", "számokat"])
    r = hangok.lepes(s, "a-01", "Számokat pont.")
    assert r["k10"] == {"ujraleiras": 1} and len(s.tts_keresek) == 1 and r["szovaltozas"] is None
    s = Ál(["halmaszt"])                                   # kiejtés szerinti írás: nem szóváltozás, nincs újrapróba
    r = hangok.lepes(s, "a-01", "Halmazt pont.")
    assert r["k10"] == {} and s.whisper_hivas == 1


def test_nyugta_k10_ketseges_szo_es_szam():
    import video
    szavak = {"a-01": [{"szo": "a", "kezd_s": 0.1, "ertek": None, "whisper": "az"},
                       {"szo": "számokat", "kezd_s": 0.3, "ertek": None, "whisper": "sámokat"},
                       {"szo": "kilenc", "kezd_s": 0.9, "ertek": 9, "whisper": "hat"}],
              "a-02": [{"szo": "halmazt", "kezd_s": 0.2, "ertek": None, "whisper": "halmaszt"}],
              "a-03": [{"szo": "két", "kezd_s": 0.4, "ertek": 2, "whisper": None},
                       {"szo": "kör", "kezd_s": 0.7, "ertek": None, "whisper": None}]}
    terv = {"a-01": {"hang_kezd_s": 10.0}, "a-02": {"hang_kezd_s": 20.0}, "a-03": {"hang_kezd_s": 30.0}}
    assert [(x["lepes"], x["ido_s"], x["fajta"], x["szo"], x["whisper"]) for x in video.k10_ketseges(szavak, terv)] == [
        ("a-01", 10.1, "szo", "a", "az"), ("a-01", 10.3, "szo", "számokat", "sámokat"),
        ("a-01", 10.9, "szam", "kilenc", "hat"), ("a-03", 30.4, "nincs_szo", "két kör", None)]


def test_whisper_ujraprobalas_szo_nelkul():
    s = Ál([None, None, "Kilenc"])
    r = hangok.lepes(s, "a-01", "Kilenc pont.")
    assert s.whisper_hivas == 3 and r["van_szoido"] and not r["k10"]


def test_videokeret(tmp_path):
    from school_notes2.podcast.ledger import Ledger, PodcastSettings
    st = PodcastSettings(learner="teszt", state_root=tmp_path / "podcast", lock_path=tmp_path / "podcast.lock",
                         key_file=tmp_path / ".env", music=tmp_path / "zene.mp3", monthly_usd=Decimal("13"))
    v = object.__new__(hangok.Valodi)
    v.tanulo, v.epizod, v.settings, v.client = "teszt", "video/matek/halmazok-1", st, None
    v.paid, v.szam, v.futas_keret = None, hangok.Szamlalo(), hangok.KERET_TOVABBI
    v._szalak_init()
    hosszu = hangok.tts_keres("a" * 20000)                       # foglalás kb. 0,63 USD > 0,5
    with v.fizetos([hosszu]):
        assert v.futas_keret == hangok.KERET_ELSO
        with pytest.raises(hangok.Megallt, match="futáskeret"):
            v.tts("s01-01", hosszu)
    led = Ledger(st)
    led.value["calls"].append({"kind": "speech", "learner": "teszt", "episode": "video/matek/halmazok-1",
                               "request_sha256": "x", "started_at": "2026-10-13T10:00:00+02:00", "state": "ok",
                               "reserved_usd": 0.95, "cost_usd": 0.95})
    led.save()
    kozepes = hangok.tts_keres("b" * 3000)                       # kb. 0,095 USD: a futásba fér, a videóba nem
    with v.fizetos([kozepes]):
        with pytest.raises(hangok.Megallt, match="videókeret"):
            v.tts("s01-01", kozepes)


# --- párhuzamos hanglépés: sorrend, keret, rövid zár ---------------------------------------------

def test_parhuzamos_sorrend_es_elso_hiba():
    import random
    import time as t

    def fv(i):
        t.sleep(random.random() / 200)
        if i in (7, 3):
            raise ValueError(i)
        return i * i
    assert hangok.parhuzamos(lambda i: (t.sleep(random.random() / 200), i * i)[1], list(range(40))) == \
        [i * i for i in range(40)]
    with pytest.raises(ValueError, match="^3$"):
        hangok.parhuzamos(fv, list(range(40)))


def _kimenet(mappa: Path) -> dict:
    return {str(f.relative_to(mappa)): f.read_bytes() for f in sorted(mappa.rglob("*")) if f.is_file()}


def test_csonk_parhuzamos_azonos_a_sorossal(tmp_path, monkeypatch):
    narr = json.loads((TESZT / "hibasjelenet" / "narracio.json").read_text(encoding="utf-8"))
    ki = {}
    for n in (1, 6):
        monkeypatch.setattr(hangok, "PARHUZAMOS", n)
        m = tmp_path / f"p{n}"
        m.mkdir()
        with open(m / "log.txt", "w") as log:
            hangok.hang_es_szavak(m, narr, hangok.Csonk(narr), log)
        (m / "log.txt").unlink()
        ki[n] = _kimenet(m)
    assert ki[1] == ki[6] and "szavak.json" in ki[1]


class ÁlKliens:
    """Hamis OpenRouter-kliens: véletlen késleltetés, a TTS-hang a kérésből számolt, a Whisper egy szót
    hall (szóváltozás → K10-ág). Minden hívásnál feljegyzi, fogja-e valaki a podcast.lock-ot."""

    def __init__(self, zar_ut: Path):
        self.zar_ut, self.zar_foglalt, self.hivas = zar_ut, [], 0

    def post(self, url, payload):
        import fcntl
        import hashlib
        import random
        import time as t
        from school_notes2.podcast.openrouter import Answer
        fd = os.open(self.zar_ut, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.zar_foglalt.append(False)
        except BlockingIOError:
            self.zar_foglalt.append(True)
        finally:
            os.close(fd)
        self.hivas += 1
        t.sleep(random.random() / 50)
        h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).digest()
        if "input_audio" not in payload:
            m = array("h", [(h[i % 32] - 128) * 40 * (1 if i % 7 < 4 else -1) for i in range(30000)])
            return Answer(200, {"content-type": "audio/pcm", "x-generation-id": "g-" + h.hex()[:8]}, m.tobytes())
        return Answer(200, {}, json.dumps({"id": "w-" + h.hex()[:8], "usage": {"cost": 0.0001},
                                           "words": [w("kutya", 0.1, 0.6)]}).encode())


def _valodi(tmp_path: Path, **beall):
    from school_notes2.podcast.ledger import PodcastSettings
    st = PodcastSettings(learner="teszt", state_root=tmp_path / "podcast", lock_path=tmp_path / "podcast.lock",
                         key_file=tmp_path / ".env", music=tmp_path / "zene.mp3", **beall)
    v = object.__new__(hangok.Valodi)
    v.tanulo, v.epizod, v.settings, v.client = "teszt", "video/matek/halmazok-1", st, ÁlKliens(st.lock_path)
    v.paid, v.szam, v.futas_keret = None, hangok.Szamlalo(), hangok.KERET_TOVABBI
    v._szalak_init()
    return v


NARR = [{"id": "s01", "lepesek": [{"text": f"A {i}. lépés: két halmaz közös része."} for i in range(1, 7)]
         + [{"text": "A 1. lépés: két halmaz közös része."}]},       # ismétlődő kérés: egyszer fizetünk
        {"id": "s02", "lepesek": [{"text": f"Unió, {i}. példa."} for i in range(1, 6)]}]


def test_valodi_parhuzamos_azonos_a_sorossal(tmp_path, monkeypatch):
    ki, hivas = {}, {}
    for n in (1, 6):
        monkeypatch.setattr(hangok, "PARHUZAMOS", n)
        v = _valodi(tmp_path / f"a{n}")
        v.csonk = True                                   # a hang.wav összefűzése (ffmpeg) itt nem kell
        m = tmp_path / f"p{n}"
        m.mkdir()
        hs = hangok.hang_es_szavak(m, NARR, v, None)
        ki[n] = _kimenet(m)
        led = json.loads(v.settings.ledger_path.read_text(encoding="utf-8"))["calls"]
        assert all(c["state"] == "ok" for c in led)
        assert n > 1 or not any(v.client.zar_foglalt)   # sorosan: a válaszra várás alatt senki sem fogja
        hivas[n] = (v.client.hivas, sorted((c["kind"], c["request_sha256"], c["reserved_usd"]) for c in led),
                    hs["k10"], hs["szam"])
    assert ki[1] == ki[6] and hivas[1] == hivas[6]
    assert hivas[1][3].uj_tts == len({l["text"] for j in NARR for l in j["lepesek"]}) * 2   # + a K10 pontos TTS


def test_valodi_parhuzamos_keret_megall(tmp_path, monkeypatch):
    monkeypatch.setattr(hangok, "PARHUZAMOS", 6)
    v = _valodi(tmp_path)
    narr = [{"id": "s01", "lepesek": [{"text": f"{i}. " + "hosszú mondat " * 150} for i in range(30)]}]
    m = tmp_path / "v"
    m.mkdir()
    with pytest.raises(hangok.Megallt, match="futáskeret"):
        hangok.hang_es_szavak(m, narr, v, None)
    from school_notes2.podcast.ledger import Ledger
    led = Ledger(v.settings)
    assert v.futas_keret == hangok.KERET_ELSO
    assert sum(Ledger.cost(c) for c in v.paid.opened) <= hangok.KERET_ELSO
    assert led.episode_cost(v.epizod, "teszt") <= hangok.KERET_ELSO
    assert len(led.value["calls"]) == len(v.paid.opened) and all(c["state"] != "sent" for c in led.value["calls"])


def test_zar_nincs_fogva_gyorsitotarbol_es_valaszvaraskor(tmp_path):
    from school_notes2.images.budget import images_lock
    v = _valodi(tmp_path, lock_timeout_s=1)
    keres = hangok.tts_keres("Gyorsítótárból jön.")
    with v.fizetos([keres]):
        pcm = v.tts("s01-01", keres)                     # fizetős: a válaszra várás alatt nincs zár
    assert v.client.zar_foglalt == [False]
    with images_lock(v.settings.lock_path, 5, what="podcast"):     # más folyamat fogja a zárat
        with v.fizetos([keres]):
            assert v.tts("s01-01", keres) == pcm         # gyorsítótárból: nem vár a zárra (különben LockTimeout)
            with pytest.raises(TimeoutError, match="lock busy"):
                v.whisper("s01-01", pcm, 0)              # fizetős: a foglaláshoz kell a zár
    assert v.client.hivas == 1


def test_k10_whisper_tizedes_nem_kell_ujra():
    """A Whisper szóidős listája a tizedesvesszőt elhagyja („4 7”): ez 4,7, nem számeltérés (a kapuval egyezően)."""
    class Tizedes(Ál):
        def whisper(self, sid, pcm, proba):
            self.whisper_hivas += 1
            return [w("A", 0.0, 0.1), w("4", 0.2, 0.4), w("7", 0.5, 0.7), w("méter.", 0.8, 1.0)]
    s = Tizedes([])
    r = hangok.lepes(s, "a-01", "A négy egész hét tized méter.")
    assert r["k10"] == {} and r["szamhiba"] == [] and len(s.tts_keresek) == 1 and s.whisper_hivas == 1
    assert hangok.szam_hibak([{"szo": "négy", "ertek": 4.7, "whisper": "4 7"}]) == []
    assert hangok.szam_hibak([{"szo": "négy", "ertek": 4.7, "whisper": "4 8"}]) == [["négy", "4 8"]]


def test_sigterm_megallit_es_a_sorban_allok_nem_indulnak():
    import signal
    import threading as th
    import time as t
    indult = []

    def fv(i):
        indult.append(i)
        t.sleep(0.05)
        return i
    th.Timer(0.12, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    with pytest.raises(hangok.Megallt, match="SIGTERM"):
        hangok.parhuzamos(fv, list(range(40)), 2)
    assert len(indult) < 12 and signal.getsignal(signal.SIGTERM) is not None


def _ledger(v) -> list:
    return json.loads(v.settings.ledger_path.read_text(encoding="utf-8"))["calls"]


def test_zaras_zar_nelkul_fuggo_es_a_vegen_kiirodik(tmp_path, monkeypatch):
    """Ha a válaszra várás alatt más fogja a zárat (lejár a várakozás), a zárás függő lesz, a `fizetos`
    végén íródik ki: nem marad `sent` bejegyzés."""
    import fcntl
    import threading as th
    import time as t
    monkeypatch.setattr(hangok, "ZARAS_VARAS_S", 0.1)
    v = _valodi(tmp_path, lock_timeout_s=0.5)
    engedd, fogva = th.Event(), th.Event()
    eredeti = v.client.post

    def tarto():
        fd = os.open(v.settings.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        fogva.set()
        engedd.wait()
        os.close(fd)

    def post(url, payload):
        th.Thread(target=tarto).start()
        fogva.wait()
        return eredeti(url, payload)
    v.client.post = post
    keres = hangok.tts_keres("Más fogja a zárat.")
    with v.fizetos([keres]):
        t0 = t.monotonic()
        v.tts("s01-01", keres)                           # a zárás csak ZARAS_VARAS_S-ig vár, aztán függő
        assert t.monotonic() - t0 < 0.4
        assert [c["state"] for c in _ledger(v)] == ["sent"] and len(v._fuggo) == 1
        with pytest.raises(TimeoutError):               # a foglalás lock_timeout_s-ig vár, aztán lejár
            v.tts("s01-02", hangok.tts_keres("Másik mondat."))
        t0 = t.monotonic()
        with pytest.raises(TimeoutError):               # lejárt zár után az új foglalás nem vár újra
            v.tts("s01-03", hangok.tts_keres("Harmadik mondat."))
        v.paid.ledger.close(v.paid.opened[0], "ok")     # lejárt zár után a zárás azonnal függő
        assert t.monotonic() - t0 < 0.05 and len(v._fuggo) == 2
        engedd.set()
    assert [c["state"] for c in _ledger(v)] == ["ok"] and not v._fuggo


def test_masik_folyamat_uton_varunk_a_valaszra(tmp_path, monkeypatch):
    """Ugyanezt a kérést egy másik folyamat épp küldi (friss `sent`): várunk, és a gyorsítótárból kapjuk;
    ha a várakozás alatt nem jön meg, fizetünk."""
    import threading as th
    from school_notes2.log import now_iso
    from school_notes2.podcast.ledger import Ledger, request_sha
    monkeypatch.setattr(hangok, "MASIK_VAR_S", 3.0)
    v = _valodi(tmp_path)
    keres, keres2 = hangok.tts_keres("Közös mondat."), hangok.tts_keres("Senki sem küldi.")
    pcm = array("h", [300, -300] * 12000).tobytes()
    led = Ledger(v.settings)
    for k in (keres, keres2):
        led.value["calls"].append({"kind": "speech", "learner": "masik", "episode": "video/x/y", "state": "sent",
                                   "request_sha256": request_sha(k), "started_at": now_iso(),
                                   "reserved_usd": 0.01, "cost_usd": None})
    led.save()
    with v.fizetos([keres]):
        th.Timer(0.3, lambda: v.paid.cache.put_audio(request_sha(keres), pcm, {"kind": "speech"})).start()
        assert v.tts("s01-01", keres) == pcm and v.client.hivas == 0 and v.szam.uj_tts == 0
        monkeypatch.setattr(hangok, "MASIK_VAR_S", 0.2)
        v.tts("s01-02", keres2)
    assert v.client.hivas == 1 and len(_ledger(v)) == 3


def test_konyveles_zar_alatt_friss_ledgerre(tmp_path):
    """--meres könyvelése: a lekérdezés zár nélkül, a mentés a zár alatt friss ledgerre; a közben más által
    írt bejegyzés megmarad, csak a saját díj íródik be."""
    import fcntl
    from school_notes2.podcast.ledger import Ledger
    v = _valodi(tmp_path)
    led = Ledger(v.settings)
    alap = {"kind": "speech", "learner": "teszt", "state": "ok", "reserved_usd": 0.05, "cost_usd": None}
    led.value["calls"] += [{**alap, "episode": v.epizod, "request_sha256": "a", "started_at": "2026-10-14T01:00:00+02:00",
                            "generation_id": "g-a"},
                           {**alap, "episode": v.epizod, "request_sha256": "b", "started_at": "2026-10-14T01:00:01+02:00",
                            "generation_id": "g-b"}]
    led.save()
    szabad = []

    class Kliens:
        def generation_cost(self, gid):
            fd = os.open(v.settings.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                szabad.append(True)
            finally:
                os.close(fd)
            masik = Ledger(v.settings)               # közben egy párhuzamos lánc foglal
            masik.value["calls"].append({**alap, "episode": "video/x/y", "request_sha256": gid, "state": "sent",
                                         "started_at": "2026-10-14T01:00:02+02:00", "generation_id": None})
            masik.save()
            return 0.01 if gid == "g-a" else None
    sajat, maradt = hangok.konyvel(v.settings, Kliens(), v.epizod, "teszt", sleep=lambda s: None, korok=2)
    calls = Ledger(v.settings).value["calls"]
    assert maradt == 1 and len(sajat) == 2 and all(szabad)
    assert [c.get("cost_usd") for c in calls[:2]] == [0.01, None]
    assert [c["request_sha256"] for c in calls[2:]] == ["g-a", "g-b", "g-b"]


def test_whisper_4xx_egy_bejegyzes_es_atmeneti_hiba_megallit(tmp_path):
    from school_notes2.state.errors import NeedsOwner, Transient
    v = _valodi(tmp_path)
    pcm = array("h", [300, -300] * 12000).tobytes()
    with v.fizetos([]):
        def rossz(url, payload):
            raise NeedsOwner("OpenRouter: HTTP 400: rossz kérés")
        v.client.post = rossz
        with pytest.raises(NeedsOwner):
            v.whisper("s01-01", pcm, 0)
        assert [(c["kind"], c["state"]) for c in _ledger(v)] == [("transcription", "failed")]

        def atmeneti(url, payload):
            raise Transient("OpenRouter: HTTP 503")
        v.client.post = atmeneti
        with pytest.raises(Transient):                  # nem üres válasz: nem fogyaszt Whisper-próbát
            hangok.szoidok(v, "s01-01", pcm)
        assert len(_ledger(v)) == 2


def test_foglalaskor_mar_gyorsitotarban_nem_fizet(tmp_path):
    """Két lánc ugyanazt a kérést: amelyik a zár alatt már a gyorsítótárban találja, nem fizet érte."""
    from school_notes2.podcast.ledger import request_sha
    v = _valodi(tmp_path)
    keres = hangok.tts_keres("Közös mondat.")
    pcm = array("h", [300, -300] * 12000).tobytes()
    with v.fizetos([keres]):
        cache, eredeti = v.paid.cache, v.paid.cache.audio
        hivas = []

        def audio(sha):                                  # az első két olvasáskor még nincs ott
            hivas.append(sha)
            if len(hivas) == 2:
                cache.put_audio(request_sha(keres), pcm, {"kind": "speech"})
            return None if len(hivas) <= 2 else eredeti(sha)
        cache.audio = audio
        assert v.tts("s01-01", keres) == pcm
    assert v.client.hivas == 0 and v.szam.uj_tts == 0 and not (v.settings.ledger_path.exists() and _ledger(v))


def test_figyelmeztetesek_lepes_szerint(tmp_path, monkeypatch):
    from school_notes2.podcast.ledger import Ledger, request_sha
    monkeypatch.setattr(hangok, "PARHUZAMOS", 4)
    v = _valodi(tmp_path)
    led = Ledger(v.settings)
    for j in reversed(NARR):
        for l in reversed(j["lepesek"][:3]):
            led.value["calls"].append({"kind": "speech", "learner": "teszt", "episode": "más", "state": "sent",
                                       "request_sha256": request_sha(hangok.tts_keres(hangok.proba_hang.tts_szoveg(l["text"]))),
                                       "started_at": "2026-10-13T10:00:00+02:00", "reserved_usd": 0.01, "cost_usd": None})
    led.save()
    v.csonk = True
    m = tmp_path / "v"
    m.mkdir()
    hangok.hang_es_szavak(m, NARR, v, None)
    f = v.kesz()["figyelmeztetes"]
    assert [x.split(":")[0] for x in f] == ["s01-01", "s01-02", "s01-03", "s02-01", "s02-02", "s02-03"]   # s01-07 = s01-01: gyorsítótárból


# --- elfogadási próba: a teljes lánc a csonkkal --------------------------------------------------

CIMEK = ("--cim", "A négy halmazművelet", "--tantargy-nev", "Teszt")


def lanc(mappa: Path, *extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, VIDEO_CSONK="1")
    return subprocess.run([str(GYOKER / "video.sh"), "teszt", "teszt", f"{mappa.name}-1", "--mappa", str(mappa),
                           *extra], capture_output=True, text=True, env=env, timeout=600)


def masol(tmp_path: Path, nev: str) -> Path:
    m = tmp_path / nev
    m.mkdir()
    for n in ("narracio.json", "jelenetek.py", "kezi.json"):
        if (TESZT / nev / n).exists():
            shutil.copy(TESZT / nev / n, m / n)
    return m


def test_tesztjelenet_zold(tmp_path):
    m = masol(tmp_path, "tesztjelenet")
    p = lanc(m)
    assert p.returncode == 0, p.stdout
    assert len(p.stdout.splitlines()) <= 30 and "KAPU: ZÖLD" in p.stdout
    elvart = json.loads((TESZT / "tesztjelenet" / "idoterv.json").read_text()) \
        if (TESZT / "tesztjelenet" / "idoterv.json").exists() else None
    if elvart:                                                    # a szintetikus.py-éval kockára azonos terv
        assert json.loads((m / "idoterv.json").read_text())["kocka_osszes"] == elvart["kocka_osszes"]
    # az író futása kontaktlapot is ad (a lektoréval azonos kockák, sűrű 4×4-es lapon); a lábsor megadja az útját
    sor = next(x for x in p.stdout.splitlines() if x.startswith("kontaktlapok "))
    assert f"{m / 'lapok-iro'}/" in sor and "10. és 12. szabály" in sor
    from PIL import Image
    iro = sorted((m / "lapok-iro").iterdir())
    assert iro and all(Image.open(x).size[0] <= 1920 and Image.open(x).size[1] <= 1160 for x in iro)
    assert sum(1 for _ in iro) == -(-int(sor.split(" lap, ")[1].split()[0]) // 16)    # teli lapok
    elotte = {n: (m / n).read_bytes() for n in ("szavak.json", "idoterv.json", "hangido.json", "kapu.json")}
    elotte.update({f"lapok-iro/{x.name}": x.read_bytes() for x in iro})
    assert lanc(m).returncode == 0
    assert elotte == {n: (m / n).read_bytes() for n in elotte}    # determinisztikus
    naplo = (m / "render_naplo.json").read_bytes()
    p = lanc(m, "--kivagat", "t01-05/szamlalo")                   # az író állóképe a naplót nem írja felül
    assert p.returncode == 0 and (m / "kivagat" / "iro-t01-05-szamlalo.png").exists(), p.stdout
    assert (m / "render_naplo.json").read_bytes() == naplo


def test_hibasjelenet_piros_a_vart_leletekkel(tmp_path):
    m = masol(tmp_path, "hibasjelenet")
    p = lanc(m)
    assert p.returncode == 1, p.stdout
    assert "K10     számeltérés/szóváltozás 1 lépésben: újraleírás 1, új TTS 1; maradt: h01-15" in p.stdout
    van = [(x["lepes"], x["kod"], x["sulyossag"]) for x in json.loads((m / "kapu.json").read_text())["leletek"]]
    vart = [(x["lepes"], x["kod"], x["sulyossag"])
            for x in json.loads((TESZT / "hibasjelenet" / "elvart-kapu.json").read_text())["leletek"]]
    assert van == vart


def test_osszeomlas_3_rovid_kivonattal(tmp_path):
    m = masol(tmp_path, "tesztjelenet")
    kod = (m / "jelenetek.py").read_text()
    (m / "jelenetek.py").write_text(re.sub(r"(\n    def jelenet_\w+\(self\):\n)", r'\1        x = {"a": 1}["b"]\n',
                                           kod, count=1))
    p = lanc(m)
    assert p.returncode == 3 and "kivétel: KeyError: 'b'" in p.stdout and "jelenetek.py:" in p.stdout
    kivonat = p.stdout.split("render-összeomlás")[1].splitlines()
    assert len(kivonat) <= 15


def test_hianyzo_bemenet_2(tmp_path):
    m = tmp_path / "ures"
    m.mkdir()
    p = lanc(m)
    assert p.returncode == 2 and "hiányzó bemenet" in p.stdout


def test_mappa_csak_csonkkal(tmp_path):
    p = subprocess.run([str(GYOKER / "video.sh"), "teszt", "teszt", "x-1", "--mappa", str(tmp_path)],
                       capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "VIDEO_CSONK"})
    assert p.returncode == 2 and "csonk" in p.stdout


# --- a kódreview (1–3. lépés) leletei ------------------------------------------------------------

def test_betunev_kotojel_es_ketiranyu_szohatar():
    """F6: „Zé” = Whisper „Z-elem” első fele, „elemszáma” = „elem száma” (összevonás), „kéthalmaz” = „két
    halmaz” (bontás): mind Whisper-idő, egyik sem becsült."""
    r = sz.illeszt("Zé elemszáma most tizenhét.", [w("Z-elem", 0.1, 0.9), w("száma,", 0.95, 1.3),
                                                   w("most", 1.35, 1.7), w("17.", 1.8, 2.2)], (0.1, 2.2), [])
    assert [x["forras"] for x in r["szavak"]] == ["whisper"] * 4 and r["szameltérés"] is None
    assert r["szavak"][1]["kezd_s"] < 0.95 and r["szavak"][1]["veg_s"] == 1.3      # „elem” + „száma”
    r = sz.illeszt("A halmazjelekkel írjuk.", [w("A", 0.1, 0.2), w("halmaz", 0.3, 0.8), w("jelekkel", 0.8, 1.3),
                                               w("írjuk.", 1.4, 1.8)], (0.1, 1.8), [])
    assert [x["forras"] for x in r["szavak"]] == ["whisper"] * 3 and r["szavak"][1]["kezd_s"] == 0.3
    # elírt szóhatár szám nélkül, közel azonos összefűzött alakkal: a sáv Whisper-idő; eltérő szó becsült marad
    r = sz.illeszt("Körbe zárt metszet elemeit.", [w("Körbezár", 0.1, 0.9), w("meccetelemeit.", 1.0, 2.0)],
                   (0.1, 2.0), [])
    assert [x["forras"] for x in r["szavak"]] == ["whisper"] * 4 and 0.8 < r["szavak"][2]["kezd_s"] <= 1.0
    r = sz.illeszt("Körbe zárt kutyák.", [w("Macska", 0.1, 0.9), w("kutyák.", 1.0, 2.0)], (0.1, 2.0), [])
    assert [x["forras"] for x in r["szavak"]] == ["becsult", "becsult", "whisper"]
    # a betűnév mindkét oldalon ugyanígy normalizál: „és” és „de” nem betű, „há” igen
    assert (sz.betu("Zé"), sz.betu("Z"), sz.betu("há"), sz.betu("és"), sz.betu("de")) == ("z", "z", "h", "es", "de")


def test_valtozott_szavak_hangalak():
    """A kiejtésben egybeeső írás zaj, a kiejtett szó változása (egy betű is) nem."""
    assert sz.hangalak("halmazt") == sz.hangalak("halmaszt")
    assert sz.hangalak("metszet") == sz.hangalak("meccet") == sz.hangalak("medszet") == sz.hangalak("metzet")
    assert sz.hangalak("egyszer") == sz.hangalak("eccer") and sz.hangalak("hosszú") != sz.hangalak("hoszú")
    assert sz.hangalak("az", "szerint") == sz.hangalak("asszerint")      # szóhatáron nincs hamis „zs”
    assert sz.hangalak("számokat") != sz.hangalak("sámokat")
    assert sz.hangalak("mínusz") == sz.hangalak("minusz") and sz.hangalak("lyuk") == sz.hangalak("juk")

    def v(a, b):
        return [(x["szo"], x["hallott"]) for x in sz.valtozott_szavak(a, b)]
    assert v(["a", "számokat"], ["a", "sámokat"]) == [("számokat", "sámokat")]
    # F2: minőségi különbség (o/ö, e/é, a/á), o/ó–ö/ő hossz, magánhangzók közti hosszú mássalhangzó: lelet
    for a, b in (("kör", "kor"), ("kell", "kel"), ("szél", "szel"), ("tört", "tőrt"), ("ház", "haz")):
        assert v(["a", a, "pont"], ["a", b, "pont"]) == [(a, b)], (a, b)
    # F3: egyenlő hosszú, több szót érintő csere szavanként; eltérő szószám és eltolt szóhatár zaj
    assert v(["Írd", "a", "számokat"], ["Írd", "az", "sámokat"]) == [("a", "az"), ("számokat", "sámokat")]
    assert v(["vízszintes", "efnek"], ["vízszintes", "f", "nek"]) == []
    assert v(["zé", "pont"], ["Z", "pont"]) == []
    assert v(["tizenöt", "kör"], ["15", "kör"]) == []           # a számot a K10 értékkel nézi
    assert v(["min", "játszanak"], ["miniátszanak"]) == []       # eltérő szószám: szóhatár-zavar
    assert v(["min", "játszanak", "aszerint"], ["miniátszanak", "az", "szerint"]) == []   # eltolt szóhatár
    assert v(["halmaz", "az"], ["halma", "az"]) == [("halmaz", "halma")]
    assert v(["körbe", "zárt"], ["kör", "bezárt"]) == []        # eltolt szóhatár, egybefűzve azonos


@pytest.mark.parametrize("nev,jel", [
    ("newton", "N"), ("nyúton", "N"), ("newtonméter", "Nm"), ("newtonméter", "N·m"), ("nyutonméter", "Nm"),
    ("kilonewtonméter", "kNm"), ("kilonewtonméter", "kN·m"), ("kilonyútonméter", "kNm"), ("kilonewton", "kN"),
    ("newtonméteres", "Nm-es"), ("kilonewtont", "kN-t"), ("kilonewtonban", "kN-ban"), ("newtonnal", "N-nal"),
    ("kilogrammal", "kg-mal"), ("méterrel", "m-rel"), ("métert", "m-t"), ("méter", "m"), ("centiméter", "cm"),
    ("milliméter", "mm"), ("kilogramm", "kg"), ("gramm", "g"), ("tonna", "t"), ("másodperc", "s"),
    ("szekundum", "s"), ("pascal", "Pa"), ("kilopascal", "kPa"), ("megapascal", "MPa"), ("joule", "J"),
    ("watt", "W"), ("fok", "°"), ("fokos", "°-os"), ("négyzetméter", "m²"), ("köbcentiméter", "cm³"),
    ("méter per szekundum", "m/s"), ("méter per szekundumnégyzet", "m/s²"), ("méter per másodpercnégyzet", "m/s2"),
    ("kilométer per óra", "km/h"), ("kilowattóra", "kWh"), ("en", "N"), ("em", "m")])
def test_mertekegyseg_neve_es_jele_egyezik(nev, jel):
    """A kimondott mértékegység és a Whisper jele (toldalékkal, összetett egységgel) ugyanaz a kulcs."""
    assert sz.betu(nev) == sz.betu(jel) and sz._alak(nev) == sz._alak(jel)


@pytest.mark.parametrize("a,b", [
    ("newton", "kN"), ("newton", "kilonewton"), ("kilonewton", "N"), ("newton", "Nm"), ("newtonméter", "N"),
    ("newtonméter", "kNm"), ("méter", "cm"), ("méter", "centiméter"), ("centiméter", "mm"), ("gramm", "kg"),
    ("kilopascal", "MPa"), ("megapascal", "mPa"), ("méter", "m²"), ("m/s", "m/s²"), ("kN-t", "kN"),
    ("newtonméteres", "Nm-t"), ("fok", "fokozat")])
def test_mertekegyseg_mas_egyseg_mas(a, b):
    """Más egység (vagy más toldalék) más kulcs: a K10 ezt továbbra is jelzi."""
    assert sz.betu(a) != sz.betu(b) and sz._alak(a) != sz._alak(b)


def test_mertekegyseg_k10():
    """A Whisper jellel írt egysége nem szóváltozás és nem karakteres eltérés; más egység lelet marad."""
    def v(a, b):
        return [(x["szo"], x["hallott"]) for x in sz.valtozott_szavak(a.split(), b.split())]
    for n, h in (("Három newton erő két méteres karon hat newtonméter forgatónyomatékot okoz",
                  "3 N erő 2 méteres karon 6 Nm forgatónyomatékot okoz"),
                 ("Kilonewtonban mért erő és méterben mért kar szorzata kilonewtonméter",
                  "Kilonyútonban mért erő és méterben mért kar szorzata kilonyútonméter"),
                 ("Három kilonewtonméter tehát háromezer newtonméter", "3 kNm tehát 3000 Nm"),
                 ("a nyomaték öt newtonméteres", "a nyomaték 5 Nm-es"),
                 ("tíz kilonewtont mérünk", "10 kN-t mérünk"),
                 ("az autó sebessége húsz méter per szekundum", "az autó sebessége 20 m/s"),
                 ("harminc fokos szög", "30°-os szög")):
        whisper = [x["szo"] for x in sz.whisper_szavai([{"word": h, "start": 0, "end": 1}])]
        assert v(n, " ".join(whisper)) == [] and sz.elteres(n.split(), whisper) == 0, (n, h)
    assert v("két kilonewton kétezer newton", "2 kN 2000 Nm") == [("newton", "Nm")]
    assert v("öt newton erő", "5 kN erő") == [("newton", "kN")]
    assert v("két méteres rúd", "két centiméteres rúd") == [("méteres", "centiméteres")]
    assert v("két méteres rúd", "2 cm-es rúd") == [("méteres", "cm-es")]
    assert v("két méteres erőkaron", "két méteres erőkoron") == [("erőkaron", "erőkoron")]
    assert v("az en halmaz", "az N halmaz") == [] and v("Z elem", "Z elem") == []
    # a kötőjeles jel a toldalékával egy szó, a betű és a szó közti kötőjel szóhatár marad
    assert [x["szo"] for x in sz.whisper_szavai([{"word": "kN-t Z-elem 30°-os 5kN 12-szer", "start": 0,
                                                 "end": 1}])] == ["kN-t", "Z", "elem", "30", "°-os", "5", "kN",
                                                                  "12-szer"]
    r = sz.illeszt("Egy newtonméter nyomaték.", [w("1", 0.1, 0.3), w("Nm", 0.3, 0.8), w("nyomaték.", 0.9, 1.5)],
                   (0.1, 1.5), [])
    assert [x["forras"] for x in r["szavak"]] == ["whisper"] * 3 and r["szovaltozas"] is None
    assert r["szavak"][1]["whisper"] == "Nm" and r["szameltérés"] is None


def test_k10_elteres_karakteres():
    """F6: a K10 eltérése a két oldal összefűzött egyeztető alakján, karakterenként (nem szószámra)."""
    assert sz.elteres(["Zé", "elemszáma"], ["Z", "elem", "száma"]) == 0
    assert sz.elteres(["tizenöt", "elem"], ["15", "elem"]) == 0
    assert sz.elteres(["min", "játszanak", "aszerint"], ["miniátszanak", "az", "szerint"]) < 0.2
    assert sz.elteres(["a", "kutya", "ugat"], ["a", "macska", "nyávog"]) > 0.5


def test_csonk_csak_mappa_mellett(tmp_path):
    """F3: VIDEO_CSONK=1 a valódi munkamappán megáll (a csonk nem írhat szintetikus hangot a tanulói mappába)."""
    p = subprocess.run([str(GYOKER / "video.sh"), "teszt", "teszt", "x-1"], capture_output=True, text=True,
                       env=dict(os.environ, VIDEO_CSONK="1"), timeout=120)
    assert p.returncode == 2 and "csak --mappa mellett" in p.stdout


def test_mellekagak_kodja_2(tmp_path):
    """F7: sérült futasok.json a --kivagat-nál és a láncban: 2-es kód, traceback nélkül."""
    m = tmp_path / "ures"
    m.mkdir()
    (m / "futasok.json").write_text("{sérült")
    p = lanc(m, "--kivagat", "t01-01/x")
    assert p.returncode == 2 and "MEGÁLLT" in p.stdout and "Traceback" not in p.stdout + p.stderr
    p = lanc(m)
    assert p.returncode == 2 and "futásnapló" in p.stdout and "Traceback" not in p.stdout + p.stderr


def test_vegleges_itelethez_kotve_k8a_tmp_fajlon(tmp_path, monkeypatch):
    """F2: a --vegleges csak egyező kulcsú accept ítélettel és változatlan bemenettel fut, különben 2;
    az --atadas új kulcsnál a régi ítéletet félreteszi. F11: K8a-bukáskor nem marad mp4 a végleges helyen."""
    import kapu
    import video
    m = masol(tmp_path, "tesztjelenet")
    assert lanc(m, "--atadas").returncode == 0
    keys = json.loads((m / "keys.json").read_text())
    assert keys["key"] == video.osszkulcs(keys)

    def verdict(**v):
        (m / "verdict.json").write_text(json.dumps({"key": keys["key"], "verdict": "accept", **v}))

    p = lanc(m, "--vegleges")
    assert p.returncode == 2 and "nincs verdict.json" in p.stdout
    verdict(verdict="revise")
    p = lanc(m, "--vegleges")
    assert p.returncode == 2 and "nem accept" in p.stdout
    verdict(key="0" * 64)
    p = lanc(m, "--vegleges")
    assert p.returncode == 2 and "kulcsa nem a keys.json" in p.stdout
    verdict()
    narr = (m / "narracio.json").read_text()
    (m / "narracio.json").write_text(narr + "\n")
    p = lanc(m, "--vegleges")
    assert p.returncode == 2 and "narracio.json" in p.stdout
    (m / "narracio.json").write_text(narr)
    assert not (m / "kesz").exists()

    monkeypatch.setenv("VIDEO_CSONK", "1")
    monkeypatch.setattr(kapu, "k8a", lambda ut: [{"uzenet": "teszt-K8a"}])
    assert video.main(["teszt", "teszt", "tesztjelenet-1", "--vegleges", "--mappa", str(m), *CIMEK]) == 1
    assert not [p for p in (m / "kesz").iterdir()] and not (m / "nyugta.json").exists()
    monkeypatch.undo()

    p = lanc(m, "--vegleges")                                    # tesztmappán nincs wiki: a cím a hívásból kell
    assert p.returncode == 2 and "--tantargy-nev és --cim" in p.stdout, p.stdout
    p = lanc(m, "--vegleges", *CIMEK)
    assert p.returncode == 0, p.stdout
    assert sorted(x.name for x in (m / "kesz").iterdir()) == ["tesztjelenet-1.mp4", "tesztjelenet-1.opus"]
    # a --vegleges az átadás renderjét használja (a lektor ezt látta), nem renderel újra
    assert "render  az átadás 1080p-s renderje" in p.stdout, p.stdout
    assert json.loads((m / "meres.json").read_text())[-1]["render"]["atadasbol"] is True
    r = video.kesz_render(m)
    assert r and r["mp4"].name == "TesztJelenet.mp4" and r["mp4"].parent.name == "1080p30"
    rogz = (m / video.RENDER_ATADAS).read_text()
    (m / video.RENDER_ATADAS).write_text(rogz.replace(json.loads(rogz)["mp4_sha256"], "0" * 64))
    assert video.kesz_render(m) is None                          # más mp4: renderel
    (m / video.RENDER_ATADAS).write_text(rogz)
    naplo = (m / "render_naplo.json").read_text()
    (m / "render_naplo.json").write_text(naplo.replace('"felbontas": [', '"felbontas":['))   # 480p-s futás írta felül
    assert video.kesz_render(m) is None
    (m / "render_naplo.json").write_text(naplo)
    assert video.kesz_render(m) is not None
    ny = json.loads((m / "nyugta.json").read_text())
    assert ny["itelet"] == "accept" and ny["itelet_kulcs"] == keys["key"] and ny["csonk"]
    # nyitó- és zárókép: a lánc teszi be; a K8a továbbra is 1 videó- és 1 hangsávot lát, a hossz +8 s
    nz = ny["nyitozaro"]
    assert (nz["tantargy"], nz["cim"]) == ("Teszt", "A négy halmazművelet")
    assert abs(nz["nyito_s"] - 5.0) < 0.05 and abs(nz["zaro_s"] - 5.0) < 0.05
    kocka = json.loads((m / "idoterv.json").read_text())["kocka_osszes"]
    assert abs(ny["mp4"]["hossz_s"] - (kocka / 30 + 10.0)) < 0.2, ny["mp4"]["hossz_s"]
    assert kapu.k8a(m / "kesz" / "tesztjelenet-1.mp4") == []

    (m / "vizualis-terv.md").write_text("# terv\n")              # új bemenet → új kulcs → az ítélet félre
    p = lanc(m, "--atadas")
    assert p.returncode == 0 and "ítélet félretéve" in p.stdout
    assert not (m / "verdict.json").exists() and (m / f"verdict-{keys['key'][:12]}.json").exists()


def test_nyitozaro_cim_a_wikibol_vagy_a_hivasbol(tmp_path):
    from lanc import nyitozaro
    w = tmp_path / "wiki" / "matematika"
    w.mkdir(parents=True)
    (w / "index.md").write_text("---\ndescription: x\n---\n# 📐 Matematika\n\n## Halmazok\n", encoding="utf-8")
    (w / "halmazok.md").write_text("# Halmazok és halmazműveletek\n", encoding="utf-8")
    assert nyitozaro.cimek(tmp_path, "matematika", "halmazok-2", None, None) == \
        ("Matematika", "Halmazok és halmazműveletek")
    assert nyitozaro.cimek(tmp_path, "matematika", "halmazok-2", "A négy halmazművelet", None) == \
        ("Matematika", "A négy halmazművelet")
    with pytest.raises(nyitozaro.Megallt, match="cím"):
        nyitozaro.cimek(tmp_path, "matematika", "nincs-1", None, None)
    with pytest.raises(nyitozaro.Megallt, match="tesztmappa"):
        nyitozaro.cimek(None, "teszt", "teszt-1", "Cím", None)


def test_meres_iro_atirataban_es_codex(tmp_path):
    """--meres: csak videoiro és videolektor számít (Claude-ügynök vagy Codex-munkamenet videós szerepfájllal).
    Az átirat videója a kitöltéséből jön (más videó mappájának említése nem sorolja át: a „masik” a halmazok-12
    írója, hiába olvassa a halmazok-1 mappáját; az „iro4” a halmazok-1-é, hiába említi a halmazok-12-t);
    kitöltés nélkül az első hivatkozásból (a lektor OUT-útja; a relatív OUT-út tanulója a cwd-ből: a „bela”
    nem az annáé). A fejlesztőügynök az első üzenetében hiába nevezi meg. A Codex-vezérlő szerepfájl nélkül nem
    számít; „halmazok-1” ≠ „halmazok-12”; üres OUT: nincs keresés."""
    from datetime import datetime

    from lanc import meres as mrs
    repo = tmp_path / "school-notes-anna-active"
    out = repo / ".school-notes" / "out" / "video" / "matematika" / "halmazok-1"
    out.mkdir(parents=True)
    (out / "narracio.json").write_text("[]")
    t_out = datetime(2026, 10, 13, 10, 30).timestamp()
    os.utime(out / "narracio.json", (t_out, t_out))
    proj = tmp_path / "projects" / "p" / "s1" / "subagents"
    proj.mkdir(parents=True)

    def claude(nev, szerep, elso, tobbi="", cwd=str(tmp_path)):
        sorok = [{"type": "user", "cwd": cwd, "timestamp": "2026-10-13T10:00:00Z", "message": {"content": elso}},
                 {"type": "assistant", "cwd": cwd, "timestamp": "2026-10-13T10:01:00Z", "requestId": "r1",
                  "message": {"content": [{"type": "text", "text": tobbi}],
                              "usage": {"input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 50}}}]
        (proj / f"agent-{nev}.jsonl").write_text("\n".join(json.dumps(x) for x in sorok) + "\n")
        (proj / f"agent-{nev}.meta.json").write_text(json.dumps({"agentType": szerep}))

    kitoltes = "Tanuló: anna\nTantárgy: matematika\nLap, rész: halmazok, 1"
    rel = ".school-notes/out/video/matematika/halmazok-1/narracio.json"
    claude("iro", "videoiro", kitoltes, f"futtatom: {out}/narracio.json")
    claude("iro2", "videoiro", kitoltes, "~/.local/share/school-notes/release/current/packages/video/video.sh anna matematika halmazok-1")
    claude("iro3", "videoiro", kitoltes, rel, cwd=str(repo))
    claude("lektor", "videolektor", f"OUT: {out}")
    claude("masik", "videoiro", kitoltes.replace("halmazok, 1", "halmazok, 12"), f"mintának: {out}/narracio.json")
    claude("iro4", "videoiro", kitoltes, f"{out.parent / 'halmazok-12'}/narracio.json")
    claude("bela", "videoiro", "Tanuló: bela anna", rel, cwd=str(tmp_path / "school-notes-bela-active"))
    claude("fejleszto", "general-purpose", f"Javítsd a kaput; OUT: {out}", f"{out}")
    cdx = tmp_path / "codex" / "2026" / "10" / "13"
    cdx.mkdir(parents=True)

    def tc(osszes, utolso):
        return {"timestamp": "2026-10-13T11:00:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": osszes, "last_token_usage": utolso}}}

    def uzenet(szoveg):
        return {"timestamp": "2026-10-13T10:30:01Z", "type": "response_item", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": szoveg}]}}
    t1 = {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 40, "total_tokens": 1040}
    t2 = {"input_tokens": 3000, "cached_input_tokens": 2000, "output_tokens": 90, "total_tokens": 3090}
    hivas = {"timestamp": "2026-10-13T11:20:00Z", "type": "response_item", "payload": {
        "type": "function_call", "arguments": f"cd {out} && ls"}}
    sorok = [{"timestamp": "2026-10-13T10:30:00Z", "type": "session_meta", "payload": {}},
             uzenet("# AGENTS.md instructions\n... szerepek/videolektor.md ..."),
             uzenet("Olvasd be és kövesd: /x/docs/helyi/szerepek/videoiro.md\n" + kitoltes),
             tc(t1, t1), tc(t1, t1), tc(t2, {"input_tokens": 2000, "cached_input_tokens": 1400}), hivas]

    def rollout(nev, sorok):
        (cdx / f"rollout-{nev}.jsonl").write_text("\n".join(json.dumps(x) for x in sorok) + "\n")
    rollout("2026-10-13T10-30-00-a", sorok)
    rollout("2026-10-13T10-30-00-b", [*sorok[:2], uzenet("Olvasd be és kövesd: /x/docs/helyi/szerepek/videoiro.md\n"
                                                        + kitoltes.replace("halmazok, 1", "halmazok, 2")), *sorok[3:]])
    rollout("2026-10-13T10-30-00-e", [*sorok[:2], uzenet("Olvasd be és kövesd: /x/docs/helyi/szerepek/videoiro.md"),
                                      uzenet(f"{out.parent / 'halmazok-2'}"), *sorok[3:]])     # első hivatkozás: más
    rollout("2026-10-13T10-30-00-c", [sorok[0], uzenet(f"Vezérlő: nézd meg {out}"), tc(t1, t1), hivas])  # nincs szerep
    rollout("2026-10-13T14-00-00-d", sorok)                    # a legújabb OUT-fájl után több mint 1 órával indult
    ugy = mrs.ugynokok(out, projektek=tmp_path / "projects", codex=tmp_path / "codex", tanulo="anna")
    assert sorted(x["fajl"].name for x in ugy) == ["agent-iro.jsonl", "agent-iro2.jsonl", "agent-iro3.jsonl",
                                                   "agent-iro4.jsonl", "agent-lektor.jsonl",
                                                   "rollout-2026-10-13T10-30-00-a.jsonl"]
    c = next(x for x in ugy if x["fajl"].name.startswith("rollout"))
    assert (c["szerep"], c["hivas"], c["input"], c["cache_read"], c["output"], c["csucs"], c["usd"]) == \
        ("videoiro (Codex)", 2, 1000, 2000, 90, 2000, None)
    assert c["munkamenet"] is None and c["falio_s"] == 50 * 60
    o = mrs.osszead(ugy)
    assert o["beolvasott"] == 5 * 1100 + 3000 and o["usd"] == round(5 * round((100 * 4 + 1000 * 0.2 + 50 * 20) / 1e6, 2), 2)
    assert "| videoiro (Codex) | 2 |" in mrs.tabla([("videoiro (Codex)", c)])[2] and "| – |" in mrs.tabla([("x", c)])[2]
    (out / "narracio.json").unlink()                           # üres OUT-mappa: a Codex-tárat nem olvassa
    ugy = mrs.ugynokok(out, projektek=tmp_path / "projects", codex=tmp_path / "codex", tanulo="anna")
    assert not any(x["fajl"].name.startswith("rollout") for x in ugy)


def test_meres_vezerlo_csak_a_video_ablaka(tmp_path):
    """--meres vezérlősora: a munkamenetből csak a videó menetének ablaka (ügynökei, a vezérlő video.sh-hívásai a
    --meres nélkül, a lánc-futások), és ahol egy másik videó ablaka is fedi, a hívás fele számít."""
    from lanc import meres as mrs
    out = tmp_path / "school-notes-anna-active" / ".school-notes" / "out" / "video" / "matematika" / "halmazok-1"
    out.mkdir(parents=True)
    mm = tmp_path / "projects" / "p" / "s1"
    (mm / "subagents").mkdir(parents=True)

    def ugynok(nev, lap, t0, t1):
        sorok = [{"type": "user", "timestamp": t0, "message": {"content": f"Tanuló: anna\nTantárgy: matematika\n"
                                                                         f"Lap, rész: halmazok, {lap}"}},
                 {"type": "assistant", "timestamp": t1, "requestId": nev, "message": {"content": [],
                  "usage": {"input_tokens": 1, "output_tokens": 1}}}]
        (mm / "subagents" / f"agent-{nev}.jsonl").write_text("\n".join(json.dumps(x) for x in sorok) + "\n")
        (mm / "subagents" / f"agent-{nev}.meta.json").write_text(json.dumps({"agentType": "videoiro"}))
    ugynok("iro", 1, "2026-10-13T10:00:00Z", "2026-10-13T10:10:00Z")
    ugynok("masik", 2, "2026-10-13T10:05:00Z", "2026-10-13T10:40:00Z")

    def hivas(rid, t, n=100):
        return {"type": "assistant", "timestamp": t, "requestId": rid, "message": {"content": [], "usage": {
            "input_tokens": n, "output_tokens": 10}}}

    def bash(i, t, parancs):
        return {"type": "assistant", "timestamp": t, "requestId": f"b{i}", "message": {"content": [
            {"type": "tool_use", "id": f"tu{i}", "name": "Bash", "input": {"command": parancs}}],
            "usage": {"input_tokens": 0, "output_tokens": 0}}}

    def eredmeny(i, t):
        return {"type": "user", "timestamp": t, "message": {"content": [{"type": "tool_result", "tool_use_id": f"tu{i}"}]}}
    vs = "~/.local/share/school-notes/release/current/packages/video/video.sh anna matematika halmazok-1"
    sorok = [hivas("elotte", "2026-10-13T09:00:00Z"),                 # az ablak előtt: nem számít
             hivas("kozos", "2026-10-13T10:07:00Z"),                  # két videó ablakában: fele
             bash(1, "2026-10-13T10:20:00Z", f"cd x && {vs} --atadas 2>&1 | tail"), eredmeny(1, "2026-10-13T10:25:00Z"),
             hivas("sajat", "2026-10-13T10:45:00Z"),                  # az átadás és a futás között, a másik után
             hivas("utana", "2026-10-13T12:00:00Z"),                  # a --meres-hívás nem nyújtja az ablakot
             bash(2, "2026-10-13T12:30:00Z", f"{vs} --meres"), eredmeny(2, "2026-10-13T12:31:00Z")]
    (mm.with_suffix(".jsonl")).write_text("\n".join(json.dumps(x) for x in sorok) + "\n")
    futasok = [{"mod": "vegleges", "kod": 0, "s": 60.0, "ido": "2026-10-13T10:50:00+00:00"}]
    ugy = mrs.ugynokok(out, projektek=tmp_path / "projects", codex=None, tanulo="anna")
    assert [x["fajl"].name for x in ugy] == ["agent-iro.jsonl"]
    v = mrs.vezerlo(out, "anna", ugy, futasok, projektek=tmp_path / "projects")
    assert len(v) == 1 and v[0]["ablak"] == ["2026-10-13T10:00:00+00:00", "2026-10-13T10:50:00+00:00"]
    assert (v[0]["input"], v[0]["output"], v[0]["parhuzamos"]) == (150, 15, ["anna/matematika/halmazok-2"])
    assert v[0]["falio_s"] == 50 * 60
    assert mrs.vezerlo(out, "anna", ugy, futasok, projektek=tmp_path / "projects") == v     # determinisztikus


def test_kontaktlap_hibaja_nem_allitja_meg_a_lancot(tmp_path, monkeypatch):
    """Ha az író kontaktlapja nem készül el, a futás a kapu kódjával zárul, a lábsor megmondja, mi történt."""
    import lapok
    import video
    m = masol(tmp_path, "tesztjelenet")
    monkeypatch.setenv("VIDEO_CSONK", "1")

    def hiba(*a, **k):
        raise RuntimeError("ffmpeg-próba")
    monkeypatch.setattr(lapok, "iro_lapok", hiba)
    assert video.main(["teszt", "teszt", "tesztjelenet-1", "--mappa", str(m)]) == 0
    ki = (m / "osszefoglalo.txt").read_text()
    assert "kontaktlap nem készült: RuntimeError: ffmpeg-próba" in ki and "MEGÁLLT" not in ki


def test_meres_vezerlo_ket_munkamenet_es_ket_tanulo(tmp_path):
    """A futások a munkamenet idősávjára vágva számítanak (a másnapi futás nem nyújtja az előző napi ablakot), a
    másik videó ablakába a saját futásai is bekerülnek (szimmetrikus), és két tanuló azonos tantárgy+lapjánál a
    pontos (tanulós) kulcs dönt. Az ablak vége más napon dátummal látszik."""
    import video
    from lanc import meres as mrs
    gy = tmp_path / "school-notes-anna-active" / ".school-notes" / "out" / "video" / "matematika"
    out, masik = gy / "halmazok-1", gy / "halmazok-2"
    out.mkdir(parents=True)
    masik.mkdir(parents=True)
    (masik / "futasok.json").write_text(json.dumps([{"mod": "atadas", "kod": 0, "s": 300.0,
                                                     "ido": "2026-10-13T10:35:00+00:00"}]))
    bela = tmp_path / "school-notes-bela-active" / ".school-notes" / "out" / "video" / "matematika" / "halmazok-1"
    bela.mkdir(parents=True)
    (bela / "futasok.json").write_text(json.dumps([{"mod": "atadas", "kod": 0, "s": 60.0,
                                                    "ido": "2026-10-13T10:59:00+00:00"}]))
    proj = tmp_path / "projects" / "p"

    def ugynok(mm, nev, tanulo, lap, t0, t1):
        (proj / mm / "subagents").mkdir(parents=True, exist_ok=True)
        sorok = [{"type": "user", "timestamp": t0, "message": {"content": f"Tanuló: {tanulo}\nTantárgy: matematika\n"
                                                                         f"Lap, rész: halmazok, {lap}"}},
                 {"type": "assistant", "timestamp": t1, "requestId": nev, "message": {"content": [],
                  "usage": {"input_tokens": 1, "output_tokens": 1}}}]
        (proj / mm / "subagents" / f"agent-{nev}.jsonl").write_text("\n".join(json.dumps(x) for x in sorok) + "\n")
        (proj / mm / "subagents" / f"agent-{nev}.meta.json").write_text(json.dumps({"agentType": "videoiro"}))

    def fo(mm, hivasok):
        (proj / f"{mm}.jsonl").write_text("\n".join(json.dumps(
            {"type": "assistant", "timestamp": t, "requestId": f"{mm}{i}", "message": {"content": [], "usage": {
                "input_tokens": 100, "output_tokens": 0}}}) for i, t in enumerate(hivasok)) + "\n")
    ugynok("s1", "iro", "anna", 1, "2026-10-13T10:00:00Z", "2026-10-13T10:10:00Z")
    ugynok("s1", "masik", "anna", 2, "2026-10-13T10:12:00Z", "2026-10-13T10:20:00Z")
    ugynok("s1", "bela", "bela", 1, "2026-10-13T10:00:00Z", "2026-10-13T10:05:00Z")
    fo("s1", ["2026-10-13T09:00:00Z", "2026-10-13T10:02:00Z", "2026-10-13T10:15:00Z", "2026-10-13T10:32:00Z",
              "2026-10-13T11:00:00Z"])
    ugynok("s2", "lektor", "anna", 1, "2026-10-14T09:00:00Z", "2026-10-14T09:30:00Z")
    fo("s2", ["2026-10-14T08:50:00Z", "2026-10-14T09:10:00Z", "2026-10-14T10:00:00Z"])
    futasok = [{"mod": "alap", "kod": 0, "s": 120.0, "ido": "2026-10-13T10:25:00+00:00"},
               {"mod": "vegleges", "kod": 0, "s": 60.0, "ido": "2026-10-14T09:40:00+00:00"}]
    ugy = mrs.ugynokok(out, projektek=tmp_path / "projects", codex=None, tanulo="anna")
    assert [x["fajl"].name for x in ugy] == ["agent-iro.jsonl", "agent-lektor.jsonl"]
    v = mrs.vezerlo(out, "anna", ugy, futasok, projektek=tmp_path / "projects")
    assert [o["ablak"] for o in v] == [["2026-10-13T10:00:00+00:00", "2026-10-13T10:25:00+00:00"],
                                       ["2026-10-14T09:00:00+00:00", "2026-10-14T09:40:00+00:00"]]
    # s1: a bela ablaka a saját futásáig (10:59) tart; 10:02 a beláéval közös (1/2), 10:15 a beláéval és a
    # halmazok-2-ével (1/3): 50 + 33; a 10:32 és a 11:00 nem ennek a videónak az ablakában. s2: csak a 09:10.
    assert [o["input"] for o in v] == [83, 100]
    assert v[0]["parhuzamos"] == ["anna/matematika/halmazok-2", "bela/matematika/halmazok-1"]
    vb = mrs.vezerlo(bela, "bela", mrs.ugynokok(bela, projektek=tmp_path / "projects", codex=None, tanulo="bela"),
                     projektek=tmp_path / "projects")
    assert [o["ablak"] for o in vb] == [["2026-10-13T10:00:00+00:00", "2026-10-13T10:59:00+00:00"]]
    assert video.ablak_szoveg(v[0]["ablak"]) == "2026-10-13 10:00–10:25 UTC"
    assert video.ablak_szoveg(["2026-10-13T22:04:00+00:00", "2026-10-14T01:44:00+00:00"]) == \
        "2026-10-13 22:04–2026-10-14 01:44 UTC"


def test_leiras_a_kulcsban_csak_ha_van(tmp_path, monkeypatch):
    """leiras.txt bemenet: a lektori accept a tartalmához kötődik; ha nincs, a kész videók kulcsa nem változik."""
    import kapu
    import video
    monkeypatch.setattr(kapu, "videotar_hash", lambda: "vt")
    (tmp_path / "narracio.json").write_text("[]", encoding="utf-8")
    regi = video.kulcsok(tmp_path)                                   # egy leiras.txt előtti keys.json
    regi["key"] = video.osszkulcs(regi)
    assert "leiras.txt" not in regi
    assert [n for n, v in video.bemenet_resz(video.kulcsok(tmp_path)).items() if regi.get(n) != v] == []
    assert video.osszkulcs(video.kulcsok(tmp_path)) == regi["key"]
    (tmp_path / "leiras.txt").write_text("A forgatónyomaték és az erőkar egy merev rúdon.\n", encoding="utf-8")
    uj = video.kulcsok(tmp_path)
    assert "leiras.txt" in uj and video.osszkulcs(uj) != regi["key"]
    assert [n for n, v in video.bemenet_resz(uj).items() if regi.get(n) != v] == ["leiras.txt"]


# --- azonos értékű számalakok (ezres tagolás, „szám + ezer”, kimondott tizedesvessző, kötőjeles számnév) ---------

@pytest.mark.parametrize("szo,ertek", [
    ("17.000", 17000), ("134.760", 134760), ("12.600", 12600), ("1.000.000", 1000000), ("17.000-et", 17000),
    ("9,81", 9.81), ("2,5", 2.5), ("9.81", 9.81), ("1.2345", 1.2345), ("0.125", 0.125), ("0.500", 0.5),
    ("hétezer-háromszázhúsz", 7320), ("százharmincnégyezer-hétszázhatvan", 134760),
    ("kétezer-négyszázötven", 2450), ("tizenháromezer-háromszáznyolcvanat", 13380),
])
def test_szamalak_ezres_pont_es_kotojeles_szamnev(szo, ertek):
    """A Whisper ezres tagoló pontja („17.000”) nem tizedes; a kötőjeles számnév (a helyes írásmód) olvasható."""
    assert sz.egy_szo(szo)[0] == ertek


@pytest.mark.parametrize("szoveg,kanon", [
    ("kettő vessző öt méter", ["#2.5", "m"]), ("egy vessző harminchét", ["#1.37"]),
    ("nulla vessző nulla öt", ["#0.05"]), ("mínusz kettő vessző öt", ["#-2.5"]),
    ("nincs benne vessző", ["nincs", "benne", "vesszo"]), ("ez a vessző tizedesvessző", ["ez", "a", "vesszo",
                                                                                         "tizedesvesszo"]),
])
def test_kimondott_tizedesvesszo(szoveg, kanon):
    assert [u["kanon"] for u in sz.egysegek(szoveg.split())] == kanon


def test_whisper_szamjegy_folytatas_es_kotojeles_szam():
    """A Whisper „2” „,5” és „17” „.000” elemei egy szám; a kötőjeles számnév nem bomlik két számra."""
    szavak = [x["szo"] for x in sz.whisper_szavai([w("2", 0, 0.2), {"word": ",5", "start": 0.2, "end": 0.4},
                                                   w("17", 0.5, 0.7), {"word": ".000", "start": 0.7, "end": 1.0},
                                                   w("kg.", 1.0, 1.2), w("hétezer-háromszáz", 1.3, 2.0),
                                                   w("Z-elem", 2.1, 2.5)])]
    assert szavak == ["2,5", "17.000", "kg", "hétezer-háromszáz", "Z", "elem"]
    assert [sz.whisper_ertek(x) for x in ("17 000", "170 000", "13 380", "4 7")] == [17000, 170000, 13.38, 4.7]


K10_ESETEK = json.loads((Path(__file__).parent / "k10_esetek.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("eset", K10_ESETEK, ids=[f"{e['video']}-{e['lepes']}" for e in K10_ESETEK])
def test_k10_azonos_ertek_mas_alakban_nem_hiba(eset):
    """Regresszió (szintetikus esetek a kész videók 11 felülbírált K10-lépésének szám- és szóbontási alakjával): a Whisper
    az értéket más alakban írja („17.000”, „17 ezer”, „134 760”, „10.000”, „13 ezer”, „2,5”); a K10 ezekre
    felülbírálás nélkül sem ad hibát, a számok sora egyezik, és a szám Whisper-időt kap (nem becsültet)."""
    import types
    import kapu
    ws = eset["words"]
    r = sz.illeszt(eset["text"], ws, (ws[0]["start"], ws[-1]["end"]), [])
    assert hangok.szam_hibak(r["szavak"]) == [] and r["szameltérés"] is None, r["szavak"]
    mu = types.SimpleNamespace(ids=[eset["lepes"]], szavak_json={eset["lepes"]: r["szavak"]})
    assert [x for x in kapu.k10(mu) if x["sulyossag"] == "hiba"] == []
    assert all(x["forras"] == "whisper" for x in r["szavak"] if x["ertek"] is not None)


@pytest.mark.parametrize("text,szavak", [
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "18", ".000", "kg."]),       # más szám
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "18", "ezer", "kg."]),       # más szám
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "17", "kg."]),               # nincs ezer
    ("Az összeg tizenháromezer-háromszáznyolcvan kilogramm.", ["Az", "összeg", "13", "ezer", "kg."]),   # hiányzó rész
    ("Az erő százharmincnégyezer-hétszázhatvan newton.", ["Az", "erő", "134", "newton."]),       # hiányzó rész
    ("Az erő százharmincnégyezer-hétszázhatvan newton.", ["Az", "erő", "134", "761", "newton."]),
    ("A szélesség huszonöt méter.", ["A", "szélesség", "2", ",5", "méter."]),                      # 2,5 ↔ huszonöt
    ("A tömeg ezerhétszáz kilogramm.", ["A", "tömeg", "17", "000", "kg."]),                         # 17 000 ↔ 1700
    ("A tömeg ezerhétszáz kilogramm.", ["A", "tömeg", "17", ".000", "kg."]),
    ("A szélesség kettő vessző öt méter.", ["A", "szélesség", "25", "méter."]),                     # 2,5 ↔ 25
    ("A szélesség kettő vessző öt méter.", ["A", "szélesség", "2", ",6", "méter."]),
    # a csonka összevonás nem fogadható el: a maradék számcsoport a hallott számhoz tartozik
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "17", "ezer", "500", "kg."]),
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "17", "000", "500", "kg."]),
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "17", "000", "000", "kg."]),
    ("A rakomány tömege tizenhétezer kilogramm.", ["A", "rakomány", "tömege", "17", "ezer", "5", "kg."]),
    ("Az összeg tizenháromezer kilogramm.", ["Az", "összeg", "13", "ezer", "380", "kg."]),
    # a Whisper ezres alakja a narráció kisebb száma után (régi vakfolt: beszúrás)
    ("A tömeg tizenhét kilogramm.", ["A", "tömeg", "17", "000", "kg."]),
    ("A tömeg tizenhét kilogramm.", ["A", "tömeg", "17", "ezer", "kg."]),
])
def test_k10_valodi_szamhiba_mas_alakban_is_hiba(text, szavak):
    """Az összevonás csak az azonos értékű alakot fogadja el: más szám, hiányzó ezres rész, „2,5” ↔ „huszonöt”,
    „17 000” ↔ „ezerhétszáz” továbbra is számeltérés (a lánc újrapróbál, a kapu K10-hibát ad)."""
    ws = [{"word": x if x[0] in ",." else " " + x, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, x in enumerate(szavak)]
    r = sz.illeszt(text, ws, (0.0, len(szavak) * 0.5), [])
    assert hangok.szam_hibak(r["szavak"]) != [], r["szavak"]


@pytest.mark.parametrize("text,szavak", [
    ("A négyzetösszeg kétezer-négyszázötven newton a négyzeten.", ["A", "négyzetösszeg", "2", ".450", "N", "a",
                                                                  "négyzeten."]),
    ("A négyzetösszeg kétezer-négyszázötven newton a négyzeten.", ["A", "négyzetösszeg", "2", "450", "N", "a",
                                                                  "négyzeten."]),
    ("Tizenhárom, háromszáznyolcvan.", ["13", "380."]),     # két külön szám: nincs összevonás, nincs eltérés
    ("Tizenháromezer, háromszáznyolcvan.", ["13", "ezer", "380."]),  # a 380 egyező pár: nem fűződik a 13 000-hez
    ("Az érték nulla egész százhuszonöt méter.", ["Az", "érték", "0", ".125", "m."]),      # vezető 0: nem ezres
    ("Az érték nulla egész százhuszonöt méter.", ["Az", "érték", "0.125", "m."]),
    ("Mínusz tizenhétezer newton.", ["Minusz", "17", "ezer", "newton."]),
    ("Az összeg tizenháromezer-háromszáznyolcvan kilogramm.", ["Az", "összeg", "13", "ezer", "380", "kg."]),
])
def test_k10_kotojeles_szamnev_es_tagolas_rendben(text, szavak):
    ws = [{"word": x if x[0] in ",." else " " + x, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, x in enumerate(szavak)]
    r = sz.illeszt(text, ws, (0.0, len(szavak) * 0.5), [])
    assert hangok.szam_hibak(r["szavak"]) == [] and r["szameltérés"] is None, r["szavak"]


@pytest.mark.parametrize("text,szavak", [
    ("Tizenhét, két egész öt.", ["17,", "2", "5."]),
    ("Hat, négy egész hét.", ["6", "4", "7."]),
    ("Tizenhét, nulla egész hatvanöt.", ["17,", "0", "65."]),
])
def test_k10_tizedes_ket_whisper_egysegre_nem_maradek(text, szavak):
    """A Whisper „2 5” = 2,5 írásmódja a replace-blokk saját tizedese: nem fűződik az előző számhoz maradékként, a K10
    nem jelez (a számsor itt a régi módon eltér: a Whisper két számot ír, ezért csak a K10-szabályt nézzük)."""
    ws = [{"word": " " + x, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, x in enumerate(szavak)]
    r = sz.illeszt(text, ws, (0.0, len(szavak) * 0.5), [])
    assert hangok.szam_hibak(r["szavak"]) == [], r["szavak"]
    assert r["szavak"][0]["whisper"] == szavak[0].strip(",.")


def test_wrapped_traceback_keeps_scene_filename_and_line():
    from lanc.render import kivonat

    trace = """│ /a/very/long/output/folder/jele │
│ netek.py:23 in jelenet_t01      │
│                               │
│ ❱ 23 x = values['missing']     │
KeyError: 'missing'
"""
    excerpt = kivonat(trace, 1)
    assert any('jelenetek.py:23 in jelenet_t01' in line for line in excerpt)
    assert any("❱ 23 x = values['missing']" in line for line in excerpt)
    assert len(excerpt) <= 15
