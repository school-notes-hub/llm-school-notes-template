"""`sn podcast <t> <subject> <page> [--snapshot | --retire | --names-only]`: one episode of the „Képben vagy?”
podcast about one topic page (`wiki/<subject>/<page>.md`), released on the page, on the Podcast
page and on Drive (owner, 2026-10-08).

**`--snapshot`** (before the reviewer): the script's checks (schema, one host, known speakers,
only the spoken form – no digit, Roman numeral, `%`, `§`, common abbreviation –, every listed
name in the text, nothing private in what goes public); a problem is a STOP (exit 2, nothing
written). Then `keys.json` in the hand-over: the review key of the script and the topic page as
they are now. A `verdict.json` given to other content (another key, or before any snapshot) is
moved aside to `verdict-<old key>.json`: an old accept never counts for a new version.

**Release** (no flag), in this order, stopping at the first failure:

0. **STOP** (exit 2, nothing paid, nothing written) on any snapshot check; without the
   reviewer's `accept` for exactly this key (no `verdict.json`, `reject`, an accept with an open
   `hiba`, a verdict `key` other than `keys.json`'s, no snapshot, or the script or the page
   changed since it); on a hand-edited machine part of the topic page or `wiki/podcast.md`
   (`guard.hand_edited`: recording this command's write would make it look the tool's);
1. the paid phase under `state/podcast.lock`: the budget must cover every call the episode still
   needs (cached calls cost nothing), then one speech call per scene (`speech.py`, B mode) and
   the blind name check (`names.py`); a 429 or 5xx answer and a missing connection are retried
   after 15 and 60 s, then the command stops (exit 1; a re-run reuses every finished call); a
   request whose earlier call was left `unknown` or `sent` gets a `figyelmeztetés:` line;
2. the mix (`audio.py`, `kevero.sh` to the parameter, the channels averaged after its limiter)
   into a 64 kbit/s mono MP3 with the show (album) and the episode title (title) as ID3 tags –
   the same calls give the same bytes;
3. the repo: the MP3 `wiki/assets/<subject>/podcast/<page>.mp3`, the receipt
   `docs/evidence/podcast/<subject>/<page>.json` (with every name the check did not verify and
   the moment it is heard), the topic page's `podcast` block, the Podcast page `wiki/podcast.md`,
   `publication/public.json`, the tool-writes record (a page only when it was the tool's before or
   every machine part it differs from the HEAD in is one this command wrote: `guard.tool_written`);
4. Drive: `Podcast/<Tantárgy> – <lapcím>.mp3` under the learner's Drive root, the same file on a
   re-release (`drive/upload.py`); a Drive failure is exit 1 after the repo part – run it again.

**`--retire`** (an episode whose topic page was renamed, deleted or must lose its episode; podcast
plan 10.6: an outdated episode never holds back the corrected notes): removes the `podcast` block
from every page whose block plays this episode, deletes the MP3 and the receipt (recorded as the
tool's deletion, so the writer guard accepts it), refreshes the Podcast page (removes it with the
last episode) and `public.json`. The Drive copy is never deleted: a line names it for the owner.
Nothing is paid; the hand-over stays.

**`--names-only`** (sn 0.4.1): a released episode's name check counted again with this tool from
the podcast cache only – the scenes' speech by the receipt's request hashes, the script whose
digest is the receipt's `script_sha256` (`adas.json` or a kept `adas-<n>.json` of the hand-over),
the stored Whisper transcripts and blind answers; nothing is sent or paid, only the receipt's
`names` (and `names_version`) change. A call missing from the cache is not made: the name's note
says so (a new blind check is due where the cut changed – another name between the neighbours).

The command does not commit; the controller commits and publishes (`sn publish`)."""

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
from ..wiki import markers, public
from ..wiki import podcast as wiki_podcast
from ..wiki.pages import links, resolve, sha256, wiki_pages
from . import guard, keys, tool_writes
from .common import Refused, today
from .figure_close import REVIEWER

STOP = 2
GRAPH = "kevero.sh (tulajdonosi jóváhagyás 2026-10-08), utána pan=mono (a két csatorna átlaga)"
ENCODING = "MP3, 64 kbit/s CBR, mono, 48 kHz; ID3v2.3: title, album"


def stop(out, title: str, lines: list[str]) -> int:
    out(title)
    for line in lines:
        out(f"  {line}")
    return STOP


