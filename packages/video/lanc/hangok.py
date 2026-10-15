"""Hang és szavak: TTS lépésenként, Whisper minden lépésre (gyorsítótárral, újrapróbálással),
illesztés, K10-újrapróbálás, videókeret. A lépések PARHUZAMOS szálon futnak; az eredmény a lépések
sorrendjében áll össze, így a kimenet a soros futáséval bájtra azonos. A fizetős hívás csak a
`school_notes2` `Paid`-jén át megy (ledger, gyorsítótár, podcastkeret); a kulcsot az `sn`-kód olvassa
(`podcast_names._client`). A podcast.lock-ot hívásonként csak a keretellenőrzés + foglalás és a
ledger-zárás idejére fogja a lánc (a gyorsítótár olvasása és a válaszra várás zár nélkül megy), így a
párhuzamos láncok és az `sn podcast` nem várnak egymásra a teljes hanglépésen át.

Kimenet a mappában: hang/<lépés>.wav (24 kHz, a lépés utáni csenddel), hang.wav (48 kHz, hangosságra
igazítva), hangido.json (a hang.py sémája + `szunetek`: a beszéd belső szünetei), szavak.json,
horgonyok.json.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import signal
import sys
import threading
import time
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

GYOKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GYOKER))
import hang as proba_hang  # noqa: E402  (a próba hang.py-ja: VOICE, STYLE, szünetek, összefűzés)

from . import szavak as sz  # noqa: E402

RATE = 24000
WHISPER_PROBA = 5                     # szóidő nélküli válasznál ennyi új kérés (új `user` mező)
MIN_SZUNET_S = 0.15                   # ennél hosszabb csend a beszéden belül: belső szünet
TAGOLT = "A számokat tagoltan, egyértelműen ejtsd."      # a K10 új TTS-kérésének plusz mondata (számeltérés)
PONTOS = "Minden szót pontosan, a leírt alakjában ejts ki."   # ugyanez szóváltozásnál
KERET_VIDEO = Decimal("1")
KERET_ELSO, KERET_TOVABBI = Decimal("0.5"), Decimal("0.2")
PARHUZAMOS = 4                        # egyszerre ennyi lépés kérései futnak (TTS, Whisper)
ZAR_POLL_S = 0.05                     # a podcast.lock próbálkozási köze (a zár hívásonként rövid)
ZARAS_VARAS_S = 3.0                   # egy ledger-zárás ennyit vár a zárra, aztán függő (a fizetos végén íródik)
MASIK_VAR_S = 45.0                    # ugyanezt a kérést egy másik folyamat épp küldi: ennyit várunk a válaszára
MASIK_FRISS_S = 300                   # a másik folyamat `sent` bejegyzése ennél frissebb: még úton lehet
KULCS = ("kind", "learner", "episode", "request_sha256", "started_at")   # egy ledger-bejegyzés azonosítója


class Megallt(Exception):
    """A lánc megáll (2-es kód): keret, zár, verzió, hiányzó vagy hibás bemenet."""


class MarKesz(Exception):
    """A foglalás pillanatában a kérés válasza már a gyorsítótárban van (egy másik lánc kifizette)."""


def ir(path: Path, adat) -> None:
    """JSON tmp-fájlba, aztán átnevezés (megszakadt futás nem hagy fél fájlt)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(adat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def tts_keres(text: str, tagolt: bool = False, pontos: bool = False) -> dict:
    from school_notes2.podcast import speech
    return {"model": speech.MODEL, "voice": proba_hang.VOICE, "response_format": "pcm",
            "instructions": proba_hang.STYLE + (" " + TAGOLT if tagolt else "") + (" " + PONTOS if pontos else ""),
            "input": text}


def beszed_szunetek(pcm: bytes, rate: int = RATE) -> tuple[float, float, list]:
    """A beszéd kezdete, vége és belső szünetei (s): 10 ms-os keretek RMS-e -55 dBFS-hez mérve (hang.py)."""
    minta = array("h")
    minta.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        minta.byteswap()
    meret = int(rate * proba_hang.KERET_S)
    kuszob2 = (32768 * 10 ** (proba_hang.CSEND_DB / 20)) ** 2
    hangos = [i for i in range(0, len(minta), meret)
              if sum(x * x for x in minta[i:i + meret]) / len(minta[i:i + meret]) > kuszob2]
    if not hangos:
        return 0.0, 0.0, []
    szunetek = [[round((a + meret) / rate, 3), round(b / rate, 3)] for a, b in zip(hangos, hangos[1:])
                if (b - a - meret) / rate >= MIN_SZUNET_S]
    return round(hangos[0] / rate, 3), round(min(len(minta), hangos[-1] + meret) / rate, 3), szunetek


# --- szolgáltatók: a valódi (Paid) és a tesztcsonk ugyanazzal a felülettel ---------------------------

@dataclass
class Szamlalo:
    uj_tts: int = 0
    uj_whisper: int = 0
    tts_foglalt: Decimal = Decimal(0)
    whisper_foglalt: Decimal = Decimal(0)


class Valodi:
    """OpenRouter a `school_notes2` útján: podcast.lock, ledger, gyorsítótár, videó- és futáskeret."""

    csonk = False

    def __init__(self, tanulo: str, epizod: str, *, local=None):
        from school_notes2.local import common
        from school_notes2.local.podcast_names import _client
        self.tanulo, self.epizod = tanulo, epizod
        self.settings = (local or common.load(tanulo)).podcast_settings()
        self.client = _client(self.settings, time.sleep)
        self.paid, self.szam, self.futas_keret = None, Szamlalo(), KERET_TOVABBI
        self._szalak_init()

    def _szalak_init(self) -> None:
        self._szal_zar = threading.Lock()      # a folyamaton belül egy szál próbálja a podcast.lock-ot
        self._szam_zar = threading.Lock()
        self._kulcs_zarak: dict[str, threading.Lock] = {}
        self._zar_lejart = None
        self._fuggo: list[dict] = []           # zár nélkül maradt ledger-zárások: a következő zár alatt íródnak
        self._helyi = threading.local()        # a szál éppen futó lépése (a figyelmeztetések jelöléséhez)

    @contextlib.contextmanager
    def zar(self, mod: str):
        """A podcast.lock rövid ideig. `mod`: "foglalas" (keretellenőrzés és foglalás, lock_timeout_s-ig vár),
        "zaras" (ledger-zárás, csak ZARAS_VARAS_S-ig; ha nem kapja meg, a hívó függőnek teszi), "vegso" (a
        függők kiírása a `fizetos` végén, lock_timeout_s-ig). Ha a foglalás várakozása egyszer lejárt (pl. az
        `sn podcast` fogja), a foglalás és a zárás nem vár újra (a zárás azonnal függő lesz)."""
        from school_notes2.images.budget import LockTimeout, images_lock
        with self._szal_zar:
            if self._zar_lejart is not None and mod != "vegso":
                raise LockTimeout(str(self._zar_lejart))
            varas = ZARAS_VARAS_S if mod == "zaras" else self.settings.lock_timeout_s
            z = images_lock(self.settings.lock_path, varas, poll_s=ZAR_POLL_S, what="podcast")
            try:
                z.__enter__()
            except LockTimeout as e:
                if mod == "foglalas":
                    self._zar_lejart = e
                raise
            try:
                yield
            finally:
                z.__exit__(None, None, None)

    def _kulcs(self, sha: str) -> threading.Lock:
        """Ugyanaz a kérés (azonos sha) egyszerre egy szálon: a második már a gyorsítótárból kapja."""
        with self._szam_zar:
            return self._kulcs_zarak.setdefault(sha, threading.Lock())

    def _fuggo_ki(self, csendben: bool) -> None:
        """A függő ledger-zárások kiírása: még egyszer kivárja a zárat (lock_timeout_s)."""
        from school_notes2.images.budget import LockTimeout
        if not self._fuggo:
            return
        try:
            with self.zar("vegso"):
                self.paid.ledger.ujraolvas()
                self.paid.ledger.save()
        except LockTimeout:
            if not csendben:
                raise

    @contextlib.contextmanager
    def fizetos(self, keresek: list[dict]):
        from school_notes2.images.budget import LockTimeout
        from school_notes2.podcast import speech
        from school_notes2.podcast.ledger import Cache, Ledger

        lanc = self

        class KozosLedger(Ledger):
            """A ledger a zár alatt mindig a lemezről friss: más lánc vagy az `sn podcast` közben írhatott."""

            def ujraolvas(self) -> None:
                Ledger.__init__(self, self.settings)
                with lanc._szam_zar:
                    fuggo, lanc._fuggo = lanc._fuggo, []
                for call in fuggo:
                    self._beir(call)

            def _beir(self, call: dict) -> None:
                """A saját bejegyzés frissítése állapottól függetlenül (kétszeri zárásnál is egy marad);
                új bejegyzés csak akkor, ha ezzel a kulccsal nincs (pl. közben új tanévi fájl)."""
                egyezo = [c for c in self.value["calls"] if all(c.get(k) == call.get(k) for k in KULCS)]
                if egyezo:
                    egyezo[-1].update(call)
                else:
                    self.value["calls"].append(dict(call))

            def close(self, call, state, **fields):
                call.update(state=state, **fields)
                try:
                    with lanc.zar("zaras"):
                        self.ujraolvas()
                        self._beir(call)
                        self.save()
                    return
                except LockTimeout:
                    pass
                with lanc._szam_zar:
                    lanc._fuggo.append(call)

        class VideoPaid(speech.Paid):
            def _kesz(self, kind, sha) -> bool:
                return (self.cache.audio(sha) if kind == "speech" else self.cache.result(sha)) is not None

            def _open(self, kind, sha, reserve):
                for vart in (False, True):
                    with lanc.zar("foglalas"):
                        self.ledger.ujraolvas()
                        # közben egy másik lánc kifizethette ugyanezt a kérést: akkor a gyorsítótárból jön
                        if self._kesz(kind, sha):
                            raise MarKesz(sha)
                        if vart or not masik_uton(self.ledger.value["calls"], sha, self.opened):
                            return self._foglal(kind, sha, reserve)
                    # egy másik folyamat épp most küldi ugyanezt: a válaszára várunk (zár nélkül)
                    vege = time.monotonic() + MASIK_VAR_S
                    while time.monotonic() < vege:
                        if self._kesz(kind, sha):
                            raise MarKesz(sha)
                        time.sleep(0.5)

            def _foglal(self, kind, sha, reserve):
                """Keretellenőrzés és foglalás; a hívó fogja a zárat."""
                futas = sum((Ledger.cost(c) for c in self.opened), Decimal(0))
                video = self.ledger.episode_cost(self.episode, lanc.tanulo)
                if futas + reserve > lanc.futas_keret:
                    raise Megallt(f"futáskeret: {futas} + {reserve} > {lanc.futas_keret} USD ({kind}); "
                                  "a fizetett rész a gyorsítótárban marad")
                if video + reserve > KERET_VIDEO:
                    raise Megallt(f"videókeret: {video} + {reserve} > {KERET_VIDEO} USD ({self.episode})")
                n = len(self.warnings)
                # a foglalás a zár elengedése előtt a ledgerben van: a következő hívás már látja
                call = super()._open(kind, sha, reserve)
                sid = getattr(lanc._helyi, "sid", "")
                self.warnings[n:] = [f"{sid}: {w}" for w in self.warnings[n:]]
                return call

        self.paid = VideoPaid(self.client, KozosLedger(self.settings), Cache(self.settings.cache_dir), self.epizod)
        uj = sum(len(k["input"]) for k in keresek if self.paid.cached_speech(k) is None)
        # első futás: a hang nagyobb része még nincs a gyorsítótárban
        self.futas_keret = KERET_ELSO if 2 * uj > sum(len(k["input"]) for k in keresek) else KERET_TOVABBI
        try:
            yield
        except BaseException:
            self._fuggo_ki(csendben=True)
            raise
        self._fuggo_ki(csendben=False)

    def _szamol(self, tts: bool, foglalas: Decimal, elojel: int) -> None:
        with self._szam_zar:
            if tts:
                self.szam.uj_tts += elojel
                self.szam.tts_foglalt += elojel * foglalas
            else:
                self.szam.uj_whisper += elojel
                self.szam.whisper_foglalt += elojel * foglalas

    def tts(self, sid: str, keres: dict) -> bytes:
        from school_notes2.podcast.ledger import request_sha, speech_reserve
        self._helyi.sid = sid
        foglalas = speech_reserve(len(keres["input"]))
        with self._kulcs(request_sha(keres)):
            uj = self.paid.cached_speech(keres) is None
            if uj:
                self._szamol(True, foglalas, 1)
            try:
                return self.paid.speech(keres, len(keres["input"]))
            except MarKesz:
                self._szamol(True, foglalas, -1)
                return self.paid.speech(keres, len(keres["input"]))

    def whisper(self, sid: str, pcm: bytes, proba: int) -> list | None:
        """Szóidők; szó nélküli vagy hibás válasznál (BadWork) None (a hívó új próbát kér). Átmeneti vagy
        ismeretlen kimenetelű hiba (Transient, Unknown) nem fogyaszt próbát: megállítja a láncot."""
        from school_notes2.podcast import names, openrouter
        from school_notes2.podcast.audio import speech_mp3
        from school_notes2.podcast.ledger import cache_sha, transcription_reserve
        from school_notes2.state.errors import BadWork
        self._helyi.sid = sid
        keres = {"model": names.WHISPER, "temperature": 0, "response_format": "verbose_json", "language": "hu",
                 "timestamp_granularities": ["word", "segment"], "provider": {"require_parameters": True},
                 "user": f"video-{proba}",
                 "input_audio": {"data": base64.b64encode(speech_mp3(pcm)).decode(), "format": "mp3"}}
        foglalas = transcription_reserve(len(pcm) / 2 / RATE)
        sha = cache_sha(keres)

        def hivas():
            return self.paid.json("transcription", openrouter.TRANSCRIPTION, keres, foglalas, expect="words")
        try:
            with self._kulcs(sha):
                if self.paid.cache.result(sha) is None:
                    self._szamol(False, foglalas, 1)
                try:
                    valasz = hivas()
                except MarKesz:
                    self._szamol(False, foglalas, -1)
                    valasz = hivas()
        except BadWork:
            return None
        return valasz["answer"].get("words") or None

    def kesz(self) -> dict:
        from school_notes2.podcast.ledger import Ledger
        p = self.paid
        futas = sum((Ledger.cost(c) for c in p.opened), Decimal(0)) if p else Decimal(0)
        video = Ledger(self.settings).episode_cost(self.epizod, self.tanulo) if p else Decimal(0)
        return {"futas_usd": futas, "futas_keret": self.futas_keret, "video_usd": video,
                "figyelmeztetes": sorted(p.warnings) if p else []}     # lépésazonosító szerint


class Csonk:
    """Tesztcsonk (VIDEO_CSONK=1): TTS és Whisper nélkül, a videotar-teszt/szintetikus.py szóidő-modelljével.
    A lépés hangja a szavak idején halk négyszögjel (a beszédhatár-mérés így valódi), egyébként csend;
    a Whisper a narráció szavait adja, a lépés `teszt_whisper` cseréivel (a K10-hez)."""

    csonk = True

    def __init__(self, narr: list):
        sys.path.insert(0, str(GYOKER / "videotar-teszt"))
        import szintetikus
        self.modell, self.szam = szintetikus, Szamlalo()
        self.lepesek = {f"{j['id']}-{n:02d}": l for j in narr for n, l in enumerate(j["lepesek"], 1)}

    @contextlib.contextmanager
    def fizetos(self, keresek):
        yield

    def _szavak(self, sid):
        lep = self.lepesek[sid]
        return self.modell.lepes_szavai(lep["text"], lep.get("teszt_whisper", {}))

    def tts(self, sid: str, keres: dict) -> bytes:
        szavak, _, _, veg = self._szavak(sid)
        minta = array("h", bytes(2 * round((veg + self.modell.FAROK_S) * RATE)))
        for w in szavak:
            for i in range(round(w["kezd_s"] * RATE), round(w["veg_s"] * RATE)):
                minta[i] = 200 if i % 2 else -200
        return minta.tobytes()

    def whisper(self, sid: str, pcm: bytes, proba: int) -> list:
        return [{"word": w["whisper"], "start": w["kezd_s"], "end": w["veg_s"]} for w in self._szavak(sid)[0]]

    def kesz(self) -> dict:
        return {"futas_usd": Decimal(0), "futas_keret": Decimal(0), "video_usd": Decimal(0), "figyelmeztetes": []}


# --- a lépés: hang, szavak, K10 --------------------------------------------------------------------

def szoidok(szolg, sid: str, pcm: bytes, kezd: int = 0) -> tuple[list, int]:
    """Whisper szóidőkkel; szó nélküli válasznál új kérés (új `user`), legfeljebb WHISPER_PROBA-szor."""
    for proba in range(kezd, kezd + WHISPER_PROBA):
        words = szolg.whisper(sid, pcm, proba)
        if words:
            return words, proba
    return [], kezd + WHISPER_PROBA - 1


def szam_hibak(szavak: list[dict]) -> list:
    """A kapu K10-szabálya (kapu.k10): a narráció száma, amelynek Whisper-értéke (`szavak.whisper_ertek`,
    „4 7” = 4,7) más vagy hiányzik → [[szó, Whisper-szöveg], …]. A lánc, a kapu és a nyugta így ugyanazt
    tekinti számeltérésnek."""
    return [[w["szo"], w.get("whisper")] for w in szavak if w.get("ertek") is not None
            and not _egyezik(w["ertek"], sz.whisper_ertek(w.get("whisper") or ""))]


def _egyezik(a, b) -> bool:                 # = kapu._egyezik
    return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9


def lepes(szolg, sid: str, text: str) -> dict:
    """Egy lépés: TTS, Whisper, illesztés; számeltérésnél (`szam_hibak`, a kapu szabálya) vagy szóváltozásnál (a Whisper más szót hallott,
    `szavak.valtozott_szavak`) (1) egy újraleírás, (2) egy új TTS a tagolt (szám) vagy pontos (szó) ejtés
    kérésével. Ha marad, a szavak `whisper` mezője mutatja: a kapu számnál K10-hibát, szónál K10-figyelmeztetést
    ad, a nyugta k10_ketseges-e a tulajdonosnak sorolja. `text` a narráció lépése a {…} horgonyjelekkel
    (a TTS-be jel nélkül megy)."""
    keres = tts_keres(proba_hang.tts_szoveg(text))

    def merni(pcm, words):
        kezd, veg, szun = beszed_szunetek(pcm)
        x = {"pcm": pcm, "beszed": (kezd, veg), "szunetek": szun, **sz.illeszt(text, words, (kezd, veg), szun)}
        x["szamhiba"] = szam_hibak(x["szavak"])
        return x

    def baj(x):
        return bool(x["szamhiba"] or x["szovaltozas"])

    pcm = szolg.tts(sid, keres)
    words, proba = szoidok(szolg, sid, pcm)
    r, k10 = merni(pcm, words), {}
    if words and baj(r):
        k10["ujraleiras"] = 1
        words2, _ = szoidok(szolg, sid, pcm, proba + 1)
        r2 = merni(pcm, words2) if words2 else r
        if words2 and not baj(r2):
            r = r2
        else:
            k10["uj_tts"] = 1
            pcm3 = szolg.tts(sid, tts_keres(proba_hang.tts_szoveg(text), tagolt=bool(r["szamhiba"]),
                                            pontos=bool(r["szovaltozas"])))
            words3, _ = szoidok(szolg, sid, pcm3)
            r3 = merni(pcm3, words3) if words3 else r
            if words3 and not baj(r3):
                r = r3
            else:
                if r["szamhiba"]:
                    k10["marad"] = r["szamhiba"]
                if r["szovaltozas"]:
                    k10["szo_marad"] = r["szovaltozas"]
    r["k10"], r["van_szoido"] = k10, bool(words)
    return r


_KIMARADT = object()


def parhuzamos(fv, elemek: list, n: int | None = None) -> list:
    """`fv` minden elemre legfeljebb `n` (PARHUZAMOS) szálon; az eredmény az elemek sorrendjében, a
    befejezés sorrendjétől függetlenül. Hibánál (pl. keret) a még el nem kezdett elemek kimaradnak, a
    futók befejeződnek (a kifizetett rész a gyorsítótárba kerül), és a sorrendben első hiba megy tovább."""
    allj = threading.Event()

    def egy(x):
        if allj.is_set():
            return _KIMARADT
        try:
            return fv(x)
        except BaseException:
            allj.set()
            raise

    def sigterm(*_):
        raise Megallt("megszakítva (SIGTERM): a futó hívások lezárultak, a kifizetett rész a gyorsítótárban")

    fo = threading.current_thread() is threading.main_thread()
    regi = signal.signal(signal.SIGTERM, sigterm) if fo else None
    ex = ThreadPoolExecutor(max_workers=n or PARHUZAMOS)
    try:
        fut = [ex.submit(egy, x) for x in elemek]
        wait(fut)
    except BaseException:
        # Ctrl-C vagy SIGTERM: a sorban álló lépések nem indulnak, a futók befejeződnek (ledger lezárva)
        allj.set()
        ex.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        if fo:
            signal.signal(signal.SIGTERM, regi)
    ex.shutdown()
    for f in fut:
        if f.exception() is not None:
            raise f.exception()
    return [f.result() for f in fut]


def masik_uton(calls: list[dict], sha: str, sajat: list[dict]) -> bool:
    """Van-e ugyanerre a kérésre friss (MASIK_FRISS_S-nél újabb) `sent` bejegyzés, ami nem a mienk."""
    from datetime import datetime, timezone
    sajat_k = {tuple(c.get(k) for k in KULCS) for c in sajat}
    most = datetime.now(timezone.utc)
    for c in calls:
        if c.get("request_sha256") == sha and c.get("state") == "sent" and tuple(c.get(k) for k in KULCS) not in sajat_k:
            try:
                if (most - datetime.fromisoformat(c["started_at"])).total_seconds() < MASIK_FRISS_S:
                    return True
            except (KeyError, TypeError, ValueError):
                continue
    return False


def konyvel(settings, client, epizod: str, tanulo: str, sleep=time.sleep, korok: int = 4,
            szunet: float = 15) -> tuple[list, int]:
    """A videó hívásainak díja az OpenRouterből (a `Ledger.backfill` megfelelője, --meres): a lekérdezés és a
    várakozás zár nélkül, minden mentés a podcast.lock alatt friss ledgerre, csak a kulccsal egyező saját
    bejegyzések díját írja (a közben más által írt bejegyzések megmaradnak). Visszaad: (saját hívások, díj nélkül maradt)."""
    from school_notes2.images.budget import images_lock
    from school_notes2.podcast.ledger import Ledger

    def sajat(led):
        return [c for c in led.value["calls"] if c["episode"] == epizod and c["learner"] == tanulo]

    def nyitott(led):
        return [c for c in sajat(led) if c.get("cost_usd") is None and c.get("generation_id") and c.get("state") == "ok"]

    for n in range(korok):
        if not nyitott(Ledger(settings)):
            break
        if n:
            sleep(szunet)
        arak = {}
        for c in nyitott(Ledger(settings)):
            dij = client.generation_cost(c["generation_id"])
            if dij is not None:
                arak[tuple(c.get(k) for k in KULCS)] = dij
        if arak:
            with images_lock(settings.lock_path, settings.lock_timeout_s, what="podcast"):
                led = Ledger(settings)
                for c in led.value["calls"]:
                    dij = arak.get(tuple(c.get(k) for k in KULCS))
                    if dij is not None and c.get("cost_usd") is None:
                        c.update(cost_usd=dij, cost_source="openrouter /generation")
                led.save()
    led = Ledger(settings)
    return sajat(led), len(nyitott(led))


def hang_es_szavak(mappa: Path, narr: list, szolg, log) -> dict:
    """Minden lépés hangja és szavai (PARHUZAMOS szálon, az eredmény lépéssorrendben); a fájlok kiírása;
    visszaad: összesítő a jelentéshez."""
    lepesek = [(f"{j['id']}-{n:02d}", j, n, l) for j in narr for n, l in enumerate(j["lepesek"], 1)]
    keresek = [tts_keres(proba_hang.tts_szoveg(l["text"])) for *_, l in lepesek]
    (mappa / "hang").mkdir(exist_ok=True)
    ido, szavak_ki, horg_ki, reszek, k10 = {"rate": RATE, "lepesek": []}, {}, {}, [], {}
    nincs_szoido = 0
    with szolg.fizetos(keresek):
        eredmenyek = parhuzamos(lambda x: lepes(szolg, x[0], x[3]["text"]), lepesek)
    for (sid, jel, n, lep), r in zip(lepesek, eredmenyek):
        nincs_szoido += not r["van_szoido"]
        if r["k10"]:
            k10[sid] = r["k10"]
        gap = int(proba_hang.szunet_s(n, jel["lepesek"], lep) * RATE)
        ido["lepesek"].append({"id": sid, "jelenet": jel["id"], "minta": len(r["pcm"]) // 2 + gap,
                               "szunet_minta": gap, "beszed_kezd_s": r["beszed"][0], "beszed_veg_s": r["beszed"][1],
                               "szunetek": r["szunetek"], "text": lep["text"],
                               "horgonyok": proba_hang.horgonyok(lep["text"])})
        szavak_ki[sid] = r["szavak"]
        if r["horgonyok"]:
            horg_ki[sid] = r["horgonyok"]
        ut = mappa / "hang" / f"{sid}.wav"
        adat = r["pcm"] + b"\0\0" * gap
        if not ut.exists() or _wav_pcm(ut) != adat:
            with wave.open(str(ut.with_suffix(".tmp")), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(adat)
            ut.with_suffix(".tmp").replace(ut)
        reszek.append(ut)
    ir(mappa / "hangido.json", ido)
    ir(mappa / "szavak.json", szavak_ki)
    ir(mappa / "horgonyok.json", horg_ki)
    _hang_wav(mappa, reszek, ido, szolg.csonk, log)
    return {"lepes": len(lepesek), "nincs_szoido": nincs_szoido, "k10": k10, "szam": szolg.szam,
            "hossz_s": sum(s["minta"] for s in ido["lepesek"]) / RATE}


def _wav_pcm(ut: Path) -> bytes:
    with wave.open(str(ut)) as w:
        return w.readframes(w.getnframes())


def _hang_wav(mappa: Path, reszek: list, ido: dict, csonk: bool, log) -> None:
    """hang.wav: a lépések egymás után, 48 kHz, hangosságra igazítva (a csonknál csend); csak ha változott."""
    h = hashlib.sha256(b"csonk" if csonk else b"")
    for p in reszek:
        h.update(p.name.encode() + hashlib.sha256(p.read_bytes()).digest())
    jegy, wav = mappa / "hang" / "osszefuzes.sha256", mappa / "hang.wav"
    if wav.exists() and jegy.exists() and jegy.read_text() == h.hexdigest():
        return
    if csonk:
        minta = sum(s["minta"] for s in ido["lepesek"]) * proba_hang.OUT_RATE // RATE
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(proba_hang.OUT_RATE), w.writeframes(bytes(2 * minta))
    else:
        with contextlib.redirect_stdout(log):
            proba_hang.hang_osszefuz(mappa, reszek)
    try:
        with contextlib.redirect_stdout(log):
            proba_hang.hang_ellenoriz(wav, ido)
    except SystemExit as e:
        raise Megallt(f"eszközhiba: {e}") from None
    jegy.write_text(h.hexdigest())


def idoterv_szavakkal(mappa: Path, fps: int) -> dict:
    """idoterv.json a próba idoterv.py-jával, lépésenként a `szavak` listával (szó, érték, kocka)."""
    import idoterv
    ido = json.loads((mappa / "hangido.json").read_text(encoding="utf-8"))
    horg = json.loads((mappa / "horgonyok.json").read_text(encoding="utf-8"))
    szavak = json.loads((mappa / "szavak.json").read_text(encoding="utf-8"))
    kezi_ut = mappa / "kezi.json"
    kezi = json.loads(kezi_ut.read_text(encoding="utf-8")) if kezi_ut.exists() else {}
    try:
        terv = idoterv.terv(ido, horg, kezi, fps)
    except SystemExit as e:
        raise Megallt(f"idoterv: {e}") from None
    for lep in terv["lepesek"]:
        lep["szavak"] = [{"szo": w["szo"], "ertek": w["ertek"], "szo_s": round(lep["hang_kezd_s"] + w["kezd_s"], 4),
                          "kocka": min(max(idoterv.s_kocka(lep["hang_kezd_s"] + w["kezd_s"] - idoterv.ELORE_S, fps),
                                           lep["kezd_kocka"]), lep["veg_kocka"] - 1),
                          "forras": w["forras"]} for w in szavak[lep["id"]]]
    ir(mappa / "idoterv.json", terv)
    return terv
