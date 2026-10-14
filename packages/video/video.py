"""A Manim-videó egyparancsos gépi lánca (terv-menet.md 2. pont). A video.sh hívja, a school_notes2
uv-környezetében; a Manimot nem importálja (a render a manim.sh-n át, saját környezetben fut).

    video.sh <tanuló> <tantárgy> <lap>-<n> [--atadas [--valtozott] | --vegleges | --meres | --kivagat <lépés>/<obj>
                                           | --takarit]

Lánc: indulás (verziók, zár) → bemenet → hang (TTS lépésenként) → szavak (Whisper minden lépésre,
illesztés, K10-újrapróbálás) → idoterv → render (480p30; --atadas/--vegleges: 1080p30) → kapu (kapu.py:
K1–K13, tábla, szöveg; --atadas: lapok, kivágatok, lépéskulcs) → 480p: az író kontaktlapjai (lapok-iro/,
a lábsor megadja az útjukat) → összefoglaló (≤ 30 sor).
--vegleges: az átadás 1080p-s renderje, ha kész és változatlan (render-atadas.json; különben render), utána
nyitó- és zárókép, összefésülés (felirat- és fejezetsáv nélkül), K8a (ffprobe), Opus-mentés, nyugta.
--meres: könyvelés (backfill), szerepenkénti token, gépi idő és díj, API-egyenérték → meres.md.
--kivagat <lépés>/<obj>: az író állóképe (≤ 2 körönként), a kapu lapok.iro_kivagat-jával vágva.
--takarit: a Manim-gyorsítótár (media) törlése; csak a nyugta után.

Munkamappa: <tanulói repó>/.school-notes/out/video/<tantárgy>/<lap>-<n>/; a media/ a
~/.cache/school-notes/video/<tanuló>/<tantárgy>/<lap>-<n>/ alá mutat. Részletek: video.log.
Kilépési kód: 0 zöld, 1 piros, 2 megállt (bemenet, verzió, zár, keret, időkorlát), 3 render-összeomlás.
Teszthez: VIDEO_CSONK=1 és --mappa <mappa>: TTS és Whisper helyett a szintetikus csonk, fizetős hívás nincs.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

GYOKER = Path(__file__).resolve().parent
sys.path.insert(0, str(GYOKER))
from lanc import hangok, meres as mrs, nyitozaro as nyz, render as rnd  # noqa: E402
from lanc.hangok import Megallt, ir  # noqa: E402

VIDEOTAR_VERZIO = "0.1"
MANIM_VERZIO = "0.22."
SN = Path.home() / ".local" / "share" / "school-notes"
CACHE = Path.home() / ".cache" / "school-notes" / "video"
KESZ = Path.home() / "jegyzet" / "video-kesz"
IDOKORLAT_S = float(os.environ.get("VIDEO_IDOKORLAT_S", "560"))   # a hívó 600 s-os Bash-korlátja alatt
MAX_SOR = 30
PIROS_HATAR, OSSZEOMLAS_HATAR, KIVAGAT_HATAR = 4, 6, 2


def hu(x, n=2) -> str:
    return f"{float(x):.{n}f}".replace(".", ",")


def perc(s: float) -> str:
    return f"{int(s // 60)} p {int(s % 60)} s" if s >= 60 else f"{s:.0f} s"


# --- indulás ---------------------------------------------------------------------------------------

def indulasi_hibak() -> list[str]:
    """Manim 0.22.x, TinyTeX, ffmpeg/ffprobe, magyar betűs font, videotar-verzió."""
    hibak = []
    dist = sorted((SN / "manim-env").glob("lib/python*/site-packages/manim-*.dist-info"))
    verzio = dist[-1].name.split("-")[1].removesuffix(".dist-info") if dist else None
    if not verzio or not verzio.startswith(MANIM_VERZIO):
        hibak.append(f"Manim {verzio or 'nincs'} (kell: {MANIM_VERZIO}x; telepites.md)")
    if not list((SN / "tinytex" / ".TinyTeX" / "bin").glob("*/latex")):
        hibak.append("TinyTeX hiányzik (telepites.md)")
    hibak += [f"{p} hiányzik" for p in ("ffmpeg", "ffprobe", "fc-list") if not shutil.which(p)]
    if shutil.which("fc-list") and not subprocess.run(["fc-list", ":lang=hu", "family"], capture_output=True,
                                                      text=True).stdout.strip():
        hibak.append("nincs magyar ékezetes font (fc-list :lang=hu)")
    m = re.search(r'^VERZIO = "([^"]+)"', (GYOKER / "videotar" / "utem.py").read_text(), re.M)
    if not m or m.group(1) != VIDEOTAR_VERZIO:
        hibak.append(f"videotar {m.group(1) if m else '?'} (a lánc a {VIDEOTAR_VERZIO}-hoz készült)")
    return hibak


def verziok() -> dict:
    """A nyugtához: a lánc (a template-fa) commitja, a videotar hash-e, Manim, font."""
    import kapu
    git = subprocess.run(["git", "-C", str(GYOKER), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    piszkos = subprocess.run(["git", "-C", str(GYOKER), "status", "--porcelain", "videotar", "lanc", "kapu.py",
                              "video.py"], capture_output=True, text=True).stdout.strip()
    dist = sorted((SN / "manim-env").glob("lib/python*/site-packages/manim-*.dist-info"))
    font = subprocess.run(["fc-match", "sans-serif"], capture_output=True, text=True).stdout.strip()
    return {"lanc_commit": git + ("+változott" if piszkos else ""), "videotar": VIDEOTAR_VERZIO,
            "videotar_sha256": kapu.videotar_hash(), "manim": dist[-1].name.split("-")[1].removesuffix(".dist-info") if dist else None, "font": font}


@contextlib.contextmanager
def video_zar(mappa: Path):
    """Egy videón egyszerre egy lánc (a fizetős szakaszt a podcast.lock külön védi)."""
    fd = os.open(mappa / ".video.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Megallt("ezen a videón már fut egy lánc (.video.lock)") from None
        yield
    finally:
        os.close(fd)


def bemenet(mappa: Path) -> list:
    """narracio.json: [{id, lepesek: [{text, szunet?, kulcspont?}]}]; a {}-párok; jelenetek.py egy osztállyal."""
    for n in ("narracio.json", "jelenetek.py"):
        if not (mappa / n).exists():
            raise Megallt(f"hiányzó bemenet: {mappa / n}")
    try:
        narr = json.loads((mappa / "narracio.json").read_text(encoding="utf-8"))
        assert isinstance(narr, list) and narr, "üres vagy nem lista"
        ids = [j["id"] for j in narr]
        assert len(set(ids)) == len(ids), f"ismétlődő jelenet-id: {ids}"
        for j in narr:
            assert isinstance(j.get("lepesek"), list) and j["lepesek"], f"{j['id']}: nincs lepesek"
            for l in j["lepesek"]:
                hangok.proba_hang.tts_szoveg(l["text"])
                hangok.proba_hang.horgonyok(l["text"])
        rnd.jelenet_osztaly(mappa / "jelenetek.py")
    except (AssertionError, KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise Megallt(f"hibás bemenet: {e}") from None
    return narr


# --- a lánc ----------------------------------------------------------------------------------------

class Lanc:
    def __init__(self, a, mappa: Path):
        self.a, self.mappa, self.t0 = a, mappa, time.monotonic()
        self.log_ut = mappa / "video.log"
        self.lepesido: dict[str, list] = {}
        self.sorok: list[str] = []
        self.minoseg = "1080p" if (a.atadas or a.vegleges) else "480p"
        self.mod = "atadas" if a.atadas else "vegleges" if a.vegleges else "alap"

    def maradek(self) -> float:
        return IDOKORLAT_S - (time.monotonic() - self.t0)

    @contextlib.contextmanager
    def lepes(self, nev: str):
        t = time.monotonic()
        yield
        self.lepesido[nev] = [round(t - self.t0, 1), round(time.monotonic() - self.t0, 1)]

    def media(self) -> None:
        """A nehéz media/ a ~/.cache alá (a kapu a mappa/media útvonalon keresi)."""
        m = self.mappa / "media"
        if self.a.mappa:
            m.mkdir(exist_ok=True)
            return
        cel = CACHE / self.a.tanulo / self.a.tantargy / self.a.lap / "media"
        cel.mkdir(parents=True, exist_ok=True)
        if m.is_symlink() and m.resolve() == cel.resolve():
            return
        if m.exists() and not m.is_symlink():
            raise Megallt(f"{m} valódi mappa: helyezd át a {cel} alá, vagy töröld")
        m.unlink(missing_ok=True)
        m.symlink_to(cel)

    def fut(self) -> int:
        a, mappa = self.a, self.mappa
        narr = bemenet(mappa)
        hibak = indulasi_hibak()
        if hibak:
            raise Megallt("indulás: " + "; ".join(hibak))
        if a.vegleges:
            vegleges_feltetel(mappa)
        self.media()
        epizod = f"video/{a.tantargy}/{a.lap}"
        # a csonk csak a --mappa tesztmappán fut (a mappa_utja a valódi mappán VIDEO_CSONK=1 mellett megáll)
        szolg = hangok.Csonk(narr) if a.mappa and os.environ.get("VIDEO_CSONK") == "1" \
            else hangok.Valodi(a.tanulo, epizod)
        with open(self.log_ut, "w", encoding="utf-8") as log, self.lepes("hang+szavak"):   # a napló futásonként új
            log.write(f"\n=== {datetime.now(timezone.utc).isoformat(timespec='seconds')} {self.mod} {epizod}\n")
            self.hs = hangok.hang_es_szavak(mappa, narr, szolg, log)
        self.keret = szolg.kesz()
        with self.lepes("idoterv"):
            self.terv = hangok.idoterv_szavakkal(mappa, rnd.FPS)
        with self.lepes("render"):
            kesz = kesz_render(mappa) if a.vegleges else None
            self.r = kesz or rnd.render(mappa, mappa / "media", self.minoseg, self.log_ut, max(30.0, self.maradek()))
        self.sorok = self.fej_sorok(szolg)
        if self.r["kod"]:
            self.sorok += self.r["kivonat"]
            return self.r["kod"]
        if kesz:
            self.sorok.append("render  az átadás 1080p-s renderje (a lektor ezt látta; mp4 és napló sha256 egyezik), "
                              "újrarenderelés nélkül")
        else:
            self.sorok.append(f"render  {hu(self.r['s'], 0)} s, {self.r['animacio']} animáció, "
                              f"{self.r['gyorsitotar']} gyorsítótárból")
            if a.atadas:
                render_rogzit(mappa, self.r["mp4"])
        with self.lepes("kapu"):
            kod, kapu_sorok = self.kapu()
        self.sorok += kapu_sorok
        if self.mod == "alap":
            with self.lepes("lapok"):
                try:                                  # a kontaktlap segédlet: a hibája nem írja felül a kapu kódját
                    self.iro_lapok = iro_lapok(mappa)
                except Exception as e:  # noqa: BLE001
                    with open(self.log_ut, "a", encoding="utf-8") as log:
                        traceback.print_exc(file=log)
                    self.iro_lapok = f"kontaktlap nem készült: {type(e).__name__}: {str(e)[:150]} (video.log)"
        if a.atadas:
            self.sorok += pillanatkep(mappa)
        if a.vegleges and kod == 0:
            with self.lepes("vegleges"):
                kod = self.vegleges(szolg)
        return kod

    def fej_sorok(self, szolg) -> list[str]:
        hs, sz, k = self.hs, self.hs["szam"], self.keret
        szavak = json.loads((self.mappa / "szavak.json").read_text(encoding="utf-8"))
        becs = sum(any(w["forras"] == "becsult" for w in v) for v in szavak.values())
        gyan = sum(any(w["forras"] == "gyanus" for w in v) for v in szavak.values())
        sorok = [f"hang    {hs['lepes']} lépés, {sz.uj_tts} új TTS, {hu(sz.tts_foglalt, 3)} USD foglalva, "
                 f"{hu(hs['hossz_s'], 1)} s",
                 f"szavak  {hs['lepes'] - hs['nincs_szoido']}/{hs['lepes']} lépés szóidővel ({becs} becsült, "
                 f"{gyan} gyanús), {sz.uj_whisper} új Whisper, {hu(sz.whisper_foglalt, 3)} USD foglalva"]
        if hs["k10"]:
            marad = sorted(s for s, v in hs["k10"].items() if "marad" in v or "szo_marad" in v)
            sorok.append(f"K10     számeltérés/szóváltozás {len(hs['k10'])} lépésben: újraleírás "
                         f"{sum(v.get('ujraleiras', 0) for v in hs['k10'].values())}, új TTS "
                         f"{sum(v.get('uj_tts', 0) for v in hs['k10'].values())}; maradt: {', '.join(marad) or '–'}")
        if szolg.csonk:
            sorok.append("keret   CSONK (teszt): TTS és Whisper nélkül, fizetős hívás nincs")
        else:
            sorok.append(f"keret   futás {hu(k['futas_usd'])}/{hu(k['futas_keret'], 1)} USD · videó "
                         f"{hu(k['video_usd'])}/{hu(hangok.KERET_VIDEO, 0)} USD (foglalással; könyvelés a --meres-nél)")
            sorok += [f"FIGY    {w}" for w in k["figyelmeztetes"][:2]]
        t = self.terv
        nh = sum(len(l["horgonyok"]) for l in t["lepesek"])
        sorok.append(f"terv    {len(t['lepesek'])} lépés, {nh} horgony, {t['kocka_osszes']} kocka "
                     f"({perc(t['kocka_osszes'] / t['fps'])})")
        return sorok

    def kapu(self) -> tuple[int, list[str]]:
        import kapu
        try:
            with open(self.log_ut, "a", encoding="utf-8") as log, contextlib.redirect_stdout(log):
                return kapu.futtat(self.mappa, atadas=self.a.atadas, valtozott=self.a.valtozott,
                                   vezerlo=bool(self.a.atadas or self.a.vegleges))
        except FileNotFoundError as e:
            raise Megallt(f"kapu: hiányzó bemenet: {e}") from None

    def vegleges(self, szolg) -> int:
        """Nyitó- és zárókép, összefésülés, K8a, Opus-mentés, nyugta (a tanulói repó docs/evidence/video/ alá)."""
        import kapu
        a, m = self.a, self.mappa
        teszt = bool(a.mappa or szolg.csonk)        # tesztmappa vagy csonk: sose a KESZ és az evidence alá
        cel = (m / "kesz" if teszt else KESZ / a.tanulo / a.tantargy) / f"{a.lap}.mp4"
        cel.parent.mkdir(parents=True, exist_ok=True)
        # m.parents[4] a nem feloldott (symlinkes) munkamappa útján a tanulói repó gyökere: szándékos
        targy, cim = nyz.cimek(None if teszt else m.parents[4], a.tantargy, a.lap, a.cim, a.tantargy_nev)
        nz = nyz.kepek(self.r["mp4"], m / "media", self.minoseg, targy, cim, self.log_ut, max(30.0, self.maradek()))
        tmp = cel.with_name(f".{cel.stem}.tmp.mp4")    # a K8a a tmp-fájlon mér; csak zöld után a végleges helyre
        try:
            nyz.osszefesul(nz, self.r["mp4"], m / "hang.wav", tmp, self.log_ut)
            k8a = kapu.k8a(tmp)
            if k8a:
                self.sorok += [f"HIBA K8a {x.get('uzenet', x)}" for x in k8a]
                return 1
            info = rnd.ffprobe_adat(tmp)
            opus_tmp = tmp.with_suffix(".opus")
            rnd.opus_mentes(m / "hang.wav", opus_tmp, self.log_ut)
            opus_tmp.replace(cel.with_suffix(".opus"))
            tmp.replace(cel)
        finally:
            tmp.unlink(missing_ok=True)
            tmp.with_suffix(".opus").unlink(missing_ok=True)
        nyugta = self.nyugta(cel, info, szolg)
        nyugta["nyitozaro"] = nyz.nyugta(nz, targy, cim)
        ir(m / "nyugta.json", nyugta)
        if not teszt:
            ev = m.parents[4] / "docs" / "evidence" / "video" / a.tantargy
            (ev / a.lap).mkdir(parents=True, exist_ok=True)
            ir(ev / f"{a.lap}.json", nyugta)
            for n in ("narracio.json", "vizualis-terv.md", "jelenetek.py", "kezi.json", LEIRAS):
                if (m / n).exists():
                    shutil.copyfile(m / n, ev / a.lap / n)
            if not (m / LEIRAS).exists():
                # nem állít meg: a videó leírása (címke) üres marad, az sn publish listázza
                self.sorok.append(f"FIGY    nincs {LEIRAS} az OUT-ban: a videó leírása üres marad")
        self.sorok.append(f"végleges {cel} ({info['hossz_s']} s, {info['felbontas'][0]}×{info['felbontas'][1]}), "
                          f"{cel.with_suffix('.opus').name}, nyugta")
        return 0

    def nyugta(self, cel: Path, info: dict, szolg) -> dict:
        """A videó nyugtája. Az `mp4.sha256` és az `opus.sha256` a címkézetlen renderre szól: az sn publish
        utána címkézi a video-kesz fájljait (sorszám a névben, cím, album, track, leírás; -c copy)."""
        m = self.mappa
        be = lambda n: json.loads((m / n).read_text(encoding="utf-8")) if (m / n).exists() else None  # noqa: E731
        szavak, naplo, kj = be("szavak.json"), be("render_naplo.json"), be("kapu.json") or {}
        tts = hangok.tts_keres("")
        tts.pop("input")
        stilus = tts.pop("instructions")
        terv = {l["id"]: l for l in be("idoterv.json")["lepesek"]}
        ketseges = k10_ketseges(szavak, terv)
        return {"sema": "video-nyugta/1", "video": f"{self.a.tantargy}/{self.a.lap}", "tanulo": self.a.tanulo,
                "csonk": szolg.csonk, "kulcs": kulcsok(m), "itelet": (be("verdict.json") or {}).get("verdict"),
                "itelet_kulcs": (be("verdict.json") or {}).get("key"),
                "mp4": {"sha256": rnd.sha256(cel), "bajt": cel.stat().st_size, **info, "render": "manim -qh --fps 30",
                        "osszefesules": "nyitókép + fő videó + zárókép (concat, másolva); aac 160k sztereó, "
                                        "-map_metadata -1 -map_chapters -1 -sn -dn"},
                "opus": {"sha256": rnd.sha256(cel.with_suffix(".opus")), "bitrata": "48k"},
                "verziok": verziok(), "tts": {**tts, "stilus_sha256": hashlib_sha(stilus)},
                "hang_lepesenkent": {p.stem: rnd.sha256(p) for p in sorted((m / "hang").glob("*.wav"))},
                "kapu": {k: kj.get(k) for k in ("zold", "szam") if k in kj},
                "kapu_kivetel": be("kapu-kivetel.json"),
                "kapcsolok": sorted(({"lepes": l["id"], **x} for l in (naplo or {}).get("lepesek", [])
                                     for x in l["kapcsolok"]), key=lambda x: (x["lepes"], x["obj"], x["kapcsolo"])),
                "kezi": be("kezi.json"), "k10_ketseges": ketseges,
                "meres": (be("meres.json") or [None])[-1]}

    def futas_naplo(self, kod: int) -> tuple[int, int, int]:
        """futasok.json bővítése; visszaad: (hányadik alapfutás az utolsó átadás óta, pirosak, összeomlások)."""
        ut = self.mappa / "futasok.json"
        f = json.loads(ut.read_text()) if ut.exists() else []
        f.append({"mod": self.mod, "kod": kod, "s": round(time.monotonic() - self.t0, 1),
                  "ido": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        ir(ut, f)
        utolso = max((i for i, x in enumerate(f) if x["mod"] == "atadas"), default=-1)
        alap = [x for x in f[utolso + 1:] if x["mod"] == "alap"]
        return len(alap), sum(x["kod"] == 1 for x in alap), sum(x["kod"] == 3 for x in alap)

    def meres_ir(self, kod: int) -> None:
        ut = self.mappa / "meres.json"
        f = json.loads(ut.read_text()) if ut.exists() else []
        hs = getattr(self, "hs", None)
        sor = {"mod": self.mod, "kod": kod, "ido": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "s": round(time.monotonic() - self.t0, 1), "lepesek": self.lepesido}
        if hs:
            sor.update(tts_uj=hs["szam"].uj_tts, whisper_uj=hs["szam"].uj_whisper,
                       foglalt_usd=float(hs["szam"].tts_foglalt + hs["szam"].whisper_foglalt),
                       k10=hs["k10"], hossz_s=round(hs["hossz_s"], 3))
        if getattr(self, "r", None):
            sor["render"] = {k: self.r[k] for k in ("s", "animacio", "gyorsitotar", "kod", "atadasbol") if k in self.r}
        f.append(sor)
        ir(ut, f)


def iro_lapok(m: Path) -> str:
    """Az író 480p-s futásának kontaktlapjai (lapok.iro_lapok); a lánc lábsora megadja az útjukat."""
    import kapu
    import lapok
    n, kocka, cel = lapok.iro_lapok(kapu.Munka(m), json.loads((m / "kapu.json").read_text(encoding="utf-8")))
    return f"kontaktlapok {n} lap, {kocka} kocka: {cel}/ (átadás előtt egy üzenetben, 10. és 12. szabály)"


def k10_ketseges(szavak: dict, terv: dict) -> list[dict]:
    """A nyugta K10-helyei a tulajdonosnak (ezeket az időpontokat hallgatja meg): a szám, amelynek értékét a
    Whisper másnak hallotta, a szó, amelyet a lánc újrapróbálása után is más szóként hallott, és a lépés,
    amelyre a Whisper minden próbára szó nélkül válaszolt (`nincs_szo`: a lépés szövege, a beszéd kezdete)."""
    from lanc import szavak as sz
    ki = []
    for sid, v in sorted(szavak.items()):
        kezd = terv[sid]["hang_kezd_s"]
        ki += [{"lepes": sid, "ido_s": round(kezd + w["kezd_s"], 2), "fajta": "szam", "szo": w["szo"],
                "whisper": w["whisper"]} for w in v if w.get("ertek") is not None and szam_mas(w)]
        ws = [w for w in v if "whisper" in w]
        if ws and not any(w["whisper"] for w in ws):      # a Whisper szó nélkül válaszolt: a lépés egésze
            ki.append({"lepes": sid, "ido_s": round(kezd + ws[0]["kezd_s"], 2), "fajta": "nincs_szo",
                       "szo": " ".join(w["szo"] for w in ws), "whisper": None})
        elif ws:
            ki += [{"lepes": sid, "ido_s": round(kezd + ws[x["idx"]]["kezd_s"], 2), "fajta": "szo", "szo": x["szo"],
                    "whisper": x["hallott"]} for x in sz.valtozott_szavak([w["szo"] for w in ws], sz.hallott_szavak(ws))]
    return sorted(ki, key=lambda x: (x["lepes"], x["ido_s"], x["fajta"], x["szo"]))


def szam_mas(w: dict) -> bool:
    """A szó számértéke és a Whisper hallotta érték eltér (a K10 kétséges helye a nyugtába)."""
    from lanc import szavak as sz
    hallott = [u["ertek"] for u in sz.egysegek((w.get("whisper") or "").split()) if u["ertek"] is not None]
    tizedes = sz.whisper_ertek(w.get("whisper") or "")
    return bool(w.get("whisper")) and w["ertek"] not in hallott and w["ertek"] != tizedes


def hashlib_sha(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()


# A videó leírása (1–2 mondat, legfeljebb ~200 karakter, egy sor; a videóíró írja): a --vegleges az evidence alá
# másolja, az sn publish a videófájl címkéjébe (comment/description) írja. Bemenet: a lektori accept a kulcson át
# hozzá is kötődik. Ha nincs, nem kerül a kulcsba (a kulcsok() csak a meglévő fájlt hash-eli), így a leírás nélkül
# kész videók kulcsa nem változik.
LEIRAS = "leiras.txt"
BEMENETEK = ("narracio.json", "jelenetek.py", "kezi.json", "vizualis-terv.md", "kapu-kivetel.json", LEIRAS)


def kulcsok(m: Path) -> dict:
    """keys.json: a bemenetek és kimenetek hash-e (az ítélet ehhez a tartalomhoz kötődik)."""
    import kapu
    k = {n: rnd.sha256(m / n) for n in (*BEMENETEK, "idoterv.json", "szavak.json", "hang.wav", "render_naplo.json",
                                        "lepeskulcs.json") if (m / n).exists()}
    k["videotar"] = kapu.videotar_hash()
    return k


def bemenet_resz(k: dict) -> dict:
    """A kulcstérkép bemeneti része: amit az író ír (és a videotar); a --vegleges ezt veti össze."""
    return {n: k.get(n) for n in (*BEMENETEK, "videotar")}


def osszkulcs(k: dict) -> str:
    """A kulcstérkép kanonikus JSON-jának sha256-ja (a verdict.json `key` mezője ehhez kötődik)."""
    return hashlib_sha(json.dumps({n: v for n, v in k.items() if n != "key"}, sort_keys=True, separators=(",", ":")))


def pillanatkep(m: Path) -> list[str]:
    """--atadas: keys.json a `key` összesítővel (a podcast snapshot mintájára). Ha a kulcs változott, a régi
    verdict.json félre kerül (más tartalomra szólt; sosem törlődik)."""
    k = kulcsok(m)
    k["key"] = osszkulcs(k)
    regi = json.loads((m / "keys.json").read_text(encoding="utf-8")) if (m / "keys.json").exists() else {}
    sorok = []
    if regi.get("key") != k["key"] and (m / "verdict.json").exists():
        alap = f"verdict-{str(regi.get('key') or 'elotte')[:12]}"
        hova = next(m / f"{alap}{'' if n == 1 else f'-{n}'}.json" for n in range(1, 1000)
                    if not (m / f"{alap}{'' if n == 1 else f'-{n}'}.json").exists())
        (m / "verdict.json").replace(hova)
        sorok.append(f"a korábbi ítélet félretéve (más változatra szólt): {hova.name}")
    ir(m / "keys.json", k)
    sorok.append(f"pillanatkép keys.json (kulcs: {k['key'][:12]})")
    return sorok


RENDER_ATADAS = "render-atadas.json"


def render_rogzit(m: Path, mp4: Path) -> None:
    """--atadas: a lektornak átadott 1080p-s render ujjlenyomata (mp4 és render_naplo.json), hogy a --vegleges ne
    renderelje újra. Nem része a keys.json kulcsának (az mp4 bájtjai renderről renderre eltérhetnek)."""
    ir(m / RENDER_ATADAS, {"mp4": str(mp4.relative_to(m / "media")), "mp4_sha256": rnd.sha256(mp4),
                           "render_naplo.json": rnd.sha256(m / "render_naplo.json")})


def kesz_render(m: Path) -> dict | None:
    """A --vegleges az átadás renderjét használja, ha az kész és változatlan: a rögzített mp4 megvan, bájtra az,
    a render_naplo.json az átadásé (a keys.json szerint is), 1080p-s, és a bemenetei (narráció, időterv, jelenetkód,
    videotar) a mostaniak. A bemenetek egyezését az átadás óta a vegleges_feltetel már igazolta. Különben None:
    a lánc renderel (például --takarit után, vagy ha azóta 480p-s futás írta felül a naplót)."""
    import kapu
    try:
        r = json.loads((m / RENDER_ATADAS).read_text(encoding="utf-8"))
        keys = json.loads((m / "keys.json").read_text(encoding="utf-8"))
        naplo = json.loads((m / "render_naplo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mp4 = m / "media" / r.get("mp4", "")
    ns = rnd.sha256(m / "render_naplo.json")
    if naplo.get("felbontas") != [1920, 1080] or r.get("render_naplo.json") != ns or keys.get("render_naplo.json") != ns \
            or not mp4.is_file() or mp4.parent.name != rnd.MINOSEG["1080p"][1]:
        return None
    modul = "jelenetek.py"
    friss = {"narracio.json": rnd.sha256(m / "narracio.json"), "idoterv.json": rnd.sha256(m / "idoterv.json"),
             modul: rnd.sha256(m / modul), "videotar": kapu.videotar_hash()}
    if any(naplo.get("bemenet", {}).get(k) != v for k, v in friss.items()) or rnd.sha256(mp4) != r.get("mp4_sha256"):
        return None
    return {"kod": 0, "mp4": mp4, "s": 0.0, "animacio": 0, "gyorsitotar": 0, "osztaly": mp4.stem, "atadasbol": True}


def vegleges_feltetel(m: Path) -> None:
    """A --vegleges csak a lektor elfogadó ítéletével, és csak arra a tartalomra fut, amelyet a lektor látott."""
    kp, vp = m / "keys.json", m / "verdict.json"
    if not kp.exists():
        raise Megallt("nincs keys.json: előbb --atadas és lektori ítélet kell")
    if not vp.exists():
        raise Megallt("nincs verdict.json: a --vegleges csak a lektor elfogadó ítélete után")
    try:
        keys, verdict = json.loads(kp.read_text(encoding="utf-8")), json.loads(vp.read_text(encoding="utf-8"))
    except ValueError as e:
        raise Megallt(f"sérült keys.json vagy verdict.json: {e}") from None
    if verdict.get("verdict") != "accept":
        raise Megallt(f"az ítélet nem accept ({verdict.get('verdict')!r})")
    if not keys.get("key") or verdict.get("key") != keys["key"]:
        raise Megallt("a verdict.json kulcsa nem a keys.json kulcsa (az ítélet más változatra szólt)")
    if keys.get("key") != osszkulcs(keys):
        raise Megallt("a keys.json kulcsa nem egyezik a tartalmával")
    elter = sorted(n for n, v in bemenet_resz(kulcsok(m)).items() if keys.get(n) != v)
    if elter:
        raise Megallt(f"a bemenet az átadás óta változott ({', '.join(elter)}): új --atadas és ítélet kell")


# --- --meres, --takarit ----------------------------------------------------------------------------

def meres(a, mappa: Path) -> int:
    """Előbb könyvel (backfill a videó hívásaira), aztán szerepenkénti token, gépi idő, díj → meres.md."""
    epizod = f"video/{a.tantargy}/{a.lap}"
    sorok = [f"MÉRÉS {a.tanulo} {epizod}"]
    if os.environ.get("VIDEO_CSONK") == "1":
        dij = {"konyvelt": Decimal(0), "foglalt": Decimal(0), "hivas": 0, "tts": 0, "whisper": 0}
    else:
        from school_notes2.local import common
        from school_notes2.local.podcast_names import _client
        settings = common.load(a.tanulo).podcast_settings()
        # a mentés a podcast.lock alatt friss ledgerre (párhuzamos lánc vagy `sn podcast` bejegyzése nem vész el)
        sajat, maradt = hangok.konyvel(settings, _client(settings, time.sleep), epizod, a.tanulo)
        dij = mrs.ledger_osszeg(sajat)
        if maradt:
            sorok.append(f"könyvelés: {maradt} hívás díja még nem ismert (foglalással számolva)")
    ugy = mrs.ugynokok(mappa, tanulo=a.tanulo)
    szerepek: dict[str, list] = {}
    for x in ugy:
        szerepek.setdefault(x["szerep"], []).append(x)
    futas_lista = json.loads((mappa / "futasok.json").read_text()) if (mappa / "futasok.json").exists() else []
    vez = mrs.vezerlo(mappa, a.tanulo, ugy, futas_lista)
    tsor = [(f"{nev} ({len(v)} példány)", mrs.osszead(v)) for nev, v in sorted(szerepek.items())]
    if vez:
        tsor.append(("vezérlő", mrs.osszead(vez)))
    tsor.append(("összesen", mrs.osszead([o for _, o in tsor])))
    gepi = json.loads((mappa / "meres.json").read_text()) if (mappa / "meres.json").exists() else []
    futas = futas_lista
    szavak = json.loads((mappa / "szavak.json").read_text()) if (mappa / "szavak.json").exists() else {}
    bizonytalan = sum(any(w["forras"] in ("becsult", "gyanus") for w in v) for v in szavak.values())
    tul = sum(o.get("tulajdonos_uzenet", 0) for o in vez)
    md = [f"# Mérés: {a.tanulo} {epizod}", "", *mrs.tabla(tsor), "",
          f"- gépi idő: {perc(sum(x['s'] for x in gepi))} ({len(gepi)} futás); lánc: {len(futas)} futás, "
          f"{sum(x['kod'] == 1 for x in futas)} piros, {sum(x['kod'] == 3 for x in futas)} összeomlás",
          f"- TTS + Whisper: {dij['tts']} + {dij['whisper']} fizetős hívás; könyvelt {hu(dij['konyvelt'], 4)} USD, "
          f"még csak foglalt {hu(dij['foglalt'], 4)} USD",
          f"- becsült/gyanús szóidejű lépés: {bizonytalan}/{len(szavak)} "
          f"({hu(100 * bizonytalan / max(1, len(szavak)), 0)}%)",
          f"- vezérlő: {tul} tulajdonosi üzenet, várakozás {perc(sum(o.get('varakozas_s', 0) for o in vez))} "
          "(a falióra ezt kivonja); csak a videó menetének ablaka: "
          + ("; ".join(ablak_szoveg(o["ablak"])
                       + (f", párhuzamos videókkal megosztva ({', '.join(o['parhuzamos'])})" if o["parhuzamos"] else "")
                       for o in vez) or "nincs"),
          f"- ügynök-átiratok: {len(ugy)} (" + ", ".join(sorted(x['fajl'].name for x in ugy)) + ")", "",
          "API-egyenérték: Opus 5.5, USD/M token: bemenet 4, cache-olvasás 0,20, cache-írás 5 (1 ó: 8), kimenet 20. "
          "Codex-munkamenet („(Codex)”): a Codex-keretből, API-egyenérték nélkül (–); az összesen-sor USD-je csak a "
          "Claude-é."]
    (mappa / "meres.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    ossz = tsor[-1][1]
    sorok += [f"{nev}: {o['hivas']} hívás, {hu(o['beolvasott'] / 1e6)} M token, "
              f"{'Codex-keret' if o['usd'] is None else hu(o['usd']) + ' USD'}, "
              f"csúcs {o['csucs'] // 1000} e" for nev, o in tsor[:-1]][:20]
    sorok.append(f"összesen: {ossz['hivas']} hívás, {hu(ossz['beolvasott'] / 1e6)} M token, API-egyenérték "
                 f"{hu(ossz['usd'] or 0)} USD (Claude); TTS+Whisper könyvelt {hu(dij['konyvelt'], 4)} + foglalt "
                 f"{hu(dij['foglalt'], 4)} USD")
    sorok.append(f"részletek: {mappa / 'meres.md'}")
    print("\n".join(sorok))
    return 0


def ablak_szoveg(ablak: list[str]) -> str:
    """A vezérlő-ablak a meres.md-be: „2026-10-13 22:04–23:44”, más napra végződve a vége is dátummal (UTC)."""
    a, b = (x[:16].replace("T", " ") for x in ablak)
    return f"{a}–{b[11:] if a[:10] == b[:10] else b} UTC"


def kivagat(a, mappa: Path) -> int:
    """Az író kivágata: a lépés végállapotának 1080p-s állóképe az objektum dobozára vágva (legfeljebb 2)."""
    import lapok
    lepes, _, obj = a.kivagat.partition("/")
    ut = mappa / "futasok.json"
    f = json.loads(ut.read_text()) if ut.exists() else []
    utolso = max((i for i, x in enumerate(f) if x["mod"] == "atadas"), default=-1)
    if sum(x["mod"] == "kivagat" for x in f[utolso + 1:]) >= KIVAGAT_HATAR:
        print(f"MEGÁLLT: már {KIVAGAT_HATAR} kivágat készült ebben a körben")
        return 2
    if not obj or not (mappa / "render_naplo.json").exists():
        print("MEGÁLLT: --kivagat <lépés>/<obj>, és előbb egy zöld vagy piros 480p-s futás kell")
        return 2
    try:
        with video_zar(mappa):
            kep = rnd.allokep(mappa, mappa / "media", lepes, mappa / "video.log", IDOKORLAT_S)
            ki = lapok.iro_kivagat(mappa, lepes, obj, kep)
    except (Megallt, KeyError, ValueError, FileNotFoundError, subprocess.SubprocessError) as e:
        print(f"MEGÁLLT: kivágat: {e} (részletek: video.log)")
        return 2
    f.append({"mod": "kivagat", "kod": 0, "s": 0, "ido": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    ir(ut, f)
    print(f"KIVÁGAT {lepes}/{obj}: {ki}")
    return 0


def takarit(a, mappa: Path) -> int:
    if not (mappa / "nyugta.json").exists():
        print("MEGÁLLT: nincs nyugta.json (a --takarit csak a --vegleges és a tulajdonosi lezárás után)")
        return 2
    cel = (mappa / "media").resolve()
    meret = sum(p.stat().st_size for p in cel.rglob("*") if p.is_file()) if cel.exists() else 0
    shutil.rmtree(cel, ignore_errors=True)
    print(f"TAKARÍTÁS {a.lap}: {cel} törölve ({meret / 1e6:.0f} MB)")
    return 0


# --- belépés ---------------------------------------------------------------------------------------

def mappa_utja(a) -> Path:
    if a.mappa:
        if os.environ.get("VIDEO_CSONK") != "1":
            raise Megallt("--mappa csak a tesztcsonkkal (VIDEO_CSONK=1) használható")
        return Path(a.mappa).resolve()
    if os.environ.get("VIDEO_CSONK") == "1":
        raise Megallt("VIDEO_CSONK=1 csak --mappa mellett (a valódi munkamappán a csonk nem futhat)")
    from school_notes2.local import common
    return common.load(a.tanulo).repo / ".school-notes" / "out" / "video" / a.tantargy / a.lap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tanulo")
    ap.add_argument("tantargy")
    ap.add_argument("lap", help="<lap>-<n>, például halmazok-1")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--atadas", action="store_true")
    g.add_argument("--vegleges", action="store_true")
    g.add_argument("--meres", action="store_true")
    g.add_argument("--takarit", action="store_true")
    g.add_argument("--kivagat", metavar="LÉPÉS/OBJ")
    ap.add_argument("--valtozott", action="store_true")
    ap.add_argument("--cim", help="a nyitó- és a záróképen (--vegleges); alapból a témalap címsora")
    ap.add_argument("--tantargy-nev", help="a nyitó- és a záróképen (--vegleges); alapból a tantárgyi index címsora")
    ap.add_argument("--mappa", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.valtozott and not a.atadas:
        ap.error("--valtozott csak --atadas mellett")
    if (a.cim or a.tantargy_nev) and not a.vegleges:
        ap.error("--cim és --tantargy-nev csak --vegleges mellett")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*-\d+", a.lap) or not re.fullmatch(r"[a-z0-9-]+", a.tantargy):
        ap.error("a lap alakja <lap>-<n> (kisbetű, szám, kötőjel), a tantárgy kisbetűs azonosító")
    try:
        mappa = mappa_utja(a)
    except Exception as e:  # noqa: BLE001  (sn-konfiguráció: hiányzó tanuló vagy repó)
        print(f"MEGÁLLT: {e}")
        return 2
    if not mappa.is_dir():
        print(f"MEGÁLLT: nincs munkamappa: {mappa}")
        return 2
    if a.meres or a.takarit or a.kivagat:
        try:
            return meres(a, mappa) if a.meres else takarit(a, mappa) if a.takarit else kivagat(a, mappa)
        except Exception as e:  # noqa: BLE001  (a szerződésben az 1 a piros; minden más megállás 2)
            print(f"MEGÁLLT: {type(e).__name__}: {str(e)[:300]}")
            return 2
    lanc = Lanc(a, mappa)
    try:
        with video_zar(mappa):
            kod = lanc.fut()
    except Megallt as e:
        kod, lanc.sorok = 2, lanc.sorok + [f"MEGÁLLT: {e}"]
    except Exception as e:  # noqa: BLE001
        with open(lanc.log_ut, "a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        uzenet = getattr(e, "message", None) or str(e)
        todo = getattr(e, "todo", "")
        kod = 2
        lanc.sorok.append(f"MEGÁLLT: {type(e).__name__}: {uzenet[:300]}" + (f" → {todo}" if todo else ""))
        if type(e).__module__.split(".")[0] not in ("school_notes2",) and "LockTimeout" not in type(e).__name__:
            lanc.sorok.append("(eszközhiba? a traceback a video.log-ban; jelentsd, és állj meg)")
    try:
        hanyadik, piros, omlas = lanc.futas_naplo(kod)
        lanc.meres_ir(kod)
    except (OSError, ValueError, KeyError, TypeError) as e:     # sérült futasok.json vagy meres.json
        hanyadik = piros = omlas = 0
        kod, lanc.sorok = 2, lanc.sorok + [f"MEGÁLLT: futásnapló: {type(e).__name__}: {str(e)[:200]}"]
    fej = (f"VIDEÓ {a.lap} · {'1080p30' if lanc.minoseg == '1080p' else '480p30'} · "
           + (f"{hanyadik}. futás ({piros} piros, {omlas} összeomlás)" if lanc.mod == "alap" else lanc.mod)
           + f" · {perc(time.monotonic() - lanc.t0)} · kód {kod}")
    lab = []
    if lanc.mod == "alap" and kod == 1 and piros >= PIROS_HATAR:
        lab.append(f"{piros}. piros futás: add át (iro-jelentes.md: maradék hibák, saját vagy téves kapuhiba)")
    if lanc.mod == "alap" and kod == 3 and omlas >= OSSZEOMLAS_HATAR:
        lab.append(f"{omlas}. összeomlás: lépj ki, jelentsd")
    if getattr(lanc, "iro_lapok", None):
        lab.append(lanc.iro_lapok)
    lab.append("részletek: kapu.json, tabla.txt, meres.json, video.log")
    sorok = [fej] + lanc.sorok
    if len(sorok) + len(lab) > MAX_SOR:
        sorok = sorok[:MAX_SOR - len(lab) - 1] + [f"… további {len(sorok) - (MAX_SOR - len(lab) - 1)} sor: "
                                                   "kapu.json, tabla.txt"]
    kimenet = "\n".join(sorok + lab)
    (mappa / "osszefoglalo.txt").write_text(kimenet + "\n", encoding="utf-8")
    print(kimenet)
    return kod


if __name__ == "__main__":
    sys.exit(main())
