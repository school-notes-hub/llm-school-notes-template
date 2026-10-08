"""`sn podcast <t> <subject> <page> [--snapshot]`: one episode of the „Képben vagy?” podcast
about one topic page (`wiki/<subject>/<page>.md`), released on the page, on the Podcast page
and on Drive (owner, 2026-10-08).

**`--snapshot`** (before the reviewer): the script's checks (schema, one host, known speakers,
only the spoken form – no digit, Roman numeral, `%`, `§`, common abbreviation –, every listed
name in the text, nothing private in what goes public); a problem is a STOP (exit 2, nothing
written). Then `keys.json` in the hand-over: the review key of the script and the topic page as
they are now. A `verdict.json` given to other content (another key, or before any snapshot) is
moved aside to `verdict-<old key>.json`: an old accept never counts for a new version.

**Release** (no flag), in this order, stopping at the first failure:

0. **STOP** (exit 2, nothing paid, nothing written) on any snapshot check, and without the
   reviewer's `accept` for exactly this key (no `verdict.json`, `reject`, an accept with an open
   `hiba`, no snapshot, or the script or the page changed since it);
1. the paid phase under `state/podcast.lock`: the budget must cover every call the episode still
   needs (cached calls cost nothing), then one speech call per scene (`speech.py`, B mode) and
   the blind name check (`names.py`); a 429 or 5xx answer and a missing connection are retried
   after 15 and 60 s, then the command stops (exit 1; a re-run reuses every finished call);
2. the mix (`audio.py`, `kevero.sh` to the parameter) into a 64 kbit/s mono MP3 with the show
   (album) and the episode title (title) as ID3 tags – the same calls give the same bytes;
3. the repo: the MP3 `wiki/assets/<subject>/podcast/<page>.mp3`, the receipt
   `docs/evidence/podcast/<subject>/<page>.json` (with every name the check did not verify and
   the moment it is heard), the topic page's `podcast` block, the Podcast page `wiki/podcast.md`,
   `publication/public.json`, the tool-writes record;
4. Drive: `Podcast/<Tantárgy> – <lapcím>.mp3` under the learner's Drive root, the same file on a
   re-release (`drive/upload.py`); a Drive failure is exit 1 after the repo part – run it again.

The command does not commit; the controller commits and publishes (`sn publish`). The hand-over
stays where it is: a re-run with the same script pays nothing and changes nothing."""

import hashlib
import json
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from .. import VERSION
from ..drive import upload as drive_upload
from ..images.budget import images_lock
from ..podcast import audio, names, openrouter, script as scripts, speech
from ..podcast.ledger import Cache, Ledger, request_sha, speech_reserve
from ..schemas import validate
from ..state import safefs
from ..state.errors import Prerequisite, SnError
from ..wiki import podcast as wiki_podcast
from ..wiki import public
from ..wiki.pages import sha256
from . import keys, tool_writes
from .common import today
from .figure_close import REVIEWER

STOP = 2
GRAPH = "kevero.sh (tulajdonosi jóváhagyás 2026-10-08)"
ENCODING = "MP3, 64 kbit/s CBR, mono, 48 kHz; ID3v2.3: title, album"


def stop(out, title: str, lines: list[str]) -> int:
    out(title)
    for line in lines:
        out(f"  {line}")
    return STOP


def snapshot(local, ep, out=print) -> int:
    script, problems = scripts.load(local.repo, ep)
    if problems:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP: a forgatókönyv nem mehet a lektorhoz (nem írtam semmit):", problems)
    key = scripts.review_key(local.repo, ep, script)
    old = scripts.read(local.repo, ep, "keys.json", {}) or {}
    if old.get("key") != key and safefs.is_file(local.repo, f"{ep.folder}/verdict.json"):
        # a verdict given to other content must not count for this one: kept aside, never deleted
        base = f"{ep.folder}/verdict-{str(old.get('key') or 'elotte')[:12]}"
        kept = next(f"{base}{'' if n == 1 else f'-{n}'}.json" for n in range(1, 1000)
                    if not safefs.exists(local.repo, f"{base}{'' if n == 1 else f'-{n}'}.json"))
        safefs.move(local.repo, f"{ep.folder}/verdict.json", kept)
        out(f"a korábbi ítélet félretéve (más változatra szólt): {kept}")
    safefs.write_text(local.repo, f"{ep.folder}/keys.json",
                      json.dumps({"key": key, "page": ep.page}, indent=1) + "\n")
    seconds = scripts.characters(script) / 16
    out(f"pillanatkép: {ep.folder}/keys.json")
    out(f"becsült hossz: ~{wiki_podcast.length(seconds)} beszéd + 0:26 zene "
        f"({scripts.characters(script)} karakter, {len(script['scenes'])} jelenet, {len(script['names'])} név)")
    local.record("podcast", "snapshot", target=ep.ident)
    return 0


