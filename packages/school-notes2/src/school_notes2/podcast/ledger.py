"""The podcast's own budget, ledger and cache (podcast plan 12: apart from the images).

* **Ledger** `state/podcast/<school-year>/ledger.json` – one entry per paid call (every learner
  in one file, as the image ledger): kind (`speech`, `transcription`, `judge`), learner,
  episode, the request's SHA-256, start time, state (`sent` → `ok`, `failed` or `unknown`),
  the reservation and – once known – the booked cost. A call without a booked cost counts with
  its reservation, so an interrupted or unknown call never makes the budget look larger.
* **Budget** (`[limits] podcast_monthly_usd`, `podcast_year_total_usd`): before an episode
  starts, the reservations of every call it still needs must fit into the Budapest calendar
  month and the school year; each call checks again before it is sent.
* **Cache** `state/podcast/cache/<request sha256>.{pcm,json}` – the answer of every finished
  call, by its exact request: a repeated `sn podcast` with the same script and the same audio
  pays nothing and gives the same bytes (the speech model itself is not deterministic).
* **Lock** `state/podcast.lock` – the paid phase of one episode at a time, for every learner.

Reservations (USD, deliberately high; measured 2026-10-08: speech 0.059 USD for 3 500
characters and 215 s, Whisper 0.0067 USD for 215 s, a blind name check at most 0.0021 USD):
speech `characters / 11 × 30 × 9e-6 × 1.25 + characters × 1e-6`, transcription
`seconds × 5e-5 + 0.001`, blind check 0.005."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..images.settings import budapest_today, school_year
from ..log import TZ, now_iso
from ..state.errors import NeedsOwner
from ..state.files import read_json, write_bytes, write_json

JUDGE_RESERVE = Decimal("0.005")


def speech_reserve(characters: int) -> Decimal:
    return Decimal(str(round(characters / 11 * 30 * 9e-6 * 1.25 + characters * 1e-6, 6)))


def transcription_reserve(seconds: float) -> Decimal:
    return Decimal(str(round(seconds * 5e-5 + 0.001, 6)))


def request_sha(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class BudgetExhausted(NeedsOwner):
    """The podcast budget does not cover what the episode still needs: the owner decides."""


@dataclass(frozen=True)
class PodcastSettings:
    learner: str
    state_root: Path                 # state/podcast/ (ledger per school year, cache)
    lock_path: Path                  # state/podcast.lock, shared by all learners
    key_file: Path                   # the ops `.env`
    music: Path                      # the owner's track
    monthly_usd: Decimal = Decimal("5")
    year_total_usd: Decimal = Decimal("40")
    timeout_s: int = 600
    lock_timeout_s: int = 600
    today: Callable[[], date] = field(default=budapest_today)

    @property
    def request_id(self) -> str:
        return school_year(self.today())

    @property
    def ledger_path(self) -> Path:
        return self.state_root / self.request_id / "ledger.json"

    @property
    def cache_dir(self) -> Path:
        return self.state_root / "cache"


class Ledger:
    def __init__(self, settings: PodcastSettings):
        self.settings = settings
        self.value = read_json(settings.ledger_path, None) or {"request_id": settings.request_id, "calls": []}

    def save(self) -> None:
        write_json(self.settings.ledger_path, self.value)

    @staticmethod
    def cost(call: dict) -> Decimal:
        value = call.get("cost_usd")
        return Decimal(str(value if value is not None else call.get("reserved_usd", "0")))

    def spent_month(self) -> Decimal:
        day = self.settings.today()

        def this_month(call: dict) -> bool:
            started = datetime.fromisoformat(call["started_at"]).astimezone(TZ).date()
            return (started.year, started.month) == (day.year, day.month)

        return sum((self.cost(c) for c in self.value["calls"] if this_month(c)), Decimal(0))

    def spent_year(self) -> Decimal:
        return sum((self.cost(c) for c in self.value["calls"]), Decimal(0))

    def check(self, reservation: Decimal, what: str) -> None:
        month, year = self.spent_month(), self.spent_year()
        if month + reservation > self.settings.monthly_usd:
            raise BudgetExhausted(
                f"a podcast havi kerete nem fedezi: {what} (foglalás {reservation} USD, a hónapban eddig "
                f"{month} USD, keret {self.settings.monthly_usd} USD)",
                todo="tulajdonosi döntés: [limits] podcast_monthly_usd, vagy a következő hónap")
        if year + reservation > self.settings.year_total_usd:
            raise BudgetExhausted(
                f"a podcast tanévi kerete nem fedezi: {what} (foglalás {reservation} USD, a tanévben eddig "
                f"{year} USD, keret {self.settings.year_total_usd} USD)",
                todo="tulajdonosi döntés: [limits] podcast_year_total_usd")

    def open(self, kind: str, episode: str, sha: str, reservation: Decimal) -> dict:
        """A paid call is about to be sent: checked against the budget, recorded first."""
        self.check(reservation, f"{kind} ({episode})")
        call = {"kind": kind, "learner": self.settings.learner, "episode": episode, "request_sha256": sha,
                "started_at": now_iso(), "state": "sent", "reserved_usd": float(reservation),
                "cost_usd": None}
        self.value["calls"].append(call)
        self.save()
        return call

    def close(self, call: dict, state: str, **fields) -> None:
        call.update(state=state, **fields)
        self.save()

    def unpriced(self, only: list[dict] | None = None) -> list[dict]:
        calls = self.value["calls"] if only is None else [c for c in self.value["calls"] if any(c is o for o in only)]
        return [c for c in calls if c.get("cost_usd") is None and c.get("generation_id") and c.get("state") == "ok"]

    def backfill(self, client, rounds: int = 4, pause: float = 15, sleep=None, only: list[dict] | None = None) -> int:
        """Booked costs from OpenRouter (a speech call's is known only some seconds later); with
        `only` just those calls (this run's), so an old call OpenRouter never prices does not make
        every run wait."""
        sleep = sleep or (lambda s: None)
        for n in range(rounds):
            todo = self.unpriced(only)
            if not todo:
                break
            if n:
                sleep(pause)
            for call in todo:
                cost = client.generation_cost(call["generation_id"])
                if cost is not None:
                    call.update(cost_usd=cost, cost_source="openrouter /generation")
            self.save()
        return len(self.unpriced(only))

    def episode_cost(self, episode: str, learner: str) -> Decimal:
        return sum((self.cost(c) for c in self.value["calls"]
                    if c["episode"] == episode and c["learner"] == learner), Decimal(0))


class Cache:
    """The answers of finished calls by request SHA-256 (private, never in a repo)."""

    def __init__(self, folder: Path):
        self.folder = folder

    def audio(self, sha: str) -> bytes | None:
        meta = read_json(self.folder / f"{sha}.json", None)
        path = self.folder / f"{sha}.pcm"
        if not meta or not path.is_file():
            return None
        data = path.read_bytes()
        return data if hashlib.sha256(data).hexdigest() == meta.get("audio_sha256") else None

    def put_audio(self, sha: str, data: bytes, meta: dict) -> None:
        write_bytes(self.folder / f"{sha}.pcm", data)
        write_json(self.folder / f"{sha}.json", {**meta, "audio_sha256": hashlib.sha256(data).hexdigest()})

    def result(self, sha: str) -> dict | None:
        return read_json(self.folder / f"{sha}.json", None)

    def put_result(self, sha: str, value: dict) -> None:
        write_json(self.folder / f"{sha}.json", value)
