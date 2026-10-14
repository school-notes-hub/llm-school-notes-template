"""Lépésütemező: a narráció lépései pontosan az idoterv.json kockáin, horgonnyal és szóra kötéssel.

Egy lépés = egy szekció (next_section("s01-01")). A lépés elemei egymás után indulnak a lépés
elején; ha nem férnek bele, arányosan rövidülnek, a maradék várakozás. Kötött elem:
  Horgony(nev, rt, fv, tart=False)  a narráció {nev} jelölésű szaván indul (előtte next_section("s01-10@nev"));
  Szora(mit, rt, fv, hanyadik=1)    a lépés `mit` szaván (szó vagy szám; a k-adik előfordulás) indul, {} nélkül.
A kötött elem utáni elemek a kötött elemhez láncolódnak. A kiemelések (kiemel, korvonal) a lépés
végéig maradnak, és a következő lépés első animációjával tűnnek el; tart=True horgonynál már a
következő kötött elemnél.

Környezeti változók: CSAK=s02,s03 (csak ezek kapnak képkockát, az állapot felépül);
IG=s03-04 (a lépés végén megáll, naplót nem ír; a -s kapcsolóval ez az író kivágata).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import manim
from manim import FadeOut, Scene, config
from manim.animation.animation import prepare_animation

from . import naplo as _naplo
from .naplo import Naplo, VideotarHiba, sima
from .stilus import HATTER

VERZIO = "0.1"
HORGONY_MINTA = re.compile(r"\{([^{}]+)\}")


class Horgony:
    """Lépéselem, amely a narráció {nev} szavának kockáján indul."""

    def __init__(self, nev: str, rt: float, fv, tart: bool = False):
        self.nev, self.rt, self.fv, self.tart = nev, rt, fv, tart


class Szora:
    """Lépéselem, amely a lépés `mit` szaván indul. `mit`: szám (a szó értéke) vagy szó (kisbetű,
    ékezet nélkül egyezik, vagy legalább 4 betűs szótő: „unió” ~ „uniója”); hanyadik: a k-adik
    előfordulás a lépés szövegében, vagy "utolso"."""

    def __init__(self, mit, rt: float, fv, hanyadik=1):
        self.mit, self.rt, self.fv, self.hanyadik = mit, rt, fv, hanyadik
        self.tart = False


class Eredmeny(Szora):
    """A Szamolas eredménye: a lépés még szabad {} horgonyára (az értékének egyeznie kell),
    különben az érték utolsó előfordulására."""

    def __init__(self, ertek, rt: float, fv):
        super().__init__(ertek, rt, fv, hanyadik="utolso")


def tiszta(szoveg: str) -> str:
    return szoveg.replace("{", "").replace("}", "")


def _szam(x):
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if isinstance(x, str) and re.fullmatch(r"-?\d+(?:[.,]\d+)?", x.strip()):
        return float(x.strip().replace(",", "."))
    return None


def szo_keres(szavak: list[dict], mit, hanyadik, sid: str) -> dict:
    """A lépés szavai közül a `mit`-nek megfelelő `hanyadik`-adik (vagy az utolsó)."""
    v = _szam(mit)
    if v is not None:
        talalat = [w for w in szavak if w.get("ertek") is not None and abs(float(w["ertek"]) - v) < 1e-9]
    else:
        c = sima(mit)
        talalat = [w for w in szavak if sima(w["szo"]) == c or (len(c) >= 4 and sima(w["szo"]).startswith(c))]
    if hanyadik == "utolso":
        if not talalat:
            raise VideotarHiba(f"{sid}: a(z) {mit!r} nem hangzik el a lépésben")
        return talalat[-1]
    if len(talalat) < int(hanyadik):
        raise VideotarHiba(f"{sid}: a(z) {mit!r} {hanyadik}. előfordulása nincs a lépés szövegében "
                           f"({len(talalat)} van)")
    return talalat[int(hanyadik) - 1]


def narracio_lepesek(mappa: Path) -> list[dict]:
    narr = json.loads((mappa / "narracio.json").read_text(encoding="utf-8"))
    ki = []
    for jel in narr:
        for i, lep in enumerate(jel["lepesek"], 1):
            ki.append({"id": f"{jel['id']}-{i:02d}", "jelenet": jel["id"], "text": lep["text"]})
    return ki


def idoterv_betolt(mappa: Path, fps: float) -> list[dict]:
    lepesek = narracio_lepesek(mappa)
    terv = json.loads((mappa / "idoterv.json").read_text(encoding="utf-8"))
    if abs(float(terv["fps"]) - fps) > 1e-9:
        raise VideotarHiba(f"idoterv.json fps={terv['fps']}, a render fps={fps}: --fps {terv['fps']} kell")
    tl = terv["lepesek"]
    if [t["id"] for t in tl] != [l["id"] for l in lepesek]:
        raise VideotarHiba("az idoterv.json lépései nem egyeznek a narracio.json lépéseivel: új idoterv kell")
    for t, l in zip(tl, lepesek):
        t["text"], t["jelenet"] = l["text"], l["jelenet"]
        t["horgonyok"] = {k: int(v["kocka"] if isinstance(v, dict) else v) for k, v in (t.get("horgonyok") or {}).items()}
    return tl


def _sha(ut: Path) -> str:
    return hashlib.sha256(ut.read_bytes()).hexdigest() if ut.exists() else ""


def videotar_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")) + [Path(__file__).parent / "naplo-sema.json"]:
        h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def _anim_lista(fv) -> list:
    anims = fv() if fv else []
    if anims is None:
        return []
    return list(anims) if isinstance(anims, (list, tuple)) else [anims]


class VideoJelenet(Scene):
    """Alaposztály: JELENETEK (opcionális ellenőrzés) és jelenet_<id>() -> list[list[elem]]."""

    JELENETEK: list[str] | None = None
    SZIGORU_TRANSFORM = True     # a nyers Transform szöveges objektumon futásidejű hiba (csak a napló tesztje kapcsolja ki)
    _utemezo = False

    def mappa(self) -> Path:
        if os.environ.get("VIDEO_MAPPA"):
            return Path(os.environ["VIDEO_MAPPA"])
        return Path(sys.modules[type(self).__module__].__file__).resolve().parent

    # a play/wait csak az ütemezőn át megy: így minden képváltozás naplózott és a kockatervben van
    def play(self, *args, **kw):
        if not self._utemezo:
            raise VideotarHiba("a self.play/self.wait közvetlenül nem hívható: a lépés elemei (rt, fv) párok, "
                               "Horgony vagy Szora, az fv animációt (vagy listát) ad vissza")
        return super().play(*args, **kw)

    def wait(self, *args, **kw):
        if not self._utemezo:
            raise VideotarHiba("a self.wait közvetlenül nem hívható: a csendet az ütemező tölti ki")
        return super().wait(*args, **kw)

    def construct(self):
        _naplo.uj_regiszter()
        _naplo.AKTIV = self
        self.camera.background_color = HATTER
        fps = float(config.frame_rate)
        mappa = self.mappa()
        terv = idoterv_betolt(mappa, fps)
        self.kocka = 0
        self.tartos: list = []
        self._tartos_ki: list = []
        self.naplo = Naplo(self, szigoru=self.SZIGORU_TRANSFORM)
        csak = {s.strip() for s in os.environ.get("CSAK", "").split(",") if s.strip()}
        ig = os.environ.get("IG", "").strip()
        jelenetek = list(dict.fromkeys(t["jelenet"] for t in terv))
        if self.JELENETEK is not None and list(self.JELENETEK) != jelenetek:
            raise VideotarHiba(f"JELENETEK = {self.JELENETEK}, a narrációban {jelenetek}")
        for sid in jelenetek:
            fv = getattr(self, "jelenet_" + sid, None)
            if fv is None:
                raise VideotarHiba(f"hiányzik a jelenet_{sid}() függvény")
            lepesek = fv()
            tl = [t for t in terv if t["jelenet"] == sid]
            if len(lepesek) != len(tl):
                raise VideotarHiba(f"{sid}: {len(lepesek)} képi lépés, {len(tl)} narrációs lépés")
            for t, elemek in zip(tl, lepesek):
                self.lepes(t, elemek, kihagy=bool(csak) and sid not in csak)
                if ig and t["id"] == ig:
                    return
        if ig:
            raise VideotarHiba(f"IG={ig}: nincs ilyen lépés")
        modul = Path(sys.modules[type(self).__module__].__file__).resolve()
        fej = {"sema": _naplo.SEMA, "jelenet": type(self).__name__, "videotar": VERZIO, "manim": manim.__version__,
               "fps": fps, "felbontas": [int(config.pixel_width), int(config.pixel_height)],
               "bemenet": {"narracio.json": _sha(mappa / "narracio.json"), "idoterv.json": _sha(mappa / "idoterv.json"),
                           modul.name: _sha(modul), "videotar": videotar_hash()},
               "kepkockak": self.kocka, "hossz_mp": round(self.kocka / fps, 3)}
        self.naplo.ir(mappa / "render_naplo.json", fej)

    # --- segédek az író kódjához ---------------------------------------------

    def mind_ki(self) -> list:
        """Minden látható objektum eltűnik (a tartós kiemeléseket a lépés eleje már kiveszi)."""
        return [FadeOut(m) for m in list(self.mobjects) if m not in self._tartos_ki]

    def _tartos_hozzaad(self, mob) -> None:
        self.tartos.append(mob)

    # --- ütemező ---------------------------------------------------------------

    def _kotesek(self, t: dict, elemek: list) -> dict[int, tuple[str, str, int]]:
        """Elemindex → (fajta, címke, kocka) a kötött elemekre; ellenőrzi a sorrendet és a horgonyszerződést."""
        sid = t["id"]
        kodbeli = [e.nev for e in elemek if isinstance(e, Horgony)]
        szabad = [n for n in t["horgonyok"] if n not in kodbeli]
        ki, elozo, eredmeny_horgony = {}, int(t.get("anim_kocka", t["kezd_kocka"])) - 1, []
        for i, e in enumerate(elemek):
            if isinstance(e, Horgony):
                if e.nev not in t["horgonyok"]:
                    raise VideotarHiba(f"{sid}: Horgony({e.nev!r}), de a narrációban nincs {{{e.nev}}}")
                k, cimke, fajta = t["horgonyok"][e.nev], e.nev, "horgony"
            elif isinstance(e, Eredmeny) and szabad:
                nev = szabad.pop(0)
                w = szo_keres(t.get("szavak") or [], nev.split()[0], 1, sid)
                if w.get("ertek") is None or abs(float(w["ertek"]) - float(_szam(e.mit))) > 1e-9:
                    raise VideotarHiba(f"{sid}: az eredmény {e.mit}, a {{{nev}}} horgonyszó értéke {w.get('ertek')}")
                eredmeny_horgony.append(nev)
                k, cimke, fajta = t["horgonyok"][nev], nev, "horgony"
            elif isinstance(e, Szora):
                if not t.get("szavak"):
                    raise VideotarHiba(f"{sid}: az idoterv.json lépésének nincs szavak listája (a Szora-hoz kell)")
                w = szo_keres(t["szavak"], e.mit, e.hanyadik, sid)
                k, cimke, fajta = int(w["kocka"]), w["szo"], "szora"
            elif isinstance(e, tuple) and len(e) == 2:
                continue
            else:
                raise VideotarHiba(f"{sid}: ismeretlen lépéselem: {e!r} (elem: (rt, fv), Horgony vagy Szora)")
            if k <= elozo and not ki and fajta == "szora":
                k = elozo + 1             # a lépés első szavára kötve: a lépés animációs kezdete
            if k <= elozo:
                raise VideotarHiba(f"{sid}: a(z) {cimke!r} kötés kockája ({k}) nem az előző kötés ({elozo}) után van; "
                                   f"a kötött elemek a szavak sorrendjében álljanak")
            ki[i] = (fajta, cimke, k)
            elozo = k
        nevek = sorted(kodbeli + eredmeny_horgony)
        if nevek != sorted(t["horgonyok"]) or sorted(t["horgonyok"]) != sorted(HORGONY_MINTA.findall(t["text"])):
            raise VideotarHiba(f"{sid}: horgonyszerződés: kód {nevek}, terv {sorted(t['horgonyok'])}")
        return ki

    def lepes(self, t: dict, elemek: list, kihagy: bool = False) -> None:
        """Egy narrációs lépés: pontosan veg_kocka − kezd_kocka kocka."""
        fps = float(config.frame_rate)
        sid = t["id"]
        kotesek = self._kotesek(t, elemek)
        self.next_section(sid, skip_animations=kihagy)
        if self.kocka != t["kezd_kocka"]:
            raise VideotarHiba(f"{sid}: a kockaszámláló {self.kocka}, a terv kezd_kocka {t['kezd_kocka']} "
                               f"(az előző lépés túlfutott: kevesebb elem vagy rövidebb rt kell)")
        lepes_kezd = self.kocka
        self.naplo.lepes_kezd(t)
        anim_kocka = int(t.get("anim_kocka", t["kezd_kocka"]))
        if anim_kocka > self.kocka:
            self._lejatszik([], anim_kocka - self.kocka)
        szakaszok, akt, akt_kotes, akt_tart = [], [], None, False
        for i, e in enumerate(elemek):
            if i in kotesek:
                szakaszok.append((akt, kotesek[i][2], akt_kotes, akt_tart))
                akt, akt_kotes, akt_tart = [(e.rt, e.fv)], kotesek[i], bool(getattr(e, "tart", False))
            else:
                akt.append(e)
        szakaszok.append((akt, t["veg_kocka"], akt_kotes, akt_tart))
        self._tartos_ki, self.tartos = list(self.tartos), []
        fuggo = [FadeOut(m) for m in self._tartos_ki]
        for szelemek, hatarido, kotes, tart in szakaszok:
            if kotes and kotes[0] == "horgony" and self.kocka > lepes_kezd:
                self.next_section(f"{sid}@{kotes[1]}", skip_animations=kihagy)
            tartos_eleje = len(self.tartos)
            kezdo = self.kocka
            keret = max(hatarido - kezdo, 0) / fps
            nevleges = sum(rt for rt, _ in szelemek)
            skala = keret / nevleges if nevleges > keret and nevleges > 0 else 1.0
            eltelt, elso = 0.0, True
            for rt, fv in szelemek:
                eltelt += rt * skala
                n = kezdo + int(round(eltelt * fps)) - self.kocka
                anims = _anim_lista(fv)
                if n < 1:
                    if not anims:
                        continue
                    n = 1
                if fuggo:
                    anims, fuggo = fuggo + anims, []
                self._lejatszik(anims, n, {"kotes": (kotes[0], kotes[1]) if kotes and elso else None,
                                           "rovidites": skala})
                elso = False
            maradek = hatarido - self.kocka
            if maradek > 0 and fuggo:
                n = min(maradek, max(1, int(round(0.3 * fps))))
                self._lejatszik(fuggo, n)
                fuggo = []
                maradek = hatarido - self.kocka
            if maradek > 0:
                self._lejatszik([], maradek)
            if kotes and kotes[0] == "horgony":
                self.naplo.allapot_ment("@" + kotes[1])
            if tart:
                fuggo += [FadeOut(m) for m in self.tartos[tartos_eleje:]]
                del self.tartos[tartos_eleje:]
        if fuggo:
            self.tartos += [a.mobject for a in fuggo]
        self.naplo.lepes_zar()

    def _lejatszik(self, anims, n: int, info: dict | None = None) -> None:
        """Pontosan n képkocka: a Manim np.arange(0, run_time, 1/fps) lépésenként ír képkockát,
        ezért (n − 0,5)/fps futásidő pontosan n kockát ad."""
        fps = float(config.frame_rate)
        rt = (n - 0.5) / fps
        anims = [prepare_animation(a) for a in anims]
        ctx = self.naplo.elott(anims)
        self._utemezo = True
        try:
            if anims:
                super().play(*anims, run_time=rt)
            else:
                super().wait(rt, frozen_frame=False)
        finally:
            self._utemezo = False
        self.naplo.utan(ctx, self.kocka, self.kocka + n, anims, info or {})
        self.kocka += n