def run(local, subject: str, page: str, take_snapshot: bool = False, out=print, *,
        client: openrouter.Client | None = None, sleep=time.sleep, retire_: bool = False,
        names_only: bool = False) -> int:
    try:
        ep = scripts.episode(subject, page)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    if take_snapshot:
        return snapshot(local, ep, out)
    if retire_:
        return retire(local, ep, out)
    if names_only:
        return recount(local, ep, out)
    return release(local, ep, out, client=client, sleep=sleep)


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
    out(f"pillanatkép: {ep.folder}/keys.json (kulcs: {key})")
    out(f"becsült hossz: ~{wiki_podcast.length(seconds)} beszéd + 0:26 zene "
        f"({scripts.characters(script)} karakter, {len(script['scenes'])} jelenet, {len(script['names'])} név)")
    local.record("podcast", "snapshot", target=ep.ident)
    return 0


def stops(local, ep) -> tuple[dict | None, list[str]]:
    """Step 0: the script, the accept bound to the content, hand-edited machine parts."""
    repo = local.repo
    script, problems = scripts.load(repo, ep)
    if script is not None and not problems:
        problems = scripts.verdict_problems(repo, ep, script)
    git, record = local.git(), tool_writes.load(repo)
    for rel in (ep.page, wiki_podcast.PAGE):
        parts = guard.hand_edited(repo, git, rel, record)
        if parts:
            problems.append(f"{rel}: kézzel írt gépi rész ({', '.join(parts)}) – az sn podcast nem írja felül és nem "
                            "rögzíti; előbb állítsd vissza (vagy egy megszakadt sn close után futtasd újra azt)")
    return script, problems


def release(local, ep, out, *, client=None, sleep=time.sleep) -> int:
    script, problems = stops(local, ep)
    if problems:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem költöttem, nem írtam semmit):", problems)
    settings = local.podcast_settings()
    audio.check_music(settings.music)
    client = client or _client(settings, sleep)
    requests = [speech.payload(script, scene) for scene in script["scenes"]]
    pcms, checked, cost, warnings = paid_phase(local, settings, client, ep, script, requests, sleep)
    for line in warnings:
        out(f"figyelmeztetés: {line}")
    with tempfile.TemporaryDirectory(prefix="sn-podcast-") as tmp:
        data, starts, seconds = audio.episode(pcms, settings.music, Path(tmp), title=script["title"],
                                              album=wiki_podcast.SHOW)
    record = build_record(local, ep, script, requests, data, seconds, pcms, starts, timed(checked, starts))
    write_repo(local, ep, record, data, out)
    summary(out, ep, record, data, cost)
    return drive(local, ep, record, data, cost, out)


def _client(settings, sleep) -> openrouter.Client:
    key = keys.load(settings.key_file).get("OPENROUTER_API_KEY")
    if not key:
        raise Prerequisite("OPENROUTER_API_KEY hiányzik az ops .env-ből", todo="tedd be a kulcsot a school-notes-ops/.env-be")
    return openrouter.Client(key, settings.timeout_s, sleep=sleep)


def paid_phase(local, settings, client, ep, script, requests, sleep) -> tuple[list[bytes], list[dict], Decimal, list]:
    """Speech per scene and the name check, under the podcast lock and budget."""
    with images_lock(settings.lock_path, settings.lock_timeout_s, what="podcast"):
        ledger, cache = Ledger(settings), Cache(settings.cache_dir)
        ledger.backfill(client, rounds=1)
        paid = speech.Paid(client, ledger, cache, ep.ident, log=local.steps)
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
    return pcms, checked, cost, paid.warnings


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


def build_record(local, ep, script: dict, requests: list[dict], data: bytes, seconds: float,
                 pcms: list[bytes], starts: list[float], checked: list[dict]) -> dict:
    """The release receipt; release days, tool and ffmpeg version kept while the MP3 is the same."""
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
    ffmpeg = old.get("mix", {}).get("ffmpeg") if same else None
    record = {
        "show": wiki_podcast.SHOW, "subject": ep.subject, "page": ep.page, "title": script["title"],
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
                "encoding": ENCODING, "ffmpeg": ffmpeg or audio.ffmpeg_version()},
        "names": checked, "names_version": names.RECEIPT_VERSION,
        "rights": wiki_podcast.RIGHTS,
        "drive": {"folder": drive_upload.PODCAST, "name": wiki_podcast.drive_names(wanted)[ep.ident]},
        "first_released": first, "released": old["released"] if same else day,
        "tool": old["tool"] if same and old.get("tool") else VERSION,
    }
    validate("podcast-episode", record)
    return record


