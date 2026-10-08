"""The parts of `sn podcast`: the mix is the approved `kevero.sh`, the speech request is the B
mode of the 3rd sample, the wire's error classes, the name check, the guard, the page check, the
config, the public gate's view of the MP3."""

import json
import re
import subprocess
import urllib.error
from pathlib import Path

import pytest

from school_notes2.podcast import audio, names, openrouter, speech
from school_notes2.state import safefs
from tests.podcast.conftest import SCRIPT, TOPIC, needs_ffmpeg, release, tone

KEVERO = Path(__file__).with_name("kevero.sh")


def test_mix_graph_is_kevero_sh_to_the_parameter():
    text = KEVERO.read_text(encoding="utf-8")
    graph = re.search(r'-filter_complex "\\\n(.*?)" -map', text, re.S)[1]
    graph = graph.replace("\\\n", "")
    assert audio.MIX_GRAPH == graph
    assert "OS=$(python3 -c \"print(int((12+$D-6)*1000))\")" in text      # the offset as mix_graph computes it
    assert '-i "$M" -i "$V" -sseof -20 -i "$M"' in text


@needs_ffmpeg
def test_mix_offset_follows_the_voice_length(tmp_path):
    from tests.podcast.conftest import tone as make
    pcm = tmp_path / "v.pcm"
    pcm.write_bytes(make(3.0, 220))
    audio.normalized(pcm, tmp_path / "v.wav")
    assert "adelay=9000|9000[o]" in audio.mix_graph(tmp_path / "v.wav")      # (12 + 3 − 6) × 1000


@needs_ffmpeg
def test_episode_is_byte_identical_mono_64k_with_only_title_and_album(tmp_path, music):
    scenes = [tone(1.5, 300), tone(2.0, 330)]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one = audio.episode(scenes, music, tmp_path / "a", title="Cím – ő", album="Képben vagy?")
    two = audio.episode(scenes, music, tmp_path / "b", title="Cím – ő", album="Képben vagy?")
    assert one[0] == two[0]
    assert one[1] == [12.3, 12.3 + 1.5 + 0.6]
    assert one[2] == pytest.approx(0.3 + 1.5 + 0.6 + 2.0 + 1.0 + 26, abs=0.1)
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate", Path(__file__).parents[3] / "study-site" / "check-public.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    text, frames, v1 = gate.id3(one[0])
    assert frames == ["TIT2", "TALB"] and text == "Cím – ő\nKépben vagy?" and not v1
    assert b"Suno teszt" not in one[0]                                      # the music's own tags are dropped


def test_speech_request_is_b_mode():
    request = speech.payload(SCRIPT, SCRIPT["scenes"][0])
    assert request == {
        "model": "google/gemini-3.8-flash-tts", "voice": "Puck", "response_format": "pcm",
        "instructions": SCRIPT["style"],
        "input": [{"text": SCRIPT["scenes"][0]["turns"][0]["text"], "voice": "Laomedeia",
                   "instructions": SCRIPT["style"] + " Jelenet-felidézően kezd."},
                  {"text": "Dani vagyok, és ez tényleg érdekes.", "voice": "Puck",
                   "instructions": SCRIPT["style"] + " Élénk, kíváncsi."}]}
    last = speech.payload(SCRIPT, SCRIPT["scenes"][1])["input"][1]
    assert last["instructions"] == SCRIPT["style"]


class _Opener:
    def __init__(self, exc):
        self.exc = exc

    def open(self, request, timeout):
        raise self.exc


@pytest.mark.parametrize("raised, expected", [
    (urllib.error.URLError(ConnectionRefusedError()), ConnectionError),
    (urllib.error.URLError(TimeoutError()), TimeoutError),
    (ConnectionResetError(), TimeoutError),          # the answer was lost after sending
    (TimeoutError(), TimeoutError),
])
def test_wire_errors_are_classified(monkeypatch, raised, expected):
    monkeypatch.setattr(openrouter.urllib.request, "build_opener", lambda *a: _Opener(raised))
    with pytest.raises(expected):
        openrouter.urllib_transport("POST", openrouter.SPEECH, b"{}", {}, 5)


def test_connection_never_made_is_retried_then_transient():
    from school_notes2.state.errors import Transient
    calls = []

    def transport(*args):
        calls.append(args)
        raise ConnectionError("refused")
    client = openrouter.Client("k", 5, transport=transport, sleep=lambda s: None)
    with pytest.raises(Transient, match="nincs kapcsolat"):
        client.post(openrouter.SPEECH, {})
    assert len(calls) == 3


