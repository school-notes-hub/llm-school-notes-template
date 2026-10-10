"""The blind name check (the measured method of 2026-10-07, `kiejtes/biro/biro.py` and
`adas.py`): for every occurrence of a listed name in a scene, Whisper (`openai/whisper-large-v3`,
Hungarian, word times) transcribes the whole scene; the name is cut out at the quietest 10 ms
next to its neighbour words; the audio model (`google/gemini-3.8-flash`) writes down what it
hears **without** the target (blind), three times. A name is verified when all three blind
transcriptions equal a target and Whisper wrote the name where it stands. The measurement (0/12
false accepts, a good clip passes 3 times in 5) asked Whisper for a target literally; the 0.4.1
Whisper condition (`whisper_heard`: the spelling too) is not measured.

Since sn 0.4.1 (receipt `names_version` 2; the alignment and the Whisper check live in `align.py`):

* **Whisper check per occurrence, by spelling too** (`whisper_heard`): Whisper writes a name
  mostly as it is spelled (`Kossuth`, `Széchenyi`), so its words at the name are compared with
  the form and the targets, accents aside, a case ending (`ENDINGS`) in the last word and – from 5
  letters on – one consonant more or less allowed;
  sn 0.4.0 looked for a pronunciation target (`kosut`) in the whole scene's text and so almost
  never found one.
* **Where each name is** (`place`): the name's own Whisper words – also where the text and
  Whisper disagree around it (numbers, misheard words) – and a later name only after the earlier
  one, so two names never get the same moment. The moment (`timing` `word`) is the first of
  those words' start; without it the receipt gives only a span: `segment` (some OpenRouter
  providers answer with segment times only – no word times, so no cut and no blind check) or
  `gap` (Whisper wrote nothing like the name between its neighbours, e.g. a 30 s window it
  skipped).
* **The cut** stays the measured one (one matching neighbour word on each side) unless another
  listed name stands between those neighbours or a neighbour is another name's word: then the
  name's own Whisper words with the word next to them on each side, and where that word is
  another name's, the cut ends at the boundary between the two (one name per clip, `locate`).

A name that is not verified does not stop the episode: it goes into the receipt with the moment
it is heard in the final episode (or the span it lies in), for the owner, who listens to the
finished episode only. `CacheOnly` replays a released episode's check from the cache
(`sn podcast --names-only`)."""

import base64
import io
import json
import math
import re
import sys
import wave
from array import array
from decimal import Decimal

from . import openrouter
from .align import (SIMILAR, TIMING_GAP, TIMING_NONE, TIMING_SEGMENT, TIMING_WORD, _equal, compact,  # noqa: F401
                    norm_ph, place, timeline, whisper_heard, words_of)
from .ledger import JUDGE_RESERVE, cache_sha, transcription_reserve
from .speech import RATE

WHISPER = "openai/whisper-large-v3"
JUDGE = "google/gemini-3.8-flash"
REPEATS = 3
RECEIPT_VERSION = 2   # the receipt's `names` (`names_version`; without it: 1, sn 0.4.0)

PROMPT_BLIND = """Fonetikus lejegyző vagy. A hangfelvételen egy gépi felolvasó (TTS) magyar mondatot mond. Jegyezd le PONTOSAN, hangról hangra, ahogy a vizsgált név vagy szó ténylegesen elhangzik – nem azt, ahogy írni szokás, és nem azt, ahogy helyesen kellene ejteni.

A lejegyzés magyar fonetikus átírás, a magyar helyesírás hangértékeivel: s = [ʃ] (mint a „sas” szóban), sz = [s], z = [z], zs = [ʒ], cs = [tʃ], c = [ts], ty = [c], gy = [ɟ], ny = [ɲ], j = [j]; az ékezetes magánhangzó hosszú (á [aː], é [eː], í, ó, ő, ú, ű), az ékezet nélküli rövid (a [ɒ], e [ɛ], i, o, ö, u, ü); a hosszú mássalhangzót kettőzve írd. Ne használj IPA-jelet, idegen betűt (w, x, q, th, ch, y) és eredeti helyesírást; csak magyar betűket.

Különösen figyelj: a magánhangzók hosszára (a/á, e/é, o/ó, ö/ő, i/í, u/ú); a magyar rövid a [ɒ] hangot a-nak írd, ne o-nak; a mássalhangzók zöngésségére és pontos hangjára (s/sz, sz/z, zs/z, cs/c/ty); a mássalhangzók hosszára; ha a gép idegen nyelvre vált (angolos, németes ejtés), azt is úgy jegyezd le, ahogy szól (például a magyar s helyett [s] hangot „sz”-szel).

A felvétel szövege tájékozódásul; a [NÉV] helyén a vizsgált név vagy szó szól: „{context}”

A válaszod kizárólag egy JSON-objektum legyen, más szöveg nélkül:
{{"hallott": "<a név vagy szó magyar fonetikus átírásban, csak a [NÉV] helyén elhangzott rész>", "megjegyzes": "<ha valamelyik hangban bizonytalan vagy, melyikben; különben üres>"}}"""


