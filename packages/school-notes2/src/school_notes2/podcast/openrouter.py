"""The paid podcast calls through OpenRouter, with the existing key (no new integration, owner
2026-10-07): Gemini speech (`/audio/speech`, B mode), Whisper transcription
(`/audio/transcriptions`) and the blind name transcription (`/chat/completions` with audio),
and the cost of a speech call afterwards (`/generation`).

The key is read from the ops `.env` at call time and goes only into the request header; it is
never logged or written. A 429, a 5xx answer or a connection that never reached the server is
retried after 15 and 60 s; then the command stops (`Transient`). A timeout after the request was
sent is `Unknown`: the call may have been paid, so it is not repeated in this run. Any other
4xx answer stops at once (`NeedsOwner`, with the start of the answer)."""

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from ..state.errors import NeedsOwner, Transient

API = "https://openrouter.ai/api/v1"
SPEECH = f"{API}/audio/speech"
TRANSCRIPTION = f"{API}/audio/transcriptions"
CHAT = f"{API}/chat/completions"
GENERATION = f"{API}/generation?id="
RETRY_DELAYS = (15, 60)
RETRYABLE = (429, 500, 502, 503, 504)


class Unknown(Transient):
    """The request was sent and the answer never came: its outcome (and cost) is unknown."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class Answer:
    status: int
    headers: dict
    body: bytes

    def json(self) -> dict:
        try:
            return json.loads(self.body)
        except ValueError:
            raise NeedsOwner("OpenRouter answered with something that is not JSON") from None


def urllib_transport(method: str, url: str, body: bytes | None, headers: dict, timeout: float) -> Answer:
    """Production wire: one HTTPS request, no redirect. Raises `urllib.error.HTTPError` for an
    error status, `ConnectionError` when nothing reached the server, `TimeoutError` after."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            return Answer(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read())
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        # urllib wraps what fails while connecting and sending; a timeout there may already
        # have sent the request
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError("timed out") from None
        raise ConnectionError(str(exc.reason)) from None
    except (OSError, http.client.HTTPException):
        # waiting for or reading the answer (a timeout, a dropped connection): the request
        # was sent, its outcome is unknown
        raise TimeoutError("answer lost") from None


@dataclass
class Client:
    key: str = field(repr=False)
    timeout_s: float = 600
    transport: Callable[..., Answer] = urllib_transport
    sleep: Callable[[float], None] = time.sleep
    retries: list = field(default_factory=list)      # (url, reason) of every retry, for the log

    def _headers(self, json_body: bool = True) -> dict:
        headers = {"Authorization": "Bearer " + self.key}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def post(self, url: str, payload: dict) -> Answer:
        body = json.dumps(payload, ensure_ascii=False).encode()
        for delay in (*RETRY_DELAYS, None):
            try:
                return self.transport("POST", url, body, self._headers(), self.timeout_s)
            except urllib.error.HTTPError as exc:
                text = _excerpt(exc)
                if exc.code in RETRYABLE and delay is not None:
                    self.retries.append((url, f"HTTP {exc.code}"))
                    self.sleep(delay)
                    continue
                if exc.code in RETRYABLE:
                    raise Transient(f"OpenRouter: HTTP {exc.code} {len(RETRY_DELAYS) + 1} próba után",
                                    todo="később futtasd újra ugyanazt a parancsot (a kész részek "
                                         "gyorsítótárból jönnek, nem költenek újra)") from None
                raise NeedsOwner(f"OpenRouter: HTTP {exc.code}: {text}",
                                 todo="nézd meg a kérést (modell, hang, keret)") from None
            except ConnectionError as exc:
                if delay is not None:
                    self.retries.append((url, "connection"))
                    self.sleep(delay)
                    continue
                raise Transient(f"OpenRouter: nincs kapcsolat ({exc})",
                                todo="a hálózat után futtasd újra ugyanazt a parancsot") from None
            except TimeoutError:
                raise Unknown("OpenRouter: a kérés elment, a válasz nem jött meg (időtúllépés); "
                              "a költség ismeretlen, a foglalás a keretben marad",
                              todo="futtasd újra később; a ledger a foglalással számol") from None
        raise AssertionError("unreachable")

    def generation_cost(self, generation_id: str) -> float | None:
        """The booked cost of a finished call, or None while OpenRouter does not know it yet."""
        try:
            answer = self.transport("GET", GENERATION + generation_id, None, self._headers(False),
                                    min(self.timeout_s, 30))
            cost = answer.json().get("data", {}).get("total_cost")
        except (urllib.error.HTTPError, ConnectionError, TimeoutError, NeedsOwner, AttributeError):
            return None
        return float(cost) if cost is not None else None


def _excerpt(exc: urllib.error.HTTPError) -> str:
    try:
        text = exc.read()[:300].decode("utf-8", "replace")
    except Exception:              # noqa: BLE001 - the body is only a hint
        text = ""
    finally:
        exc.close()
    return " ".join(text.split())
