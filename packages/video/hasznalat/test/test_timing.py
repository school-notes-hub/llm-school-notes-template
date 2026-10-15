"""Production timing follows the resolved tour without changing its review inputs."""

import copy
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat.adatok import read, write, steps
from hasznalat.gyartas import sound
from hasznalat.osszerak import plan
from hasznalat.lapok_h import review_key
from test_hasznalat import filled, measured


@pytest.mark.parametrize("kind", ["scroll", "page", "typing", "cursor", "recorded"])
def test_sound_extends_silence_for_resolved_transitions(tmp_path, monkeypatch, kind):
    script, measurements = filled(), measured()
    first, second = steps(script)
    first["szunet"] = 0.6
    second["atmenet_s"] = 1.6
    required = 1.6
    if kind == "page":
        second["url"] = "/other/"
        measurements[1]["motion"] = [{"image": "kepek/1.png", "seconds": 2.4}]
        required = 2.7  # Recorded movement plus the nine-frame page fade.
    elif kind == "typing":
        second["allapot"] = [{"muvelet": "gepel", "text": "abcdefghij"}]
        required = 2.1
    elif kind == "cursor":
        first["kurzor"] = {"szereplo": "roviden", "kattint": True}
        required += 0.9
    elif kind == "recorded":
        measurements[1]["motion"] = [{"image": "kepek/1.png", "seconds": 2.4}]
        required = 2.4
    else:
        second["gorget"] = {"szereplo": "roviden"}
    original = copy.deepcopy(script)
    write(tmp_path / "forgatokonyv-kitoltott.json", script)
    write(tmp_path / "szereplok.json", {})
    write(tmp_path / "dobozok.json", measurements)
    write(tmp_path / "felvetel-nyugta.json", {"images": {}})
    key = review_key(tmp_path)
    monkeypatch.setenv("VIDEO_CSONK", "1")
    times, audio, stub = sound(SimpleNamespace(name="fixture"), tmp_path, script)
    raw = read(tmp_path / "hangido.json")
    assert raw["lepesek"][0]["szunet_minta"] >= round(required * raw["rate"])
    frames = plan(script, measurements, times)["kockak"]
    assert len(frames) == times["kocka_osszes"]
    start = times["lepesek"][1]["kezd_kocka"]
    speech_end = raw["lepesek"][0]["beszed_veg_s"] * 30
    moving = [i for i, f in enumerate(frames[:start]) if f.get("mozgas") or f.get("kurzor")]
    assert moving and min(moving) >= speech_end
    assert not frames[start]["mozgas"]
    assert times["lepesek"][1]["horgonyok"]["Minta"]["kocka"] >= start
    with wave.open(str(tmp_path / "hang.wav")) as wav:
        duration = wav.getnframes() / wav.getframerate()
    assert duration == pytest.approx(audio["hossz_s"])
    assert abs(duration - len(frames) / 30) <= 1 / 30
    assert script == original and review_key(tmp_path) == key and stub
    again = sound(SimpleNamespace(name="fixture"), tmp_path, script)[0]
    assert again == times  # No accumulating padding on a resumed production.


def test_sufficient_pause_and_final_pause_are_preserved():
    from hasznalat.idozites import timed_script

    script = filled()
    steps(script)[1]["atmenet_s"] = 0.6
    original = copy.deepcopy(script)
    assert timed_script(script, measured()) == original
    assert script == original