def run(local, subject: str, page: str, take_snapshot: bool = False, out=print, *,
        client: openrouter.Client | None = None, sleep=time.sleep) -> int:
    try:
        ep = scripts.episode(subject, page)
    except ValueError as exc:
        from .common import Refused
        raise Refused(str(exc)) from None
    if take_snapshot:
        return snapshot(local, ep, out)
    repo = local.repo
    script, problems = scripts.load(repo, ep)
    if script is not None and not problems:
        problems = scripts.verdict_problems(repo, ep, script)
    if problems:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem költöttem, nem írtam semmit):", problems)
    settings = local.podcast_settings()
    audio.tools()
    if not settings.music.is_file():
        raise Prerequisite(f"a zene nincs meg: {settings.music}",
                           todo="[podcast] music a config.toml-ban, vagy a fájl a helyére")
    if client is None:
        key = keys.load(settings.key_file).get("OPENROUTER_API_KEY")
        if not key:
            raise Prerequisite("OPENROUTER_API_KEY hiányzik az ops .env-ből",
                               todo="tedd be a kulcsot a school-notes-ops/.env-be")
        client = openrouter.Client(key, settings.timeout_s, sleep=sleep)
    pcms, checked, cost = paid_phase(local, settings, client, ep, script, sleep)
    with tempfile.TemporaryDirectory(prefix="sn-podcast-") as tmp:
        data, starts, seconds = audio.episode(pcms, settings.music, Path(tmp), title=script["title"],
                                              album=scripts.SHOW)
        ffmpeg = audio.ffmpeg_version()
    for item in checked:
        start = item.pop("start_s", None)
        item.pop("end_s", None)
        at = None if start is None else round(starts[item["scene_index"]] + start, 1)
        item.pop("scene_index")
        item.update(at_s=at, at=None if at is None else wiki_podcast.length(at))
    record = write_repo(local, ep, script, data, seconds, pcms, starts, checked, ffmpeg, out)
    summary(out, ep, record, data, cost)
    try:
        result = drive_upload.upload(local.drive(), local.student.drive_root, ep.ident,
                                     record["drive"]["name"], data)
    except SnError as exc:
        out(f"Hiba: Drive: {exc}" + (f"\nTeendő: {exc.todo}" if exc.todo else ""))
        local.record("podcast", "drive-failed", target=ep.ident, error_class=exc.kind,
                     cost_usd=float(cost))
        return 1
    state = {"created": "új fájl", "updated": "frissítve", "unchanged": "változatlan"}[result["state"]]
    out(f"Drive: {drive_upload.PODCAST}/{result['name']} ({state}"
        + ("; a Podcast mappát most hoztam létre – a megosztás a tulajdonosé" if result["folder_created"] else "")
        + ")")
    if result["same_name"]:
        out(f"figyelmeztetés: a {drive_upload.PODCAST} mappában {result['same_name']} másik fájl is ezen a néven "
            "áll (nem az sn tette oda)")
    unverified = [n for n in record["names"] if not n["verified"]]
    local.record("podcast", "ok", target=ep.ident, cost_usd=float(cost), names=len(record["names"]),
                 unverified=len(unverified), seconds_audio=record["duration_s"], drive=result["state"])
    return 0


def paid_phase(local, settings, client, ep, script, sleep) -> tuple[list[bytes], list[dict], Decimal]:
    """Speech per scene and the name check, under the podcast lock and budget."""
    with images_lock(settings.lock_path, settings.lock_timeout_s):
        ledger, cache = Ledger(settings), Cache(settings.cache_dir)
        ledger.backfill(client, rounds=1)
        paid = speech.Paid(client, ledger, cache, ep.ident, log=local.steps)
        requests = [speech.payload(script, scene) for scene in script["scenes"]]
        texts = [" ".join(t["text"] for t in scene["turns"]) for scene in script["scenes"]]
        need, seconds = Decimal(0), []
        for scene, request in zip(script["scenes"], requests):
            found = paid.cached_speech(request)
            chars = speech.scene_characters(scene)
            if found is None:
                need += speech_reserve(chars)
            seconds.append(len(found) / 2 / speech.RATE if found is not None else chars / 11)
        need += names.reservation(list(zip(texts, seconds)), script["names"])
        ledger.check(need, f"az adás ({ep.ident}) még hátralévő hívásai")
        pcms = [paid.speech(request, speech.scene_characters(scene))
                for scene, request in zip(script["scenes"], requests)]
        checked = []
        for index, (scene, text, pcm) in enumerate(zip(script["scenes"], texts, pcms)):
            for item in names.check_scene(paid, text, pcm, script["names"]):
                checked.append({**item, "scene": scene["id"], "scene_index": index})
        ledger.backfill(client, sleep=sleep, only=paid.opened)
        cost = ledger.episode_cost(ep.ident, settings.learner)
    return pcms, checked, cost


