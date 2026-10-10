"""The name check of sn 0.4.1 (receipt `names_version` 2), on the three faults of the 0.4.0
releases (2026-10-09):

1. almost every name „nem igazolt”: Whisper writes a name as it is spelled (`Kossuth`), 0.4.0
   looked for the pronunciation target (`kosut`) in the scene's text;
2. „ismeretlen helyen, hallott: –”: some OpenRouter providers answer with segment times only
   (`words: []`), 0.4.0 then had no place for any name;
3. names in one sentence got the same moment (the start of the cut, i.e. of the last word
   Whisper and the text agree on before them).

Plus `sn podcast --names-only`: the recount of a released episode from the cache, nothing paid."""

import base64
import io
import json
import wave

import pytest

from school_notes2.podcast import names, openrouter
from school_notes2.state import safefs
from tests.podcast.conftest import needs_ffmpeg, release, tone

SZ = {"form": "Széchenyi István", "targets": ["szécsényi istván"]}
KO = {"form": "Kossuth", "targets": ["kosut", "kosút"]}


class FakePaid:
    """`Paid.json` for `check_scene`: one Whisper answer, blind answers by context marker."""

    def __init__(self, transcript: dict, heard: dict):
        self.transcript, self.heard = transcript, heard
        self.blind = []                   # (context, clip seconds) of every blind call

    def json(self, kind, url, request, reserve, cache_key=None, expect=""):
        if kind == "transcription":
            return {"answer": self.transcript}
        prompt = request["messages"][0]["content"][0]["text"]
        context = prompt.split("szól: „", 1)[1].split("”", 1)[0]
        clip = base64.b64decode(request["messages"][0]["content"][1]["input_audio"]["data"])
        with wave.open(io.BytesIO(clip)) as w:
            self.blind.append((context, w.getnframes() / w.getframerate()))
        heard = next((value for marker, value in self.heard.items() if marker in context), "?")
        return {"answer": {"choices": [{"message": {"content": json.dumps({"hallott": heard})}}]}}


def timed_words(text: str, step: float = 0.5) -> list[dict]:
    return [{"word": w, "start": round(i * step, 3), "end": round((i + 1) * step, 3)}
            for i, w in enumerate(text.split())]


def test_whisper_spelling_verifies_a_good_name_and_a_wrong_sound_stays_open():
    text = "Ma Széchenyi István és Kossuth beszél, holnap Kossuthot hallgatjuk."
    good = FakePaid({"text": "", "words": timed_words("Ma Széchenyi István és Kossuth beszél, holnap")},
                    {"Ma [NÉV]": "szécsényi istván", "és [NÉV]": "kosút"})
    found = names.check_scene(good, text, tone(4.0, 220), [SZ, KO])
    assert [(r["form"], r["whisper"], r["verified"], r["heard"]) for r in found] == [
        ("Széchenyi István", True, True, ["szécsényi istván"] * 3),
        ("Kossuth", True, True, ["kosút"] * 3)]
    bad = FakePaid({"text": "", "words": timed_words("Ma Szícsinyi István és Kossuth beszél, holnap")},
                   {"Ma [NÉV]": "szícsényi istván", "és [NÉV]": "kosut"})
    found = names.check_scene(bad, text, tone(4.0, 220), [SZ, KO])
    assert [(r["form"], r["whisper"], r["verified"], r["heard"]) for r in found] == [
        ("Széchenyi István", False, False, ["szícsényi istván"]),
        ("Kossuth", True, True, ["kosut"] * 3)]


@pytest.mark.parametrize("written, expected", [
    (["Széchenyi", "István"], True), (["Szécsényi", "Istvánnak"], True), (["Szícsinyi", "István"], False),
    (["Szicsényi", "István"], False), (["Szécsinyi", "István"], False)])
def test_whisper_check_takes_the_spelling_a_case_ending_and_the_target_not_another_sound(written, expected):
    assert names.whisper_heard(written, SZ) is expected


def test_whisper_check_takes_a_one_letter_spelling_variant_but_no_changed_letter():
    assert names.whisper_heard(["Zeus"], {"form": "Zeusz", "targets": ["zeusz"]})
    assert names.whisper_heard(["Kossuth,"], KO) and names.whisper_heard(["Kosút"], KO)
    assert not names.whisper_heard(["Kusut"], KO)
    assert names.whisper_heard(["Beranger"], {"form": "Béranger", "targets": ["béranzsé"]})


