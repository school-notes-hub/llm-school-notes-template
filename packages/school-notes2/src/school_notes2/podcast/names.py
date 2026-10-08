"""The blind name check (the measured method of 2026-10-07, `kiejtes/biro/biro.py` and
`adas.py`): for every occurrence of a listed name in a scene, Whisper (`openai/whisper-large-v3`,
Hungarian, word times) transcribes the whole scene; the name is cut out at the quietest 10 ms
next to its neighbour words; the audio model (`google/gemini-3.8-flash`) writes down what it
hears **without** the target (blind), three times. A name is verified when all three blind
transcriptions equal a target and the Whisper transcript contains one (0/12 false accepts in
the measurement; a good clip passes 3 times in 5).

A name that is not verified does not stop the episode: it goes into the receipt with the moment
it is heard in the final episode, for the owner, who listens to the finished episode only."""

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


def locate(text: str, transcript: dict, pcm: bytes, i0: int, i1: int) -> tuple[float, float, str]:
    """(start, end, context) of a name occurrence in the scene audio: the text's words are
    aligned with Whisper's; the cut keeps one matching neighbour word on each side, its outer
    edge moved to the quietest frame nearby. Unmatched words between become the context."""
    tw = words_of(text)
    ww = [(norm_ph(w.get("word", "")).replace(" ", ""), w["start"], w["end"])
          for w in transcript.get("words") or [] if "start" in w and "end" in w]
    total = len(pcm) / 2 / RATE
    if not ww:
        raise ValueError("no word times")
    matcher = difflib.SequenceMatcher(None, [n for _, n in tw], [n for n, _, _ in ww], autojunk=False)
    t2w = {}
    for tag, a0, a1, b0, _ in matcher.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                t2w[a0 + k] = b0 + k
    prev = max((i for i in t2w if i < i0), default=None)
    nxt = min((i for i in t2w if i >= i1), default=None)
    if prev is not None:
        t = ww[t2w[prev]][1]
        start = refine(pcm, t, max(0.0, t - 0.1), t + 0.03)
    else:
        start = 0.0
    if nxt is not None:
        t = ww[t2w[nxt]][2]
        end = refine(pcm, t, t - 0.03, min(total, t + 0.1))
    else:
        end = total
    before = [w for w, _ in tw[(prev if prev is not None else 0):i0]]
    after = [w for w, _ in tw[i1:(nxt + 1 if nxt is not None else len(tw))]]
    return round(start, 3), round(end, 3), " ".join(before + ["[NÉV]"] + after)


def transcribe(paid, pcm: bytes) -> dict:
    """Whisper on the whole scene, sent as MP3 (as in the measured run)."""
    from .audio import speech_mp3
    request = {"model": WHISPER, "temperature": 0, "response_format": "verbose_json", "language": "hu",
               "timestamp_granularities": ["word", "segment"],
               "input_audio": {"data": base64.b64encode(speech_mp3(pcm)).decode(), "format": "mp3"}}
    answer = paid.json("transcription", openrouter.TRANSCRIPTION, request,
                       transcription_reserve(len(pcm) / 2 / RATE), expect="text")["answer"]
    return {"text": (answer.get("text") or "").strip(), "words": answer.get("words") or []}


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


def check_scene(paid, scene_text: str, pcm: bytes, names: list[dict]) -> list[dict]:
    """Every listed name in one scene: the blind check's result per occurrence."""
    found = occurrences(scene_text, names)
    if not found:
        return []
    transcript = transcribe(paid, pcm)
    out = []
    for entry, i0, i1 in found:
        targets = entry["targets"]
        result = {"form": entry["form"], "targets": targets, "heard": [], "whisper": False,
                  "verified": False}
        try:
            start, end, context = locate(scene_text, transcript, pcm, i0, i1)
        except ValueError as exc:
            out.append({**result, "start_s": None, "note": f"nem kivágható: {exc}"})
            continue
        result.update(start_s=start, end_s=end)
        result["whisper"] = any(compact(t) in compact(transcript["text"]) for t in targets)
        clip = pcm[int(start * RATE) * 2:int(end * RATE) * 2]
        for repeat in range(1, REPEATS + 1):
            heard = blind(paid, clip, context, repeat)
            if heard is None:                       # an unusable answer: one more run
                heard = blind(paid, clip, context, repeat + 10)
            result["heard"].append(heard)
            if heard is None or not any(compact(heard) == compact(t) for t in targets):
                break
        blind_ok = len(result["heard"]) == REPEATS and all(
            h is not None and any(compact(h) == compact(t) for t in targets) for h in result["heard"])
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