def test_name_occurrences_follow_the_form_and_text_order():
    found = names.occurrences("Ma Batthyány Lajos és Kossuth Lajos, majd Batthyány Lajosnak.", SCRIPT["names"])
    assert [(e["form"], i0, i1) for e, i0, i1 in found] == [("Batthyány Lajos", 1, 3), ("Kossuth Lajos", 4, 6)]
    assert names.compact("Battyányi  Lajos!") == "battyányilajos" and names.compact("Mihály") == "miháj"


def test_locate_cuts_between_matched_neighbours():
    text = "Ma Batthyány Lajos a téma volt."
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
             for i, w in enumerate("Ma battyányi lajos a téma volt".split())]
    pcm = tone(3.0, 220)
    start, end, context = names.locate(text, {"words": words}, pcm, 1, 3)
    assert 0 <= start <= 0.13 and 1.8 <= end <= 2.0      # one matched neighbour word stays on each side
    assert context == "Ma [NÉV] a"


def test_guard_catches_a_hand_written_mp3_and_receipt(world):
    from school_notes2.local import guard
    repo = world["repo"]
    safefs.write_bytes(repo, "wiki/assets/proba/podcast/kezi.mp3", b"ID3fake")
    safefs.write_json(repo, "docs/evidence/podcast/proba/kezi.json", {})
    found = guard.violations(repo, world["local"].git())
    assert "wiki/assets/proba/podcast/kezi.mp3: a podcast MP3 only `sn podcast` writes" in found
    assert any(f.startswith("docs/evidence/podcast/proba/kezi.json: a podcast receipt only") for f in found)


@needs_ffmpeg
def test_guard_and_page_check_after_a_hand_edit_of_the_released_episode(world):
    from school_notes2.local import guard
    from school_notes2.wiki import check
    assert release(world)[0] == 0
    repo = world["repo"]
    asset = "wiki/assets/proba/podcast/elso.mp3"
    safefs.write_bytes(repo, asset, safefs.read_bytes(repo, asset) + b"x")
    assert f"{asset}: a podcast MP3 only `sn podcast` writes" in guard.violations(repo, world["local"].git())
    errors = check.errors(check.check_files(repo, [TOPIC], fix=False))
    assert any("differs from the bytes its receipt names" in e["message"] for e in errors)
    safefs.unlink(repo, "docs/evidence/podcast/proba/elso.json")
    errors = check.errors(check.check_files(repo, [TOPIC], fix=False))
    assert any("needs its receipt" in e["message"] for e in errors)


@needs_ffmpeg
def test_done_reports_a_lost_player_block(world):
    from school_notes2.local import done
    from school_notes2.wiki import markers
    assert release(world)[0] == 0
    repo = world["repo"]
    safefs.write_text(repo, TOPIC, markers.remove(safefs.read_text(repo, TOPIC), {"podcast"}))
    found = dict(done.problems(repo))
    assert found["podcast-adás lejátszója eltűnt a lapjáról"] == [
        "wiki/proba/elso.md (wiki/assets/proba/podcast/elso.mp3)"]


@needs_ffmpeg
def test_close_keeps_the_podcast_page_and_public_entries(world):
    """`sn close` regenerates the Podcast page with the indexes (the topic page's current title)."""
    from school_notes2.wiki import generate, public
    assert release(world)[0] == 0
    repo = world["repo"]
    safefs.write_text(repo, TOPIC, safefs.read_text(repo, TOPIC).replace("title: Első", "title: Első rész"))
    assert "wiki/podcast.md" in generate.write_indexes(repo)
    assert "[Első rész](proba/elso.md)" in safefs.read_text(repo, "wiki/podcast.md")
    value = public.build(repo, public.render_rights(repo))
    assert any(a["path"].endswith("elso.mp3") and a["rights"] == "generated" for a in value["assets"])


def test_config_reads_the_podcast_section_and_limits():
    from school_notes2.config import ConfigError, parse
    base = {"git": {"name": "a", "email": "b"}, "students": {}}
    cfg = parse({**base, "podcast": {"music": "~/zene/outro.mp3"},
                 "limits": {"podcast_monthly_usd": 3, "podcast_year_total_usd": 20}})
    assert cfg.podcast.music == Path("~/zene/outro.mp3").expanduser()
    assert (cfg.limits.podcast_monthly_usd, cfg.limits.podcast_year_total_usd) == (3, 20)
    assert parse(base).podcast.music.name == "outro.mp3"
    with pytest.raises(ConfigError, match=r"\[podcast\] unknown keys: zene"):
        parse({**base, "podcast": {"zene": "x"}})
    with pytest.raises(ConfigError, match="podcast_monthly"):
        parse({**base, "limits": {"podcast_monthly": 1}})


