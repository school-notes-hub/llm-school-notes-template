"""Gemini speech in B mode (the approved 3rd sample, `minta3.py`): one call per scene, the
turns as a two-speaker `input` list `{text, voice, instructions}`, every turn's instruction the
shared tone sentence followed by the turn's own; the top-level voice is the host's. The answer
is raw PCM, 24 kHz, 16 bit, mono.

`Paid` runs every paid call of an episode the same way: cache first (the exact request), then
the budget check and the ledger entry, then the call, then the answer into the cache and only
then the ledger entry closed (an interruption between the two leaves a booked reservation and a
cached answer: no second payment). An answer with status 200 that is not what was asked (an
error body, no audio, no transcript, no choices) is never cached. A request whose earlier call
is `unknown` or still `sent` in the ledger may already have been paid: `warnings` names it."""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from ..log import Log
from ..state.errors import BadWork, NeedsOwner, Transient
from . import openrouter
from .ledger import Cache, Ledger, cache_sha, request_sha, speech_reserve
from .script import characters, host

MODEL = "google/gemini-3.8-flash-tts"
RATE = 24000


def payload(script: dict, scene: dict) -> dict:
    common = script["style"]
    voices = {name: s["voice"] for name, s in script["speakers"].items()}
    return {"model": MODEL, "voice": voices[host(script)], "response_format": "pcm", "instructions": common,
            "input": [{"text": t["text"], "voice": voices[t["speaker"]],
                       "instructions": f"{common} {t['style']}".strip()} for t in scene["turns"]]}


def scene_characters(scene: dict) -> int:
    return characters({"scenes": [scene]})


@dataclass
class Paid:
    client: openrouter.Client
    ledger: Ledger
    cache: Cache
    episode: str                      # `<subject>/<page>`, the ledger's episode field
    log: Log = field(default_factory=lambda: Log(None, console=False))
    opened: list = field(default_factory=list)       # this run's ledger entries
    warnings: list = field(default_factory=list)     # requests that may be paid a second time

    def _open(self, kind: str, sha: str, reserve: Decimal) -> dict:
        earlier = [c for c in self.ledger.value["calls"]
                   if c["request_sha256"] == sha and c["state"] in ("unknown", "sent")]
        if earlier:
            self.warnings.append(f"{kind}: ugyanez a kérés korábban {earlier[-1]['state']} állapotban maradt "
                                 f"({earlier[-1]['started_at']}); lehet, hogy most másodszor fizetünk érte")
        call = self.ledger.open(kind, self.episode, sha, reserve)
        self.opened.append(call)
        return call

    def cached_speech(self, request: dict) -> bytes | None:
        return self.cache.audio(request_sha(request))

    def speech(self, request: dict, characters_: int) -> bytes:
        sha = request_sha(request)
        found = self.cache.audio(sha)
        if found is not None:
            return found
        call = self._open("speech", sha, speech_reserve(characters_))
        answer = self._post(call, openrouter.SPEECH, request)
        kind = answer.headers.get("content-type", "")
        pcm = answer.body
        if not kind.startswith("audio") or len(pcm) < RATE or len(pcm) % 2:
            self.ledger.close(call, "failed")
            raise BadWork(f"a beszédmodell nem hangot adott vissza ({kind or 'típus nélkül'}, {len(pcm)} bájt)",
                          todo="futtasd újra; ha ismétlődik, nézd meg a modellt és a hangokat")
        gid = answer.headers.get("x-generation-id")
        seconds = round(len(pcm) / 2 / RATE, 3)
        self.cache.put_audio(sha, pcm, {"kind": "speech", "model": request["model"], "generation_id": gid,
                                        "seconds": seconds, "at": call["started_at"]})
        self.ledger.close(call, "ok", generation_id=gid, seconds=seconds)
        return pcm

    def json(self, kind: str, url: str, request: dict, reserve: Decimal, cache_key: dict | None = None,
             expect: str = "") -> dict:
        """A JSON call (transcription, blind check), its answer cached by `cache_key` (default:
        the request itself) when it holds `expect` and no `error`; `usage.cost` is booked."""
        sha = cache_sha(request, cache_key)
        found = self.cache.result(sha)
        if found is not None:
            return found
        call = self._open(kind, sha, reserve)
        try:
            answer = self._post(call, url, request).json()
        except NeedsOwner:
            self.ledger.close(call, "failed")               # not JSON: may be paid, the reservation stays
            raise
        answer = answer if isinstance(answer, dict) else {"error": "not an object"}
        cost = (answer.get("usage") or {}).get("cost")
        booked = {"cost_usd": float(cost), "cost_source": "openrouter usage.cost"} if cost is not None else {}
        if answer.get("error") or (expect and expect not in answer):
            self.ledger.close(call, "failed", generation_id=answer.get("id"), **booked)
            raise BadWork(f"OpenRouter: a válasz nem {expect or 'várt'} ({str(answer.get('error'))[:120]})",
                          todo="futtasd újra; a hibás válasz nem került a gyorsítótárba")
        value = {"kind": kind, "at": call["started_at"], "answer": answer}
        self.cache.put_result(sha, value)
        self.ledger.close(call, "ok", generation_id=answer.get("id"), **booked)
        return value

    def _post(self, call: dict, url: str, request: dict):
        started = time.monotonic()
        try:
            answer = self.client.post(url, request)
        except openrouter.Unknown:
            self.ledger.close(call, "unknown")             # the reservation stays booked
            self._line(call, "unknown", started)
            raise
        except (Transient, NeedsOwner) as exc:
            # a 429/5xx/4xx answer or no connection: nothing was produced, nothing is booked
            self.ledger.close(call, "failed", cost_usd=0.0, cost_source=f"nem teljesült: {exc.message[:80]}")
            self._line(call, "failed", started, error_class=exc.kind)
            raise
        self._line(call, "ok", started)
        return answer

    def _line(self, call: dict, outcome: str, started: float, **counts) -> None:
        self.log.event("podcast.call", outcome, target=call["kind"], duration_s=time.monotonic() - started,
                       **counts)