def occurrences(text: str, names: list[dict]) -> list[tuple[dict, int, int]]:
    """(name entry, first word index, end index) of every listed name in `text`, in text order;
    a word belongs to one occurrence only (the earlier-listed name wins)."""
    words = [w for w, _ in words_of(text)]
    used, out = set(), []
    for entry in names:
        form = entry["form"].split()
        for i in range(len(words) - len(form) + 1):
            if any(j in used for j in range(i, i + len(form))):
                continue
            if [re.sub(r"[^\w-]", "", w) for w in words[i:i + len(form)]] == form:
                out.append((entry, i, i + len(form)))
                used.update(range(i, i + len(form)))
    return sorted(out, key=lambda o: o[1])


def wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _rms(pcm: bytes, frame: int, size: int) -> float:
    samples = array("h")
    samples.frombytes(pcm[frame * size * 2:(frame + 1) * size * 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples) + 1e-9)


def refine(pcm: bytes, t: float, lo: float, hi: float, hop: float = 0.01) -> float:
    """The middle of the quietest 10 ms frame around `t` (±0.12 s, kept inside [lo, hi])."""
    size = int(RATE * hop)
    frames = len(pcm) // 2 // size
    a, b = max(lo, t - 0.12), min(hi, t + 0.12)
    i0 = int(a / hop)
    i1 = min(max(i0 + 1, int(b / hop)), frames)
    if i0 >= i1:
        return t
    best = min(range(i0, i1), key=lambda i: _rms(pcm, i, size))
    return (best + 0.5) * hop


class NotCached(Exception):
    """`CacheOnly`: the answer of this call is not in the cache (it would be a paid call)."""


class CacheOnly:
    """The `Paid` interface for the recount of a released episode (`sn podcast --names-only`):
    every answer comes from the cache by the same key as the paid run, nothing is sent."""

    def __init__(self, cache):
        self.cache = cache
        self.missing: list[str] = []

    def json(self, kind: str, url: str, request: dict, reserve, cache_key: dict | None = None,
             expect: str = "") -> dict:
        found = self.cache.result(cache_sha(request, cache_key))
        if found is None:
            self.missing.append(kind)
            raise NotCached(kind)
        return found


def _left_edge(pcm: bytes, t: float) -> float:
    return refine(pcm, t, max(0.0, t - 0.1), t + 0.03)


def _right_edge(pcm: bytes, t: float, total: float) -> float:
    return refine(pcm, t, t - 0.03, min(total, t + 0.1))


def _own_cut(tw, ww, t2w, pcm, i0, i1, window, others, total) -> tuple[float, float, list, list]:
    """The name's own cut (`locate`): its Whisper words and the word next to them on each side,
    or the boundary where that word is another name's."""
    s, e = window
    w2t = {w: t for t, w in t2w.items()}
    left, right = (s - 1 if s > 0 else None), (e if e < len(ww) else None)
    p, n = w2t.get(s - 1), w2t.get(e)
    if left in others:
        before, start = [], _left_edge(pcm, ww[s][1])
    else:
        before = ([w for w, _ in tw[:i0]] if left is None else
                  [w for w, _ in tw[p:i0]] if p is not None and p < i0 else [ww[left][3]])
        start = _left_edge(pcm, ww[left][1]) if left is not None else 0.0
    if right in others:
        after, end = [], _right_edge(pcm, ww[e - 1][2], total)
    else:
        after = ([w for w, _ in tw[i1:]] if right is None else
                 [w for w, _ in tw[i1:n + 1]] if n is not None and n >= i1 else [ww[right][3]])
        end = _right_edge(pcm, ww[right][2], total) if right is not None else total
    return start, end, before, after


