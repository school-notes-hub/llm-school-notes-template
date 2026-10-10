"""The blind name check (the measured method of 2026-10-07, `kiejtes/biro/biro.py` and
`adas.py`): for every occurrence of a listed name in a scene, Whisper (`openai/whisper-large-v3`,
Hungarian, word times) transcribes the whole scene; the name is cut out at the quietest 10 ms
next to its neighbour words; the audio model (`google/gemini-3.8-flash`) writes down what it
hears **without** the target (blind), three times. A name is verified when all three blind
transcriptions equal a target and Whisper wrote the name where it stands (0/12 false accepts in
the measurement; a good clip passes 3 times in 5).

Since sn 0.4.1 (receipt `names_version` 2):

* **Whisper check per occurrence, by spelling too** (`whisper_heard`): Whisper writes a name
  mostly as it is spelled (`Kossuth`, `Széchenyi`), so its words at the name are compared with
  the form (accents aside) and the targets, a case ending or one letter more or less allowed;
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
  listed name stands between those neighbours: then the name's own Whisper words with the word
  next to them on each side (one name per clip).

A name that is not verified does not stop the episode: it goes into the receipt with the moment
it is heard in the final episode (or the span it lies in), for the owner, who listens to the
finished episode only. `CacheOnly` replays a released episode's check from the cache
(`sn podcast --names-only`)."""

import base64
import difflib
import io
import json
import math
import re
import sys
import unicodedata
import wave
from array import array
from decimal import Decimal

from . import openrouter
from .ledger import JUDGE_RESERVE, transcription_reserve
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