def test_cli_parses_the_podcast_command():
    from school_notes2 import cli
    args = cli._parser().parse_args(["podcast", "barna", "proba", "elso", "--snapshot"])
    assert (args.command, args.learner, args.subject, args.page, args.snapshot) == \
        ("podcast", "barna", "proba", "elso", True)


@needs_ffmpeg
def test_ledger_books_every_call_and_the_speech_cost_from_openrouter(world):
    from school_notes2.podcast.ledger import Ledger
    assert release(world)[0] == 0
    calls = Ledger(world["local"].podcast_settings()).value["calls"]
    kinds = [c["kind"] for c in calls]
    assert kinds.count("speech") == 2 and kinds.count("transcription") == 2 and kinds.count("judge") == 6
    assert all(c["state"] == "ok" and c["cost_usd"] is not None and c["learner"] == "barna"
               and c["episode"] == "proba/elso" for c in calls)
    assert {c["cost_source"] for c in calls if c["kind"] == "speech"} == {"openrouter /generation"}


def test_backfill_waits_only_for_this_runs_calls(tmp_path):
    from decimal import Decimal
    from school_notes2.podcast.ledger import Ledger, PodcastSettings
    settings = PodcastSettings("a", tmp_path / "p", tmp_path / "l", tmp_path / "k", tmp_path / "m")
    ledger = Ledger(settings)
    old = ledger.open("speech", "x/y", "1" * 64, Decimal("0.1"))
    ledger.close(old, "ok", generation_id="never")
    new = ledger.open("speech", "x/y", "2" * 64, Decimal("0.1"))
    ledger.close(new, "ok", generation_id="soon")
    sleeps = []

    class Client:
        def generation_cost(self, gid):
            return 0.04 if gid == "soon" and sleeps else None
    assert ledger.backfill(Client(), sleep=sleeps.append, only=[new]) == 0
    assert sleeps == [15] and new["cost_usd"] == 0.04 and old["cost_usd"] is None
    assert ledger.spent_year() == Decimal("0.1") + Decimal("0.04")


def _levels(path):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                           "astats=measure_overall=Peak_level+RMS_level:measure_perchannel=none", "-f", "null", "-"],
                          capture_output=True, text=True, check=True)
    peak = float(re.findall(r"Peak level dB: (-?[\d.]+)", proc.stderr)[-1])
    rms = float(re.findall(r"RMS level dB: (-?[\d.]+)", proc.stderr)[-1])
    return peak, rms


@needs_ffmpeg
def test_mono_stays_under_the_limiter_ceiling_at_the_level_of_one_kevero_channel(tmp_path):
    """0.4.0 review H1: an `-ac 1` downmix after the graph was 3 dB louder than each channel and
    passed the limiter (peak +0.56 dBFS on the real track)."""
    loud = tmp_path / "loud.wav"                      # full-scale music: ×0.7 in the graph is −3.1 dBFS
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=30:sample_rate=48000",
                    "-af", "volume=7.99", "-ac", "2", "-c:a", "pcm_s16le", str(loud)], check=True)
    data, _, _ = audio.episode([tone(6.0, 220)], loud, tmp_path, title="x", album="y")
    (tmp_path / "mono.mp3").write_bytes(data)
    graph = audio.MIX_GRAPH.replace("$OS", str(int((12 + audio.duration(tmp_path / "voice.wav") - 6) * 1000)))
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(loud), "-i", str(tmp_path / "voice.wav"), "-sseof", "-20",
                    "-i", str(loud), "-filter_complex", graph, "-map", "[a]", "-c:a", "libmp3lame", "-b:a", "128k",
                    "-ac", "2", "-bitexact", str(tmp_path / "kevero.mp3")], check=True)     # kevero.sh exactly
    peak, rms = _levels(tmp_path / "mono.mp3")
    ref_peak, ref_rms = _levels(tmp_path / "kevero.mp3")
    assert peak < -1.0 and abs(peak - ref_peak) < 0.5
    assert abs(rms - ref_rms) < 0.15
    assert "alimiter=limit=0.89,pan=mono|c0=0.5*c0+0.5*c1[a]" in audio.mix_graph(tmp_path / "voice.wav")