def locate(text: str, transcript: dict, pcm: bytes, i0: int, i1: int,
           window: tuple[int, int] | None = None, others: frozenset = frozenset(),
           tight: bool = False) -> tuple[float, float, str]:
    """(start, end, context) of a name occurrence in the scene audio, the outer edges moved to the
    quietest frame nearby; the context is the text with [NÉV] for the name.

    The measured method: the text's words are aligned with Whisper's; the cut keeps one matching
    neighbour word on each side, the unmatched words between become context. The name's own cut
    (`_own_cut`; `window` from `place`, the name's own Whisper words) instead when `tight` (another
    listed name stands between the matching neighbours) or when a matching neighbour is another
    name's word (`others`: the Whisper word indices of the scene's other names): the Whisper word
    next to the window on each side (the text's word where Whisper agrees, else Whisper's) – unless
    that word is another name's: then the cut ends at the boundary between the two names, nothing
    of the other name in the clip. One listed name per clip."""
    tw = words_of(text)
    ww, timing = timeline(transcript)
    total = len(pcm) / 2 / RATE
    if timing != TIMING_WORD:
        raise ValueError("nincs szó-szintű időbélyeg")
    t2w = _equal(tw, ww)
    if window is None:
        entry = {"form": " ".join(w for w, _ in tw[i0:i1]), "targets": []}
        window = place(tw, ww, t2w, [(entry, i0, i1)])[0]["window"]
    prev = max((i for i in t2w if i < i0), default=None)
    nxt = min((i for i in t2w if i >= i1), default=None)
    left, right = (t2w[prev] if prev is not None else None), (t2w[nxt] if nxt is not None else None)
    if window is not None and (tight or left in others or right in others):
        start, end, before, after = _own_cut(tw, ww, t2w, pcm, i0, i1, window, others, total)
    elif window is None and tight:
        raise ValueError("a név nincs meg a Whisper szavai között")
    else:
        before = [w for w, _ in tw[(prev if prev is not None else 0):i0]]
        after = [w for w, _ in tw[i1:(nxt + 1 if nxt is not None else len(tw))]]
        start = _left_edge(pcm, ww[left][1]) if left is not None else 0.0
        end = _right_edge(pcm, ww[right][2], total) if right is not None else total
    return round(start, 3), round(end, 3), " ".join(before + ["[NÉV]"] + after)


def transcribe(paid, pcm: bytes) -> dict:
    """Whisper on the whole scene, sent as MP3 (as in the measured run)."""
    from .audio import speech_mp3
    request = {"model": WHISPER, "temperature": 0, "response_format": "verbose_json", "language": "hu",
               "timestamp_granularities": ["word", "segment"],
               "input_audio": {"data": base64.b64encode(speech_mp3(pcm)).decode(), "format": "mp3"}}
    answer = paid.json("transcription", openrouter.TRANSCRIPTION, request,
                       transcription_reserve(len(pcm) / 2 / RATE), expect="text")["answer"]
    return {"text": (answer.get("text") or "").strip(), "words": answer.get("words") or [],
            "segments": answer.get("segments") or []}