def norm_ph(text: str) -> str:
    text = unicodedata.normalize("NFC", (text or "").lower())
    text = re.sub(r"[^a-záéíóöőúüű ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: str) -> str:
    """The comparison form: no spaces, `ly` as `j` (the same sound)."""
    return norm_ph(text).replace(" ", "").replace("ly", "j")


def words_of(text: str) -> list[tuple[str, str]]:
    return [(w, norm_ph(w).replace(" ", "")) for w in text.split() if norm_ph(w)]


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


TIMING_WORD, TIMING_SEGMENT, TIMING_GAP, TIMING_NONE = "word", "segment", "gap", "none"
SIMILAR = 0.6          # the least similarity of a Whisper window to the name among other unmatched words


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
        from .ledger import request_sha
        found = self.cache.result(request_sha(cache_key if cache_key is not None else request))
        if found is None:
            self.missing.append(kind)
            raise NotCached(kind)
        return found


def timeline(transcript: dict) -> tuple[list[tuple[str, float, float, str]], str]:
    """Whisper's words as (normalised, start, end, as written) and how they are timed: `word`
    (word times), `segment` (the answer has segment times only – some OpenRouter providers give
    no word times: every word of a segment gets the segment's span) or `none`."""
    words = [(norm_ph(w.get("word", "")).replace(" ", ""), w["start"], w["end"], str(w.get("word", "")).strip())
             for w in transcript.get("words") or [] if "start" in w and "end" in w]
    if words:
        return words, TIMING_WORD
    words = [(norm_ph(w).replace(" ", ""), seg["start"], seg["end"], w)
             for seg in transcript.get("segments") or [] if "start" in seg and "end" in seg
             for w in str(seg.get("text") or "").split()]
    return (words, TIMING_SEGMENT) if words else ([], TIMING_NONE)


def _equal(tw: list, ww: list) -> dict[int, int]:
    """Text word index → Whisper word index for the words the two agree on."""
    matcher = difflib.SequenceMatcher(None, [n for _, n in tw], [w[0] for w in ww], autojunk=False)
    t2w = {}
    for tag, a0, a1, b0, _ in matcher.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                t2w[a0 + k] = b0 + k
    return t2w


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def _one_letter_more(a: str, b: str) -> bool:
    """`b` is `a` with one letter inserted, or the other way round (no letter changed)."""
    if abs(len(a) - len(b)) != 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def _written_as(got: str, wanted: str, fold: bool) -> bool:
    """`got` is `wanted` (accents aside when `fold`), maybe with a case ending (`kossuthot`);
    from 5 letters on also with one letter more or less (a spelling variant: Whisper's `Zeus` for
    `Zeusz`). A changed letter (`szícsényi`, `kusut`) is never accepted."""
    if not wanted:
        return False
    if got.startswith(wanted) or (fold and _fold(got).startswith(_fold(wanted))):
        return True
    return len(wanted) >= 5 and any(_one_letter_more(got[:n], wanted) for n in (len(wanted) - 1, len(wanted) + 1)
                                    if 0 < n <= len(got))


def whisper_heard(written: list[str], entry: dict) -> bool:
    """Did Whisper write this name where it stands? Whisper writes a name mostly as it is spelled
    (`Kossuth`, `Széchenyi`, `Zeus`), sometimes as it sounds (`Kölcsei`): the window's words are
    the form (accents aside) or a target (`_written_as`: a case ending or one letter more or less
    allowed). A different sound (`Szícsinyi` for Széchenyi) is not the name. Whisper is the second
    check only: the pronunciation itself is the blind check's."""
    got = compact(" ".join(written))
    return bool(got) and (_written_as(got, compact(entry["form"]), True)
                          or any(_written_as(got, compact(t), False) for t in entry["targets"]))


def _similarity(written: list[str], entry: dict) -> float:
    got = compact(" ".join(written))
    wanted = [compact(entry["form"]), *(compact(t) for t in entry["targets"])]
    return max(difflib.SequenceMatcher(None, _fold(got), _fold(w), autojunk=False).ratio() for w in wanted)


def place(tw: list, ww: list, t2w: dict, found: list[tuple[dict, int, int]]) -> list[dict]:
    """Where Whisper has each occurrence (in text order): `window` (first, end) of its own Whisper
    words, or None and `gap` (first, end) – the Whisper words between the agreeing neighbours.

    1. Every word of the name agrees with Whisper: those words.
    2. Between the agreeing neighbours the text has only the name: everything Whisper wrote
       there (`Szícsinyi István` for `Széchenyi István`).
    3. Other unmatched text words too: the shortest earliest window of at most the name's length
       + 2 words that Whisper wrote as the name (`whisper_heard`), else the most similar one if at
       least `SIMILAR` (ties: the earliest, then the shortest).

    A later occurrence is looked for only after the earlier one's window: two names never get
    the same Whisper words (and so the same moment)."""
    out, last = [], 0
    for entry, i0, i1 in found:
        prev = max((i for i in t2w if i < i0), default=None)
        nxt = min((i for i in t2w if i >= i1), default=None)
        lo = max(t2w[prev] + 1 if prev is not None else 0, last)
        hi = t2w[nxt] if nxt is not None else len(ww)
        window = None
        if all(i in t2w for i in range(i0, i1)):
            window = (t2w[i0], t2w[i1 - 1] + 1)
        elif lo < hi:
            first, end = prev + 1 if prev is not None else 0, nxt if nxt is not None else len(tw)
            others = [i for i in range(first, end) if not i0 <= i < i1]
            if not others:
                window = (lo, hi)
            else:
                size = (i1 - i0) + 2
                spans = [(s, e) for s in range(lo, hi) for e in range(s + 1, min(hi, s + size) + 1)]
                written = {(s, e): [w[3] for w in ww[s:e]] for s, e in spans}
                exact = [span for span in spans if whisper_heard(written[span], entry)]
                if exact:
                    window = min(exact, key=lambda span: (span[0], span[1]))
                elif spans:
                    best = min(spans, key=lambda span: (-_similarity(written[span], entry), span[0], span[1]))
                    if _similarity(written[best], entry) >= SIMILAR:
                        window = best
        if window is not None:
            last = window[1]
        out.append({"window": window, "gap": (lo, hi),
                    "between": (prev + 1 if prev is not None else 0, nxt if nxt is not None else len(tw))})
    return out


def locate(text: str, transcript: dict, pcm: bytes, i0: int, i1: int,
           window: tuple[int, int] | None = None) -> tuple[float, float, str]:
    """(start, end, context) of a name occurrence in the scene audio, the outer edges moved to the
    quietest frame nearby; the context is the text with [NÉV] for the name.

    Without `window` (the measured method): the text's words are aligned with Whisper's; the cut
    keeps one matching neighbour word on each side, the unmatched words between become context.
    With `window` (`place`: the name's own Whisper words; used when another listed name stands
    between the matching neighbours, so the cut would hold both): the cut keeps the Whisper word
    next to the window on each side (the text's word where Whisper agrees, else Whisper's)."""
    tw = words_of(text)
    ww, timing = timeline(transcript)
    total = len(pcm) / 2 / RATE
    if timing != TIMING_WORD:
        raise ValueError("nincs szó-szintű időbélyeg")
    t2w = _equal(tw, ww)
    if window is None:
        prev = max((i for i in t2w if i < i0), default=None)
        nxt = min((i for i in t2w if i >= i1), default=None)
        left, right = (t2w[prev] if prev is not None else None), (t2w[nxt] if nxt is not None else None)
        before = [w for w, _ in tw[(prev if prev is not None else 0):i0]]
        after = [w for w, _ in tw[i1:(nxt + 1 if nxt is not None else len(tw))]]
    else:
        s, e = window
        w2t = {w: t for t, w in t2w.items()}
        left, right = (s - 1 if s > 0 else None), (e if e < len(ww) else None)
        p, n = w2t.get(s - 1), w2t.get(e)
        before = ([w for w, _ in tw[:i0]] if left is None else
                  [w for w, _ in tw[p:i0]] if p is not None and p < i0 else [ww[left][3]])
        after = ([w for w, _ in tw[i1:]] if right is None else
                 [w for w, _ in tw[i1:n + 1]] if n is not None and n >= i1 else [ww[right][3]])
    if left is not None:
        t = ww[left][1]
        start = refine(pcm, t, max(0.0, t - 0.1), t + 0.03)
    else:
        start = 0.0
    if right is not None:
        t = ww[right][2]
        end = refine(pcm, t, t - 0.03, min(total, t + 0.1))
    else:
        end = total
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


def check_scene(paid, scene_text: str, pcm: bytes, names: list[dict]) -> list[dict]:
    """Every listed name in one scene, per occurrence: where it is heard (`timing`, `start_s`,
    `window_s`, scene-relative), whether Whisper wrote it there (`whisper`), the blind check's
    transcriptions (`heard`) and `verified` (all three blind transcriptions a target and Whisper
    wrote the name). The blind check runs only on a name with its own Whisper word times; without
    them (`segment`: the answer had segment times only, `gap`: Whisper wrote nothing like the name
    between its neighbours) the receipt says so in `note`. With `CacheOnly` a call that is not in
    the cache is not made: the receipt says what is missing."""
    found = occurrences(scene_text, names)
    if not found:
        return []
    total = len(pcm) / 2 / RATE
    try:
        transcript = transcribe(paid, pcm)
    except NotCached:
        return [{"form": e["form"], "targets": e["targets"], "heard": [], "whisper": False, "verified": False,
                 "timing": TIMING_NONE, "start_s": None, "window_s": None,
                 "note": "nincs tárolt Whisper-átirat (csak új, fizetős hívással számolható)"}
                for e, _, _ in found]
    tw = words_of(scene_text)
    ww, timing = timeline(transcript)
    t2w = _equal(tw, ww)
    out = []
    for (entry, i0, i1), where in zip(found, place(tw, ww, t2w, found)):
        result = {"form": entry["form"], "targets": entry["targets"], "heard": [], "whisper": False,
                  "verified": False, "timing": TIMING_NONE, "start_s": None, "window_s": None}
        window = where["window"]
        if timing == TIMING_NONE:
            out.append({**result, "note": "a Whisper-válaszban nincs időbélyeg: a hely ismeretlen, "
                                          "a vak ellenőrzés nem futott"})
            continue
        if window is None:
            out.append({**result, "timing": TIMING_GAP, "window_s": _span(ww, *where["gap"], total, timing),
                        "note": ("a Whisper itt nem írt a névhez hasonlót: csak a két szomszéd szó közötti "
                                 "szakasz ismert" if timing == TIMING_WORD else
                                 "a Whisper-válaszban csak mondatszintű idő van, és a név nincs meg a szavai "
                                 "között: csak a szomszéd mondatok szakasza ismert")
                                + ", a vak ellenőrzés nem futott"})
            continue
        s, e = window
        result["whisper"] = whisper_heard([w[3] for w in ww[s:e]], entry)
        if timing == TIMING_SEGMENT:
            out.append({**result, "timing": TIMING_SEGMENT,
                        "window_s": [round(ww[s][1], 3), round(ww[e - 1][2], 3)],
                        "note": "a Whisper-válaszban csak mondatszintű (szakasz-) idő van, szóidő nincs: "
                                "a név nem vágható ki, a vak ellenőrzés nem futott"})
            continue
        result.update(timing=TIMING_WORD, start_s=round(ww[s][1], 3))
        first, end_ = where["between"]
        crowded = any(first <= j0 < end_ and j0 != i0 for _, j0, _ in found)
        start, end, context = locate(scene_text, transcript, pcm, i0, i1, window if crowded else None)
        clip = pcm[int(start * RATE) * 2:int(end * RATE) * 2]
        try:
            for repeat in range(1, REPEATS + 1):
                heard = blind(paid, clip, context, repeat)
                if heard is None:                       # an unusable answer: one more run
                    heard = blind(paid, clip, context, repeat + 10)
                result["heard"].append(heard)
                if heard is None or not any(compact(heard) == compact(t) for t in entry["targets"]):
                    break
        except NotCached:
            result["note"] = ("a vak ellenőrzés tárolt válasza hiányzik ehhez a kivágáshoz "
                              "(csak új, fizetős hívással számolható)")
        blind_ok = len(result["heard"]) == REPEATS and all(
            h is not None and any(compact(h) == compact(t) for t in entry["targets"]) for h in result["heard"])
        result["verified"] = blind_ok and result["whisper"]
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