def write_repo(local, ep, record: dict, data: bytes, out) -> None:
    repo, git = local.repo, local.git()
    before = _texts(repo, [ep.page, wiki_podcast.PAGE])
    try:
        if not safefs.is_file(repo, ep.asset) or sha256(repo, ep.asset) != record["output_sha256"]:
            safefs.write_bytes(repo, ep.asset, data)
        _write_if_changed(repo, ep.record, wiki_podcast.dumps(record))
        _write_if_changed(repo, ep.page, wiki_podcast.with_block(safefs.read_text(repo, ep.page), record))
        wiki_podcast.write_page(repo)
        _public(repo, out)
    finally:
        # also after an interruption: the guard knows the tool's own writes (a re-run finishes)
        tool_writes.record(repo, files=[ep.asset, ep.record])
        _record_pages(repo, git, before, out)


def _texts(repo: Path, rels: list[str]) -> dict[str, str | None]:
    return {rel: safefs.read_text(repo, rel) if safefs.is_file(repo, rel) else None for rel in rels}


def _record_pages(repo: Path, git, before: dict[str, str | None], out) -> None:
    """Record a written page only when it is the tool's: it was the tool's before, or every
    machine part it now differs from the HEAD in is one this command wrote."""
    record = tool_writes.load(repo)
    mine = []
    for rel, text in before.items():
        if not safefs.is_file(repo, rel) or safefs.read_text(repo, rel) == text:
            continue
        if text is None or guard.tool_written(repo, git, rel, text, record):
            mine.append(rel)
        else:
            out(f"figyelmeztetés: {rel}: az sn podcast írta, de egy gépi részét kézzel módosították – nem rögzítem; "
                "az sn done jelezni fogja")
    tool_writes.record(repo, parts=mine)


def _write_if_changed(repo: Path, rel: str, text: str) -> None:
    if not safefs.is_file(repo, rel) or safefs.read_text(repo, rel) != text:
        safefs.write_text(repo, rel, text)


def _public(repo: Path, out) -> None:
    try:
        public.write(repo, public.either(public.render_rights(repo), public.media_receipt_rights(repo),
                                         public.writer_svg_rights(repo)))
    except public.PublicError as exc:
        out(f"figyelmeztetés: a public.json nem frissült ({exc}); az sn close írja, a kiadás előtt kell")


def drive(local, ep, record: dict, data: bytes, cost: Decimal, out) -> int:
    try:
        result = drive_upload.upload(local.drive(), local.student.drive_root, ep.ident,
                                     record["drive"]["name"], data)
    except SnError as exc:
        out(f"Hiba: Drive: {exc}" + (f"\nTeendő: {exc.todo}" if exc.todo else ""))
        local.record("podcast", "drive-failed", target=ep.ident, error_class=exc.kind, cost_usd=float(cost))
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


def summary(out, ep, record: dict, data: bytes, cost: Decimal) -> None:
    out(f"adás: {ep.asset} ({len(data) / 1_000_000:.2f} MB, {wiki_podcast.length(record['duration_s'])})")
    out(f"nyugta: {ep.record}")
    out(f"lapok: {ep.page} (lejátszó), {wiki_podcast.PAGE}")
    names_lines(out, record)
    out(f"költség: {cost} USD (ez az adás, az eddigi hívásaival együtt)")


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


