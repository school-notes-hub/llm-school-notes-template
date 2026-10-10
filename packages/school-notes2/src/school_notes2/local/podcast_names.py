"""The name part of `sn podcast`: the receipt's names in episode time (`timed`), how the terminal
says them (`names_lines`), and `--names-only [--fill-missing]` – the name check of a released
episode counted again with this tool (`recount`).

**`--names-only`**: from the podcast cache only – the scenes' speech by the receipt's request
hashes, the script whose digest is the receipt's `script_sha256` (`adas.json` or a kept
`adas-<n>.json` of the hand-over), the stored Whisper transcripts and blind answers; nothing is
sent or paid, only the receipt's `names` (and `names_version`) change, under the podcast lock.
A name whose call is missing from the cache keeps its earlier result (`heard`, `whisper`,
`verified`) in the v2 form (`kept`): with the stored transcript its place is the new
computation; without it `timing` is `none` and the 0.4.0 moment (the start of the cut, not the
name's own time) is only named in the note. When no name can be counted again nothing is written
(exit 2). A receipt changed by hand since the HEAD (not the tool's last write) is never
overwritten (exit 2); an incomplete receipt is a `Hiba:` line (exit 1).

**`--fill-missing`** (with `--names-only`, sn 0.4.2): first the same count from the cache; the
calls it misses are then sent through the paid path of the release (`speech.Paid`: cache first,
ledger, the monthly and school-year podcast budget for the reservation of every missing call –
shown on the terminal before anything is sent – and before each call), and the receipt is counted
again with them. Without the flag nothing is ever sent."""

import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

from ..images.budget import images_lock
from ..podcast import names, openrouter, script as scripts, speech
from ..podcast.ledger import Cache, Ledger
from ..schemas import validate
from ..state import safefs
from ..state.errors import Prerequisite
from ..wiki import podcast as wiki_podcast
from . import guard, keys, tool_writes
from .common import Refused

STOP = 2


def stop(out, title: str, lines: list[str]) -> int:
    out(title)
    for line in lines:
        out(f"  {line}")
    return STOP


def _client(settings, sleep) -> openrouter.Client:
    key = keys.load(settings.key_file).get("OPENROUTER_API_KEY")
    if not key:
        raise Prerequisite("OPENROUTER_API_KEY hiányzik az ops .env-ből", todo="tedd be a kulcsot a school-notes-ops/.env-be")
    return openrouter.Client(key, settings.timeout_s, sleep=sleep)


def timed(checked: list[dict], starts: list[float]) -> list[dict]:
    """The name results in the final episode's time: `at_s`/`at` (`m:ss`) only for a name with
    its own Whisper word time, `window_s`/`window` (`m:ss–m:ss`) for one known only to a segment
    or between two neighbour words – never a moment more exact than the transcript gives."""
    out = []
    for item in checked:
        item = dict(item)
        start = item.pop("start_s", None)
        item.pop("end_s", None)
        index = item.pop("scene_index")
        window = item.pop("window_s", None)
        at = None if start is None else round(starts[index] + start, 1)
        item.update(at_s=at, at=None if at is None else wiki_podcast.length(at))
        if window is not None:
            span = [round(starts[index] + window[0], 1), round(starts[index] + window[1], 1)]
            item.update(window_s=span, window=f"{wiki_podcast.length(span[0])}–{wiki_podcast.length(span[1])}")
        out.append(item)
    return out


def where(item: dict) -> str:
    """Where a name is heard, as the terminal says it (an old receipt has `at` only)."""
    timing = item.get("timing")
    if item.get("at"):
        return item["at"]
    if timing == names.TIMING_SEGMENT:
        return f"{item['window']} között (csak mondatszintű idő)"
    if timing == names.TIMING_GAP:
        return f"{item['window']} között (a Whisper itt nem írta le)"
    return "ismeretlen helyen"


def names_lines(out, record: dict) -> None:
    total = len(record["names"])
    open_ = [n for n in record["names"] if not n["verified"]]
    out(f"nevek: {total - len(open_)}/{total} gépileg igazolt")
    for item in open_:
        heard = ", ".join(h or "–" for h in item["heard"]) or "–"
        out(f"  nem igazolt: {item['form']} – {where(item)} ({item['scene']}; "
            f"hallott: {heard}; Whisper: {'igen' if item['whisper'] else 'nem'})")
        if item.get("note"):
            out(f"    {item['note']}")


def released_script(repo: Path, ep, record: dict) -> dict | None:
    """The script the episode was released from: `adas.json` or a kept `adas-<n>.json` of the
    hand-over whose digest is the receipt's `script_sha256` (in name order: the same one each time)."""
    files = safefs.listdir(repo, ep.folder) if safefs.is_dir(repo, ep.folder) else []
    candidates = sorted((n for n in files if n.startswith("adas") and n.endswith(".json")),
                        key=lambda n: (n != "adas.json", n))
    for name in candidates:
        try:
            script = json.loads(safefs.read_text(repo, f"{ep.folder}/{name}"))
        except (OSError, ValueError):
            continue
        if isinstance(script, dict) and scripts.digest(script) == record.get("script_sha256"):
            return script
    return None