CASES = [
    (["Kossuth", "Lajos", "és", "Petőfi"], KO, False),            # an ending only inside the last word
    (["Rémület"], {"form": "Ré", "targets": ["ré"]}, False),      # „mület” is no case ending
    (["Heraklész"], {"form": "Héra", "targets": ["héra"]}, False),
    (["Ionok"], {"form": "Ión", "targets": ["ión"]}, False),
    (["Zesz"], {"form": "Zeusz", "targets": ["zeusz"]}, False),   # a vowel is never the variant letter
    (["Zeuss"], {"form": "Zeusz", "targets": ["zeusz"]}, False),  # a changed letter neither
    (["Szécheny", "István"], SZ, False),
    (["Hérát"], {"form": "Héra", "targets": ["héra"]}, True),
    (["Zeuszt"], {"form": "Zeusz", "targets": ["zeusz"]}, True),
    (["Kosuth"], KO, True), (["Kossuthtal"], KO, True), (["Széchényi", "István"], SZ, True)]


def test_whisper_check_takes_a_case_ending_in_the_last_word_and_a_consonant_variant_only():
    assert [(w, names.whisper_heard(w, e)) for w, e, _ in CASES] == [(w, x) for w, _, x in CASES]


def test_segment_times_only_give_the_segment_span_and_no_blind_check():
    text = "Ma Széchenyi István és Kossuth beszél."
    paid = FakePaid({"text": "", "words": [], "segments": [
        {"start": 0.0, "end": 2.4, "text": " Ma Széchenyi István és"},
        {"start": 2.6, "end": 4.0, "text": " Kossuth beszél."}]}, {})
    found = names.check_scene(paid, text, tone(4.0, 220), [SZ, KO])
    assert [(r["timing"], r["start_s"], r["window_s"], r["whisper"], r["verified"]) for r in found] == [
        ("segment", None, [0.0, 2.4], True, False), ("segment", None, [2.6, 4.0], True, False)]
    assert paid.blind == [] and all("mondatszintű" in r["note"] for r in found)


LIST = [{"form": f, "targets": [t]} for f, t in
        (("Kölcsey", "kölcsei"), ("Vörösmarty", "vörösmarti"), ("Béranger", "béranzsé"), ("Heine", "hejne"))]
LIST_TEXT = "Kettő: a magyar előzmények Kölcsey, Vörösmarty, a világirodalmiak Béranger és Heine. Sziasztok!"


def test_names_in_one_sentence_get_their_own_moments_and_their_own_clips():
    words = timed_words("Kettő a magyar előzmények Kölcsei, Vörös Marti, a világirodalmiak Beranger és Hejne. "
                        "Sziasztok!", step=0.4)
    paid = FakePaid({"text": "", "words": words},
                    {"előzmények [NÉV]": "kölcsei", "[NÉV] a": "vörösmarti", "világirodalmiak [NÉV]": "béranzsé",
                     "és [NÉV]": "hejne"})
    found = names.check_scene(paid, LIST_TEXT, tone(6.0, 220), LIST)
    starts = {r["form"]: r["start_s"] for r in found}
    assert starts == {"Kölcsey": 1.6, "Vörösmarty": 2.0, "Béranger": 3.6, "Heine": 4.4}
    assert all(r["timing"] == "word" and r["verified"] for r in found)
    # one name per clip: the name's own words and one word on each side (≤ 4 words of 0.4 s)
    assert all(seconds <= 1.8 for _, seconds in paid.blind)
    assert all(context.count("[NÉV]") == 1 for context, _ in paid.blind)
    # side by side (review of 0.4.1, m2): no word of the other name is the neighbour in the clip
    clips = dict(paid.blind)
    assert list(clips)[:2] == ["előzmények [NÉV]", "[NÉV] a"]
    assert all("Kölcsei" not in c and "Vörös" not in c for c in clips)


def test_names_whisper_skipped_get_only_the_span_between_the_neighbours():
    words = timed_words("Kettő a magyar előzmények Sziasztok!", step=0.4)
    words[-1].update(start=30.0, end=30.6)            # Whisper skipped half a minute
    paid = FakePaid({"text": "", "words": words}, {})
    found = names.check_scene(paid, LIST_TEXT, tone(31.0, 220), LIST)
    assert [(r["timing"], r["start_s"], r["window_s"]) for r in found] == [("gap", None, [1.6, 30.0])] * 4
    assert paid.blind == [] and all("nem futott" in r["note"] for r in found)


