import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat.adatok import read, write, steps
from hasznalat.kapu_h import gate
from hasznalat.lapok_h import contacts, review
import subprocess
import wave
from types import SimpleNamespace
from hasznalat.lanc import produce, finalize
from school_notes2.local import usage_video, tool_writes
from school_notes2.wiki import check, markers
from school_notes2.wiki.rights import rendered
from lanc import nyitozaro
from school_notes2.local.common import today
from PIL import ImageDraw
from hasznalat.kapu_kiadas import exceptions
from lanc.hangok import Valodi


from test_hasznalat import fixture, filled, measured


def test_stub_chain_finalization_and_release(tmp_path, monkeypatch):
    """The real sound stub, frame encoder, mux, final gate and publisher, with tiny synthetic cards."""

    repo = tmp_path / "repo"
    out = repo / ".school-notes/out/hasznalat" / today().replace("-", "")
    out.mkdir(parents=True)
    build = tmp_path / "build"
    (build / "site/proba/minta").mkdir(parents=True)
    s = filled()
    m = measured()
    # Enough silence and screen time for the real H4 gate.
    for step in steps(s):
        step["szunet"] = 2

    (out / "kepek").mkdir()
    pic = Image.new("RGB", (3840, 2160), "#b0d0e0")
    ImageDraw.Draw(pic).rectangle((60, 300, 360, 450), fill="black")
    pic.save(out / "kepek/1.png")
    write(out / "forgatokonyv-kitoltott.json", s)
    write(out / "szereplok.json", {})
    write(out / "dobozok.json", m)
    write(
        out / "felvetel-nyugta.json",
        {"images": {"kepek/1.png": "hash"}, "chromium": "fixture"},
    )
    # The complete current contract is intentionally not bypassed in production. This isolated
    # test uses a one-word surface contract and validates its HTML in the final gate.
    monkeypatch.setattr(
        "hasznalat.kapu_h.read",
        lambda path: {"szovegek": [{"html": True, "text": "Minta"}]},
    )
    write(
        build / "payload.json", {"pages": [{"route": "proba/minta", "html": "Minta"}]}
    )
    (build / "site/proba/minta/index.html").write_text("Minta")
    for v in m:
        v["assets"] = []
    write(out / "dobozok.json", m)
    write(out / "valasztas.json", {"build": str(build), "commit": "head"})
    contacts(out, s, m)
    key = review(out)
    write(out / "verdict.json", {"key": key, "verdict": "accept", "defects": []})
    write(out / "kapu.json", {"kep_zold": True})
    local = SimpleNamespace(
        name="fixture",
        repo=repo,
        git=lambda: SimpleNamespace(out=lambda *a, **kw: "head"),
        record=lambda *a, **kw: None,
    )
    monkeypatch.setenv("VIDEO_CSONK", "1")
    assert produce(local, out) == 0

    def cards(fo, media, *args):
        media.mkdir(exist_ok=True)
        card = media / "card.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=white:s=1920x1080:r=30:d=0.2",
                "-an",
                "-c:v",
                "libx264",
                "-threads",
                "4",
                "-pix_fmt",
                "yuv420p",
                str(card),
            ],
            check=True,
        )
        return {"nyito": card, "zaro": card, "nyito_s": 0.2, "zaro_s": 0.2}

    monkeypatch.setattr(nyitozaro, "kepek", cards)
    music = tmp_path / "music.wav"
    with wave.open(str(music), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(48000 * 2))
    monkeypatch.setattr(nyitozaro, "INTRO", music)
    monkeypatch.setattr(nyitozaro, "OUTRO", music)
    monkeypatch.setattr(nyitozaro, "NYITO_HALKUL_S", 0.1)
    monkeypatch.setattr(nyitozaro, "ZARO_HALKUL_S", 0.1)
    assert finalize(local, out) == 0
    assert read(out / "kapu.json")["zold"]
    assert (
        usage_video.run(local, out=lambda s: None) == 2
    )  # the stub cannot be published
    receipt = read(out / "nyugta.json")
    receipt["csonk"] = False
    write(out / "nyugta.json", receipt)
    (repo / "wiki").mkdir(exist_ok=True)
    (repo / "wiki/index.md").write_text(
        "# Jegyzetoldal\n" + markers.wrap("subjects", "") + markers.wrap("guide", "")
    )
    tool_writes.record(repo, parts=["wiki/index.md"])
    assert usage_video.run(local, out=lambda s: None) == 0
    assert not check.check_renders(repo)
    rights = rendered(repo)
    asset = f"wiki/assets/hasznalat/hasznalat-{out.name}.mp4"
    assert rights(asset)[0] == "authored"
    published = read(repo / "publication/public.json")
    assert (
        next(a for a in published["assets"] if a["path"] == asset)["rights"]
        == "authored"
    )
    assert check.check_animation(repo, "wiki/index.md", 1, asset) == []
    assert tool_writes.load(repo)["files"]["wiki/assets/hasznalat/render.json"]
    # Current accept alone cannot authorize changed output bytes.
    (out / "hasznalat.mp4").write_bytes(b"changed")
    assert usage_video.run(local, out=lambda s: None) == 2