KEPT = "nem számoltam újra"
PLACE = ("timing", "at_s", "at", "window_s", "window")
EARLIER = "; korábbi megjegyzés: "


def kept(old: dict, fresh: dict, kind: str) -> dict:
    """The earlier receipt entry of a name whose `kind` call is missing from the cache, in the v2
    form: its blind result and verdict as they were; its place the new computation when the
    transcript is there (`judge` missing), else `timing: none` with the earlier moment only in the
    note (a 0.4.0 `at` was the start of the cut). Repeated recounts give the same entry."""
    item = {k: v for k, v in old.items() if k not in PLACE and k != "note"}
    earlier = str(old.get("note") or "") or None
    if earlier and earlier.startswith(KEPT):           # kept before: its own earlier note only
        earlier = earlier.split(EARLIER, 1)[1] if EARLIER in earlier else None
    if kind == "judge":
        item.update({k: fresh[k] for k in PLACE if k in fresh})
        note = (f"{KEPT} a vak ellenőrzést (hiányzó tárolt válasz; új, fizetős hívás kellene: --fill-missing): "
                "a hallott alakok, a Whisper-jel és az ítélet a korábbi nyugtáé, a hely az új számításé")
    elif "timing" in old:
        item.update({k: old[k] for k in PLACE if k in old})
        note = str(old.get("note", ""))
        earlier = None
    else:
        item.update(timing=names.TIMING_NONE, at_s=None, at=None)
        note = (f"{KEPT} (hiányzó tárolt Whisper-átirat; új, fizetős hívás kellene: --fill-missing): a hallott "
                "alakok, a Whisper-jel és az ítélet a korábbi nyugtáé; a hely nem ismert"
                + (f" (a 0.4.0-s nyugta a kivágás kezdetét adta: {old['at']})" if old.get("at") else ""))
    if earlier:
        note += f"{EARLIER}{earlier}"
    return {**item, "note": note} if note else item


def _read(local, ep) -> tuple[dict, list[dict], dict | None, list[str]]:
    """The receipt, its scenes, the released script and the reasons to stop before anything."""
    repo = local.repo
    if not safefs.is_file(repo, ep.record):
        return {}, [], None, [f"nincs kiadott adás: {ep.record}"]
    if guard.hand_edited_file(repo, local.git(), ep.record):
        return {}, [], None, [f"{ep.record}: a nyugta nem az sn podcast utolsó írása (kézzel módosították a HEAD "
                              "óta) – nem írom felül; előbb állítsd vissza (git checkout)"]
    record = safefs.read_json(repo, ep.record)
    try:
        scenes = [{"id": s["id"], "request_sha256": s["request_sha256"], "audio_sha256": s["audio_sha256"],
                   "start_s": float(s["start_s"])} for s in record["speech"]["scenes"]]
        list(record["names"])
        if not isinstance(record["script_sha256"], str):
            raise TypeError("script_sha256")
    except (KeyError, TypeError, ValueError) as exc:
        raise Refused(f"{ep.record}: hiányos nyugta (hiányzik vagy hibás: {exc}); a nevek csak teljes "
                      "újrakiadással számolhatók újra") from None
    script = released_script(repo, ep, record)
    if script is None:
        return record, scenes, None, [
            f"a kiadott forgatókönyv (script_sha256 {record['script_sha256'][:12]}…) nincs meg a {ep.folder}/ "
            "adas*.json fájljai között; a nevek csak teljes újrakiadással számolhatók újra"]
    if [s["id"] for s in scenes] != [s["id"] for s in script["scenes"]]:
        return record, scenes, None, ["a nyugta jelenetei nem a forgatókönyv jelenetei"]
    return record, scenes, script, []


def _count(paid, script: dict, pcms: list[bytes], scenes: list[dict]) -> list[dict]:
    checked = []
    for index, (scene, pcm) in enumerate(zip(script["scenes"], pcms)):
        text = " ".join(t["text"] for t in scene["turns"])
        for item in names.check_scene(paid, text, pcm, script["names"]):
            checked.append({**item, "scene": scene["id"], "scene_index": index})
    return timed(checked, [s["start_s"] for s in scenes])


def fill_reservation(fresh: list[dict], script: dict, pcms: list[bytes]) -> Decimal:
    """The most the missing calls can cost: per scene without a transcript the transcription and
    every name's blind runs, per name without blind answers its blind runs (two per repeat)."""
    blind = names.REPEATS * 2 * names.JUDGE_RESERVE
    total = Decimal(0)
    for index, scene in enumerate(script["scenes"]):
        items = [f for f in fresh if f["scene"] == scene["id"]]
        if any(f.get("missing") == "transcription" for f in items):
            total += names.transcription_reserve(len(pcms[index]) / 2 / speech.RATE) + len(items) * blind
        else:
            total += sum(blind for f in items if f.get("missing") == "judge")
    return total