@needs_ffmpeg
def test_release_receipt_verifies_names_whisper_wrote_as_spelled(world):
    world["router"].whisper_text = ("Sziasztok itt a Képben vagy Ma Batthyány Lajos a téma Dani vagyok és ez tényleg "
                                    "érdekes Kossuth Lajos pedig a pénzügyeket vitte Ez volt a Képben vagy Sziasztok")
    code, lines = release(world)
    assert code == 0, lines
    record = safefs.read_json(world["repo"], "docs/evidence/podcast/proba/elso.json")
    assert record["names_version"] == 2
    assert [(n["form"], n["whisper"], n["verified"], n["timing"]) for n in record["names"]] == [
        ("Batthyány Lajos", True, True, "word"), ("Kossuth Lajos", True, True, "word")]
    assert all(n["at"] and "window" not in n for n in record["names"])
    assert "nevek: 2/2 gépileg igazolt" in lines


@needs_ffmpeg
def test_release_with_segment_times_only_says_where_and_why(world):
    world["router"].whisper_segments_only = True
    code, lines = release(world)
    assert code == 0, lines
    record = safefs.read_json(world["repo"], "docs/evidence/podcast/proba/elso.json")
    for item in record["names"]:
        assert item["timing"] == "segment" and item["at"] is None and item["at_s"] is None
        assert item["window_s"][0] < item["window_s"][1] and "–" in item["window"]
    assert world["router"].count(openrouter.CHAT) == 0
    assert any(line.startswith("  nem igazolt: Batthyány Lajos – ") and "között (csak mondatszintű idő)" in line
               for line in lines)
    assert not any("ismeretlen helyen" in line for line in lines)


@needs_ffmpeg
def test_names_only_recounts_an_old_receipt_from_the_cache_and_pays_nothing(world):
    from school_notes2.local import guard, podcast
    from tests.local.conftest import git
    world["router"].whisper_text = ("Sziasztok itt a Képben vagy Ma Batthyány Lajos a téma Dani vagyok és ez tényleg "
                                    "érdekes Kossuth Lajos pedig a pénzügyeket vitte Ez volt a Képben vagy Sziasztok")
    assert release(world)[0] == 0
    repo, local = world["repo"], world["local"]
    rel = "docs/evidence/podcast/proba/elso.json"
    fresh = safefs.read_json(repo, rel)
    old = {k: v for k, v in fresh.items() if k != "names_version"}          # a 0.4.0 receipt
    old["names"] = [{"form": n["form"], "targets": n["targets"], "heard": n["heard"], "whisper": False,
                     "verified": False, "scene": n["scene"], "at": "0:13", "at_s": 13.0} for n in fresh["names"]]
    safefs.write_text(repo, rel, json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "0.4.0 receipt")
    # the hand-over moved on; the released script is kept as adas-1.json
    script = safefs.read_json(repo, ".school-notes/out/podcast/proba/elso/adas.json")
    safefs.write_json(repo, ".school-notes/out/podcast/proba/elso/adas-1.json", script)
    safefs.write_json(repo, ".school-notes/out/podcast/proba/elso/adas.json", {**script, "title": "Másik"})
    calls = len(world["router"].calls)
    lines = []
    assert podcast.run(local, "proba", "elso", False, out=lines.append, names_only=True) == 0
    assert len(world["router"].calls) == calls
    assert safefs.read_json(repo, rel) == fresh
    assert "nevek: 2/2 gépileg igazolt" in lines and "költség: 0 USD (csak a gyorsítótár; nem küldtem semmit)" in lines
    assert guard.violations(repo, local.git()) == []
    # the script of the release is gone: STOP, nothing written
    safefs.unlink(repo, ".school-notes/out/podcast/proba/elso/adas-1.json")
    lines = []
    assert podcast.run(local, "proba", "elso", False, out=lines.append, names_only=True) == 2
    assert any("nincs meg" in line for line in lines) and safefs.read_json(repo, rel) == fresh


def test_names_only_is_a_podcast_mode_of_its_own():
    from school_notes2 import cli
    args = cli._parser().parse_args(["podcast", "barna", "proba", "elso", "--names-only"])
    assert args.names_only and not args.snapshot and not args.retire
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["podcast", "barna", "proba", "elso", "--names-only", "--retire"])


SPELLED = ("Sziasztok itt a Képben vagy Ma Batthyány Lajos a téma Dani vagyok és ez tényleg "
           "érdekes Kossuth Lajos pedig a pénzügyeket vitte Ez volt a Képben vagy Sziasztok")
RECEIPT = "docs/evidence/podcast/proba/elso.json"


