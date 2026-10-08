"""Gemini speech in B mode (the approved 3rd sample, `minta3.py`): one call per scene, the
turns as a two-speaker `input` list `{text, voice, instructions}`, every turn's instruction the
shared tone sentence followed by the turn's own; the top-level voice is the host's. The answer
is raw PCM, 24 kHz, 16 bit, mono.

`Paid` runs every paid call of an episode the same way: cache first (the exact request), then
the budget check and the ledger entry, then the call, then the answer into the cache."""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from ..log import Log
from ..state.errors import BadWork, NeedsOwner, Transient
from . import openrouter
from .ledger import Cache, Ledger, request_sha, speech_reserve
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

    def cached_speech(self, request: dict) -> bytes | None:
        return self.cache.audio(request_sha(request))

    def speech(self, request: dict, characters_: int) -> bytes:
        sha = request_sha(request)
        found = self.cache.audio(sha)
        if found is not None:
            return found
        call = self.ledger.open("speech", self.episode, sha, speech_reserve(characters_))
        self.opened.append(call)
        answer = self._post(call, openrouter.SPEECH, request)
        kind = answer.headers.get("content-type", "")
        pcm = answer.body
        if not kind.startswith("audio") or len(pcm) < RATE or len(pcm) % 2:
            self.ledger.close(call, "failed")
            raise BadWork(f"a beszédmodell nem hangot adott vissza ({kind or 'típus nélkül'}, {len(pcm)} bájt)",
                          todo="futtasd újra; ha ismétlődik, nézd meg a modellt és a hangokat")
        gid = answer.headers.get("x-generation-id")
        seconds = round(len(pcm) / 2 / RATE, 3)
        self.ledger.close(call, "ok", generation_id=gid, seconds=seconds)
        self.cache.put_audio(sha, pcm, {"kind": "speech", "model": request["model"], "generation_id": gid,
                                        "seconds": seconds, "at": call["started_at"]})
        return pcm

    def json(self, kind: str, url: str, request: dict, reserve: Decimal, cache_key: dict | None = None) -> dict:
        """A JSON call (transcription, blind check), its answer cached by `cache_key` (default:
        the request itself); `usage.cost` is booked."""
        sha = request_sha(cache_key if cache_key is not None else request)
        found = self.cache.result(sha)
        if found is not None:
            return found
        call = self.ledger.open(kind, self.episode, sha, reserve)
        self.opened.append(call)
        answer = self._post(call, url, request).json()
        cost = (answer.get("usage") or {}).get("cost")
        self.ledger.close(call, "ok", generation_id=answer.get("id"),
                          **({"cost_usd": float(cost), "cost_source": "openrouter usage.cost"}
                             if cost is not None else {}))
        value = {"kind": kind, "at": call["started_at"], "answer": answer}
        self.cache.put_result(sha, value)
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