def _fill(local, ep, settings, cache, script, pcms, scenes, fresh, out, client, sleep):
    """`--fill-missing`: the missing calls through the paid path, then the count again."""
    kinds = [f["missing"] for f in fresh if f.get("missing")]
    need = fill_reservation(fresh, script, pcms)
    out(f"pótlás: {len(kinds)} névnél hiányzik tárolt válasz (Whisper-átirat: {kinds.count('transcription')}, "
        f"vak ellenőrzés: {kinds.count('judge')}); a foglalás felső becslése: {need} USD")
    ledger = Ledger(settings)
    client = client or _client(settings, sleep)
    ledger.backfill(client, rounds=1)
    ledger.check(need, f"az adás ({ep.ident}) hiányzó névellenőrzései")
    paid = speech.Paid(client, ledger, cache, ep.ident, log=local.steps)
    try:
        fresh = _count(paid, script, pcms, scenes)
    finally:
        ledger.backfill(client, sleep=sleep, only=paid.opened)
    for line in paid.warnings:
        out(f"figyelmeztetés: {line}")
    return fresh, sum((Ledger.cost(c) for c in paid.opened), Decimal(0)), len(paid.opened)


def recount(local, ep, out=print, *, fill: bool = False, client: openrouter.Client | None = None,
            sleep=time.sleep) -> int:
    """`--names-only [--fill-missing]` (module text)."""
    repo = local.repo
    record, scenes, script, problems = _read(local, ep)
    if problems:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", problems)
    settings = local.podcast_settings()
    cost, calls = Decimal(0), 0
    with images_lock(settings.lock_path, settings.lock_timeout_s, what="podcast"):
        cache = Cache(settings.cache_dir)
        pcms = [cache.audio(s["request_sha256"]) for s in scenes]
        lost = [s["id"] for s, pcm in zip(scenes, pcms)
                if pcm is None or hashlib.sha256(pcm).hexdigest() != s["audio_sha256"]]
        if lost:
            local.record("podcast", "stop", target=ep.ident)
            return stop(out, "STOP (nem írtam semmit):", [
                f"a jelenetek hangja nincs a gyorsítótárban ({', '.join(lost)}); a nevek csak teljes, fizetős "
                "újrakiadással számolhatók újra"])
        fresh = _count(names.CacheOnly(cache), script, pcms, scenes)
        if fill and any(f.get("missing") for f in fresh):
            fresh, cost, calls = _fill(local, ep, settings, cache, script, pcms, scenes, fresh, out, client, sleep)
        old = list(record["names"])
        missing = [i for i, item in enumerate(fresh) if item.get("missing")]
        if missing and len(missing) == len(fresh):
            local.record("podcast", "stop", target=ep.ident)
            return stop(out, "STOP (nem írtam semmit):", [
                f"egyik név sem számolható újra a gyorsítótárból ({len(missing)} név: hiányzó tárolt válasz); "
                "a nyugta marad, ahogy volt (a hiányzó hívások: --fill-missing, fizetős)"])
        if missing and [(n.get("form"), n.get("scene")) for n in old] != [(n["form"], n["scene"]) for n in fresh]:
            local.record("podcast", "stop", target=ep.ident)
            return stop(out, "STOP (nem írtam semmit):", [
                "a régi nyugta nevei nem párosíthatók az újraszámoltakkal, és van, ami nem számolható újra: "
                "a régi eredmény nem tartható meg név szerint"])
        merged = []
        for i, item in enumerate(fresh):
            kind = item.pop("missing", None)
            merged.append(item if kind is None else kept(old[i], item, kind))
        new = {**record, "names": merged, "names_version": names.RECEIPT_VERSION}
        validate("podcast-episode", new)
        changed = new != record
        try:
            if changed:
                safefs.write_text(repo, ep.record, wiki_podcast.dumps(new))
        finally:
            tool_writes.record(repo, files=[ep.record])
    out(f"nyugta: {ep.record} ({'frissítve' if changed else 'változatlan'}; csak a nevek)")
    names_lines(out, new)
    if missing:
        out(f"nem számoltam újra: {len(missing)} név (hiányzó tárolt válasz); ezeknél a korábbi eredmény maradt"
            + ("" if fill else "; a hiányzó hívások: --fill-missing (fizetős)"))
    out(f"költség: {cost} USD ({calls} új hívás)" if fill else "költség: 0 USD (csak a gyorsítótár; nem küldtem semmit)")
    unverified = [n for n in new["names"] if not n["verified"]]
    local.record("podcast", "names", target=ep.ident, names=len(new["names"]), unverified=len(unverified),
                 kept=len(missing), cost_usd=float(cost), calls=calls)
    return 0