def released_040(world):
    """A released episode whose committed receipt has the 0.4.0 names; returns (fresh, old)."""
    from tests.local.conftest import git
    world["router"].whisper_text = SPELLED
    assert release(world)[0] == 0
    repo = world["repo"]
    fresh = safefs.read_json(repo, RECEIPT)
    old = {k: v for k, v in fresh.items() if k != "names_version"}
    old["names"] = [{"form": n["form"], "targets": n["targets"], "heard": ["régi"], "whisper": False,
                     "verified": False, "scene": n["scene"], "at": "0:13", "at_s": 13.0} for n in fresh["names"]]
    safefs.write_text(repo, RECEIPT, json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "0.4.0 receipt")
    return fresh, old


def scene_transcript(world, index):
    """The cache file of one scene's Whisper answer (by the request the run sent)."""
    from school_notes2.podcast import audio, ledger
    local = world["local"]
    record = safefs.read_json(world["repo"], RECEIPT)
    cache = ledger.Cache(local.podcast_settings().cache_dir)
    pcm = cache.audio(record["speech"]["scenes"][index]["request_sha256"])
    request = {"model": names.WHISPER, "temperature": 0, "response_format": "verbose_json", "language": "hu",
               "timestamp_granularities": ["word", "segment"],
               "input_audio": {"data": base64.b64encode(audio.speech_mp3(pcm)).decode(), "format": "mp3"}}
    return local.podcast_settings().cache_dir / f"{ledger.request_sha(request)}.json"


@needs_ffmpeg
def test_names_only_keeps_the_earlier_entry_where_the_cache_lacks_a_call(world):
    from school_notes2.local import podcast
    fresh, old = released_040(world)
    scene_transcript(world, 1).unlink()                     # J2's transcript (Kossuth Lajos) is gone
    lines = []
    assert podcast.run(world["local"], "proba", "elso", False, out=lines.append, names_only=True) == 0
    after = safefs.read_json(world["repo"], RECEIPT)
    batthyany, kossuth = after["names"]
    assert batthyany == fresh["names"][0]                   # counted again
    note = kossuth.pop("note")
    assert kossuth == old["names"][1] and note.startswith("nem számoltam újra (hiányzó tárolt Whisper-átirat")
    assert any(line.startswith("nem számoltam újra: 1 név") for line in lines)
    assert "missing" not in json.dumps(after)


@needs_ffmpeg
def test_names_only_with_nothing_in_the_cache_writes_nothing(world):
    from school_notes2.local import podcast
    _, old = released_040(world)
    before = safefs.read_bytes(world["repo"], RECEIPT)
    for index in (0, 1):
        scene_transcript(world, index).unlink()
    lines = []
    assert podcast.run(world["local"], "proba", "elso", False, out=lines.append, names_only=True) == 2
    assert safefs.read_bytes(world["repo"], RECEIPT) == before
    assert any("egyik név sem számolható újra" in line for line in lines)


@needs_ffmpeg
def test_names_only_never_overwrites_a_hand_edited_receipt_and_takes_the_podcast_lock(world, monkeypatch):
    import contextlib
    from school_notes2.local import podcast
    released_040(world)
    repo = world["repo"]
    hand = safefs.read_text(repo, RECEIPT).replace('"régi"', '"kézzel"')
    safefs.write_text(repo, RECEIPT, hand)
    lines = []
    assert podcast.run(world["local"], "proba", "elso", False, out=lines.append, names_only=True) == 2
    assert safefs.read_text(repo, RECEIPT) == hand and any("nem az sn podcast utolsó írása" in l for l in lines)
    from tests.local.conftest import git
    git(repo, "checkout", "--", RECEIPT)
    taken = []

    @contextlib.contextmanager
    def lock(path, timeout, what):
        taken.append(what)
        yield
    monkeypatch.setattr(podcast, "images_lock", lock)
    assert podcast.run(world["local"], "proba", "elso", False, out=lambda *_: None, names_only=True) == 0
    assert taken == ["podcast"]


@needs_ffmpeg
def test_names_only_on_an_incomplete_receipt_is_an_error_line_not_a_traceback(world):
    from school_notes2.local import podcast
    from school_notes2.state.errors import SnError
    from tests.local.conftest import git
    released_040(world)
    repo = world["repo"]
    broken = {k: v for k, v in safefs.read_json(repo, RECEIPT).items() if k != "speech"}
    safefs.write_text(repo, RECEIPT, json.dumps(broken, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    git(repo, "commit", "-qam", "broken receipt")
    with pytest.raises(SnError, match="hiányos nyugta"):
        podcast.run(world["local"], "proba", "elso", False, out=lambda *_: None, names_only=True)