def blind(paid, clip: bytes, context: str, repeat: int) -> str | None:
    """One blind transcription of a cut name; None when the answer has no `hallott`."""
    request = {"model": JUDGE, "max_tokens": 1200, "reasoning": {"effort": "low"}, "usage": {"include": True},
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": PROMPT_BLIND.format(context=context)},
                   {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav_bytes(clip)).decode(),
                                                           "format": "wav"}}]}]}
    # the repeat makes the runs separate cache entries; it is not sent
    value = paid.json("judge", openrouter.CHAT, request, JUDGE_RESERVE, cache_key={**request, "sn_repeat": repeat},
                      expect="choices")
    text = (((value["answer"].get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    found = re.search(r"\{.*\}", text, re.S)
    try:
        heard = json.loads(found[0]).get("hallott") if found else None
    except ValueError:
        heard = None
    return str(heard) if heard else None


def _span(ww: list, first: int, end: int, total: float, timing: str) -> list[float]:
    """The seconds between the Whisper words before `first` and at `end` (a gap); with segment
    times the two neighbour words' whole segments (a word's own time is not known there)."""
    word = timing == TIMING_WORD
    a = (ww[first - 1][2] if word else ww[first - 1][1]) if first > 0 else 0.0
    b = (ww[end][1] if word else ww[end][2]) if end < len(ww) else total
    return [round(min(a, b), 3), round(max(a, b), 3)]


NOTE_NO_TIMES = "a Whisper-válaszban nincs időbélyeg: a hely ismeretlen, a vak ellenőrzés nem futott"
NOTE_SEGMENT = ("a Whisper-válaszban csak mondatszintű (szakasz-) idő van, szóidő nincs: a név nem vágható ki, "
                "a vak ellenőrzés nem futott")
NOTE_GAP_WORD = "a Whisper itt nem írt a névhez hasonlót: csak a két szomszéd szó közötti szakasz ismert"
NOTE_GAP_SEGMENT = ("a Whisper-válaszban csak mondatszintű idő van, és a név nincs meg a szavai között: csak a "
                    "szomszéd mondatok szakasza ismert")


def _heard_ok(heard: list, targets: list[str]) -> bool:
    return len(heard) == REPEATS and all(
        h is not None and any(compact(h) == compact(t) for t in targets) for h in heard)


def _blind_runs(paid, clip: bytes, context: str, targets: list[str], heard: list) -> None:
    """The blind transcriptions of one clip into `heard`: up to `REPEATS`, stopping at the first
    miss (an unusable answer gets one more run); a `NotCached` leaves the runs made so far."""
    for repeat in range(1, REPEATS + 1):
        value = blind(paid, clip, context, repeat)
        if value is None:
            value = blind(paid, clip, context, repeat + 10)
        heard.append(value)
        if value is None or not any(compact(value) == compact(t) for t in targets):
            break


def _unplaced(result: dict, timing: str, where: dict, ww: list, total: float) -> dict | None:
    """The result of a name the blind check cannot run on (no times, a gap), else None."""
    if timing == TIMING_NONE:
        return {**result, "note": NOTE_NO_TIMES}
    if where["window"] is None:
        return {**result, "timing": TIMING_GAP, "window_s": _span(ww, *where["gap"], total, timing),
                "note": (NOTE_GAP_WORD if timing == TIMING_WORD else NOTE_GAP_SEGMENT) + ", a vak ellenőrzés nem futott"}
    return None


def check_scene(paid, scene_text: str, pcm: bytes, names: list[dict]) -> list[dict]:
    """Every listed name in one scene, per occurrence: where it is heard (`timing`, `start_s`,
    `window_s`, scene-relative), whether Whisper wrote it there (`whisper`), the blind check's
    transcriptions (`heard`) and `verified` (all three blind transcriptions a target and Whisper
    wrote the name). The blind check runs only on a name with its own Whisper word times; without
    them (`segment`: the answer had segment times only, `gap`: Whisper wrote nothing like the name
    between its neighbours) the receipt says so in `note`. With `CacheOnly` a call that is not in
    the cache is not made: the item's `missing` names it (`transcription`, `judge`; the recount
    keeps the receipt's earlier result there and never writes `missing`)."""
    found = occurrences(scene_text, names)
    if not found:
        return []
    total = len(pcm) / 2 / RATE
    try:
        transcript = transcribe(paid, pcm)
    except NotCached:
        return [{"form": e["form"], "targets": e["targets"], "heard": [], "whisper": False, "verified": False,
                 "timing": TIMING_NONE, "start_s": None, "window_s": None, "missing": "transcription",
                 "note": "nincs tárolt Whisper-átirat (csak új, fizetős hívással számolható)"}
                for e, _, _ in found]
    tw = words_of(scene_text)
    ww, timing = timeline(transcript)
    t2w = _equal(tw, ww)
    out = []
    placed = place(tw, ww, t2w, found)
    for (entry, i0, i1), where in zip(found, placed):
        result = {"form": entry["form"], "targets": entry["targets"], "heard": [], "whisper": False,
                  "verified": False, "timing": TIMING_NONE, "start_s": None, "window_s": None}
        unplaced = _unplaced(result, timing, where, ww, total)
        if unplaced is not None:
            out.append(unplaced)
            continue
        s, e = where["window"]
        result["whisper"] = whisper_heard([w[3] for w in ww[s:e]], entry)
        if timing == TIMING_SEGMENT:
            out.append({**result, "timing": TIMING_SEGMENT, "note": NOTE_SEGMENT,
                        "window_s": [round(ww[s][1], 3), round(ww[e - 1][2], 3)]})
            continue
        result.update(timing=TIMING_WORD, start_s=round(ww[s][1], 3))
        first, end_ = where["between"]
        crowded = any(first <= j0 < end_ and j0 != i0 for _, j0, _ in found)
        others = frozenset(k for other in placed if other is not where and other["window"]
                           for k in range(*other["window"]))
        start, end, context = locate(scene_text, transcript, pcm, i0, i1, where["window"], others, crowded)
        clip = pcm[int(start * RATE) * 2:int(end * RATE) * 2]
        try:
            _blind_runs(paid, clip, context, entry["targets"], result["heard"])
        except NotCached:
            result["missing"] = "judge"
            result["note"] = ("a vak ellenőrzés tárolt válasza hiányzik ehhez a kivágáshoz "
                              "(csak új, fizetős hívással számolható)")
        result["verified"] = _heard_ok(result["heard"], entry["targets"]) and result["whisper"]
        out.append(result)
    return out


def reservation(scenes: list[tuple[str, int]], names: list[dict]) -> Decimal:
    """The most the name check of an episode can cost: one transcription per scene with a name,
    up to two blind runs per repeat and occurrence (`scenes`: (text, audio seconds))."""
    total = Decimal(0)
    for text, seconds in scenes:
        count = len(occurrences(text, names))
        if count:
            total += transcription_reserve(seconds) + count * REPEATS * 2 * JUDGE_RESERVE
    return total