def write_repo(local, ep, script: dict, data: bytes, seconds: float, pcms: list[bytes], starts: list[float],
               checked: list[dict], ffmpeg: str, out) -> dict:
    repo = local.repo
    sha = hashlib.sha256(data).hexdigest()
    old = safefs.read_json(repo, ep.record, None) if safefs.is_file(repo, ep.record) else None
    same = bool(old) and old.get("output_sha256") == sha
    day = today()
    first = old["first_released"] if old else day
    wanted = {r["subject"] + "/" + r["page"].rsplit("/", 1)[1][:-3]:
              (wiki_podcast.subject_name(repo, r["subject"]), wiki_podcast.page_title(repo, r["page"]),
               r["first_released"]) for r in wiki_podcast.records(repo)}
    wanted[ep.ident] = (wiki_podcast.subject_name(repo, ep.subject), wiki_podcast.page_title(repo, ep.page), first)
    requests = [speech.payload(script, scene) for scene in script["scenes"]]
    record = {
        "show": scripts.SHOW, "subject": ep.subject, "page": ep.page, "title": script["title"],
        "summary": script["summary"],
        "speakers": [{"name": n, "role": s["role"], "voice": s["voice"]} for n, s in script["speakers"].items()],
        "asset": ep.asset, "output_sha256": sha, "bytes": len(data), "duration_s": seconds,
        "key": scripts.review_key(repo, ep, script), "script_sha256": scripts.digest(script),
        "reviewer": REVIEWER, "verdict": scripts.verdict(repo, ep),
        "speech": {"model": speech.MODEL, "route": "openrouter /audio/speech (B mód: jelenetenként egy hívás)",
                   "scenes": [{"id": scene["id"], "request_sha256": request_sha(req),
                               "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                               "seconds": round(len(pcm) / 2 / speech.RATE, 3), "start_s": start}
                              for scene, req, pcm, start in zip(script["scenes"], requests, pcms, starts)]},
        "mix": {"music_sha256": hashlib.sha256(local.podcast_settings().music.read_bytes()).hexdigest(),
                "graph": GRAPH, "graph_sha256": hashlib.sha256(audio.MIX_GRAPH.encode()).hexdigest(),
                "encoding": ENCODING, "ffmpeg": ffmpeg},
        "names": checked,
        "rights": wiki_podcast.RIGHTS,
        "drive": {"folder": drive_upload.PODCAST, "name": wiki_podcast.drive_names(wanted)[ep.ident]},
        "first_released": first, "released": old["released"] if same else day,
        "tool": old["tool"] if same and old.get("tool") else VERSION,
    }
    if same:
        record["mix"]["ffmpeg"] = old.get("mix", {}).get("ffmpeg", ffmpeg)
    validate("podcast-episode", record)
    try:
        if not safefs.is_file(repo, ep.asset) or sha256(repo, ep.asset) != sha:
            safefs.write_bytes(repo, ep.asset, data)
        text = wiki_podcast.dumps(record)
        if not safefs.is_file(repo, ep.record) or safefs.read_text(repo, ep.record) != text:
            safefs.write_text(repo, ep.record, text)
        page = safefs.read_text(repo, ep.page)
        new = wiki_podcast.with_block(page, record)
        if new != page:
            safefs.write_text(repo, ep.page, new)
        wiki_podcast.write_page(repo)
        try:
            public.write(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                             public.writer_svg_rights(repo)))
        except public.PublicError as exc:
            out(f"figyelmeztetés: a public.json nem frissült ({exc}); az sn close írja, a kiadás előtt kell")
    finally:
        # also after an interruption: the writer guard knows the tool's own writes (a re-run finishes)
        tool_writes.record(repo, parts=[ep.page, wiki_podcast.PAGE], files=[ep.asset, ep.record])
    return record


def summary(out, ep, record: dict, data: bytes, cost: Decimal) -> None:
    out(f"adás: {ep.asset} ({len(data) / 1_000_000:.2f} MB, {wiki_podcast.length(record['duration_s'])})")
    out(f"nyugta: {ep.record}")
    out(f"lapok: {ep.page} (lejátszó), {wiki_podcast.PAGE}")
    total = len(record["names"])
    open_ = [n for n in record["names"] if not n["verified"]]
    out(f"nevek: {total - len(open_)}/{total} gépileg igazolt")
    for item in open_:
        heard = ", ".join(h or "–" for h in item["heard"]) or "–"
        out(f"  nem igazolt: {item['form']} – {item['at'] or 'ismeretlen helyen'} ({item['scene']}; "
            f"hallott: {heard}; Whisper: {'igen' if item['whisper'] else 'nem'})")
    out(f"költség: {cost} USD (ez az adás, az eddigi hívásaival együtt)")