def recount(local, ep, out=print) -> int:
    """`--names-only`: the name check of a released episode counted again with this tool, from
    the cache only (the scenes' speech, the Whisper transcripts, the blind answers – nothing is
    sent, nothing is paid); only the receipt's `names` change. A call that is not in the cache is
    not made: the name's `note` says what is missing (a new, paid run would be a full release)."""
    repo = local.repo
    if not safefs.is_file(repo, ep.record):
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", [f"nincs kiadott adás: {ep.record}"])
    record = safefs.read_json(repo, ep.record)
    script = released_script(repo, ep, record)
    if script is None:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", [
            f"a kiadott forgatókönyv (script_sha256 {str(record.get('script_sha256'))[:12]}…) nincs meg a "
            f"{ep.folder}/ adas*.json fájljai között; a nevek csak teljes újrakiadással számolhatók újra"])
    scenes = record["speech"]["scenes"]
    if [s["id"] for s in scenes] != [s["id"] for s in script["scenes"]]:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", ["a nyugta jelenetei nem a forgatókönyv jelenetei"])
    cache = Cache(local.podcast_settings().cache_dir)
    pcms = [cache.audio(s["request_sha256"]) for s in scenes]
    lost = [s["id"] for s, pcm in zip(scenes, pcms)
            if pcm is None or hashlib.sha256(pcm).hexdigest() != s["audio_sha256"]]
    if lost:
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", [
            f"a jelenetek hangja nincs a gyorsítótárban ({', '.join(lost)}); a nevek csak teljes, fizetős "
            "újrakiadással számolhatók újra"])
    paid = names.CacheOnly(cache)
    checked = []
    for index, (scene, pcm) in enumerate(zip(script["scenes"], pcms)):
        text = " ".join(t["text"] for t in scene["turns"])
        for item in names.check_scene(paid, text, pcm, script["names"]):
            checked.append({**item, "scene": scene["id"], "scene_index": index})
    new = {**record, "names": timed(checked, [s["start_s"] for s in scenes]),
           "names_version": names.RECEIPT_VERSION}
    validate("podcast-episode", new)
    changed = new != record
    try:
        if changed:
            safefs.write_text(repo, ep.record, wiki_podcast.dumps(new))
    finally:
        tool_writes.record(repo, files=[ep.record])
    out(f"nyugta: {ep.record} ({'frissítve' if changed else 'változatlan'}; csak a nevek)")
    names_lines(out, new)
    if paid.missing:
        out(f"hiányzó tárolt válasz: {len(paid.missing)} (Whisper-átirat: {paid.missing.count('transcription')}, "
            f"vak ellenőrzés: {paid.missing.count('judge')}) – ezekhez új, fizetős hívás kellene; nem küldtem el")
    out("költség: 0 USD (csak a gyorsítótár; nem küldtem semmit)")
    unverified = [n for n in new["names"] if not n["verified"]]
    local.record("podcast", "names", target=ep.ident, names=len(new["names"]), unverified=len(unverified),
                 missing=len(paid.missing))
    return 0


def players(repo: Path, asset: str) -> list[str]:
    """Every wiki page whose `podcast` block plays `asset` (the topic page, also renamed)."""
    out = []
    for rel in wiki_pages(repo):
        body = markers.read(safefs.read_text(repo, rel), wiki_podcast.BLOCK)
        if body is not None and any(link.image and resolve(rel, link.target) == asset for link in links(body)):
            out.append(rel)
    return out


def retire(local, ep, out=print) -> int:
    """`--retire` (module text)."""
    repo, git = local.repo, local.git()
    if not safefs.is_file(repo, ep.record):
        local.record("podcast", "stop", target=ep.ident)
        return stop(out, "STOP (nem írtam semmit):", [f"nincs kiadott adás: {ep.record}"])
    record = safefs.read_json(repo, ep.record)
    pages = players(repo, ep.asset)
    before = _texts(repo, [*pages, wiki_podcast.PAGE])
    try:
        for rel in pages:
            safefs.write_text(repo, rel, markers.remove(safefs.read_text(repo, rel), {wiki_podcast.BLOCK}))
            out(f"lejátszó levéve: {rel}")
        safefs.unlink(repo, ep.asset)
        safefs.unlink(repo, ep.record)
        out(f"törölve: {ep.asset}, {ep.record}")
        if wiki_podcast.records(repo):
            wiki_podcast.write_page(repo)
        elif safefs.is_file(repo, wiki_podcast.PAGE):
            safefs.unlink(repo, wiki_podcast.PAGE)
            out(f"törölve: {wiki_podcast.PAGE} (nincs több adás; a menüpont eltűnik)")
        _public(repo, out)
    finally:
        tool_writes.record(repo, files=[ep.asset, ep.record])
        _record_pages(repo, git, before, out)
    out(f"Drive: a {drive_upload.PODCAST}/{record['drive']['name']} fájl megmarad (az sn a Drive-ról nem töröl; "
        "ha kell, a tulajdonos törli)")
    local.record("podcast", "retired", target=ep.ident, pages=len(pages))
    return 0