def test_contract_drift_is_measured_on_the_selected_element():
    s = filled()
    steps(s)[0]["id"] = "5-06"
    m = measured()
    m[0]["id"] = "5-06"
    definition = {
        "szovegek": [],
        "interakciok": [
            {
                "lepes": "5-06",
                "szereplo": "roviden",
                "feltetel": "buborek",
                "ok": "csak link nélkül",
            }
        ],
    }
    args = {
        "payload": fixture(),
        "commit": "head",
        "expected_commit": "head",
        "preview": True,
        "contract": definition,
    }
    assert any(f["kod"] == "H10" for f in gate(s, m, **args)["leletek"])
    m[0]["roles"]["roviden"]["tooltip"] = True
    assert gate(s, m, **args)["kep_zold"]


def test_gate_exception_forbids_text_blank_and_surface_overrides():

    for code in ["H3", "H5", "H10"]:
        record = {"key": "current", "kivetelek": [{"kod": code, "indok": "indok"}]}
        with pytest.raises(ValueError):
            exceptions({"leletek": []}, record, "current")
    report = {
        "leletek": [{"kod": "H2", "lepes": "1-01", "szereplo": "minta"}],
        "nem_mert": [],
    }
    record = {
        "key": "current",
        "kivetelek": [
            {"kod": "H2", "lepes": "1-01", "szereplo": "minta", "indok": "ellenőrizve"}
        ],
    }
    assert exceptions(report, record, "current")["zold"]
    with pytest.raises(ValueError):
        exceptions(report, record, "stale")


def test_paid_provider_uses_the_selected_local_configuration(monkeypatch):

    settings = object()
    client = object()
    monkeypatch.setattr(
        "school_notes2.local.podcast_names._client",
        lambda actual, sleep: client if actual is settings else None,
    )
    monkeypatch.setattr(
        "school_notes2.local.common.load",
        lambda *args: pytest.fail("default config must not be read"),
    )
    provider = Valodi(
        "fixture", "hasznalat", local=SimpleNamespace(podcast_settings=lambda: settings)
    )
    assert provider.settings is settings and provider.client is client


def test_final_preflight_applies_the_owner_exception_before_the_red_gate_check(
    tmp_path, monkeypatch
):
    from hasznalat import vegleges

    monkeypatch.setattr(vegleges, "accepted", lambda out: True)
    monkeypatch.setattr(vegleges, "review_key", lambda out: "current")
    finding = {"kod": "H4", "lepes": "4-23", "szereplo": "elozo"}
    write(tmp_path / "kapu.json", {"leletek": [dict(finding)], "kep_zold": False, "nem_mert": []})
    write(tmp_path / "gyartas.json", {"files": {}})
    with pytest.raises(ValueError, match="piros gyártási kapu"):
        vegleges.final_preflight(tmp_path)
    record = {"key": "current", "kivetelek": [dict(finding, indok="a tulajdonos megnézte")]}
    write(tmp_path / "kapu-kivetel.json", record)
    vegleges.final_preflight(tmp_path)
    write(tmp_path / "kapu-kivetel.json", dict(record, key="stale"))
    with pytest.raises(ValueError, match="elavult"):
        vegleges.final_preflight(tmp_path)
    write(tmp_path / "kapu-kivetel.json", {"key": "current", "kivetelek": [dict(finding, indok=" ")]})
    with pytest.raises(ValueError):
        vegleges.final_preflight(tmp_path)
