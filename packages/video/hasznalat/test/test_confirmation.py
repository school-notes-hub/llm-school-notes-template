"""Confirmation-review regressions, using only neutral pages and images."""

import argparse
import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat import lanc, osszerak
from hasznalat.adatok import ROOT, read, steps
from hasznalat.jeloltek import candidates
from hasznalat.kitolt import validate, transition_seconds
from hasznalat.kapu_h import gate
from test_hasznalat import fixture, filled, measured, timing


def test_candidate_requires_non_banner_figure():
    payload = fixture()
    payload["pages"][-1]["usageFigures"] = []
    choices, rejected = candidates(payload)
    assert not choices
    assert any("nem fejléc img.study-figure" in x for x in rejected[0]["hiany"])
    payload["pages"][-1]["usageFigures"].append({"fits": True, "box": [0, 0, 500, 300]})
    assert len(candidates(payload)[0]) == 1
    script, measurements = filled(), measured()
    measurements[0]["roles"]["roviden"].update(
        count=0, visible=False, reason="Nincs nem fejléc ábra."
    )
    result = gate(
        script,
        measurements,
        preview=True,
        payload=fixture(),
        commit="head",
        expected_commit="head",
        contract={"szovegek": []},
    )
    assert any(
        f["kod"] == "H1" and f["uzenet"] == "Nincs nem fejléc ábra."
        for f in result["leletek"]
    )


def test_phone_base_keeps_complete_page_and_camera_zooms_composition(tmp_path):
    image = Image.new("RGB", (1170, 2532), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1169, 180), fill="blue")
    draw.rectangle((0, 181, 90, 2531), fill="red")
    image.save(tmp_path / "page.png")
    step, measurement = steps(filled())[0], measured()[0]
    step.update(nezet="telefon", kamera="elem")
    measurement["viewport"] = {"width": 390, "height": 844}
    measurement["roles"]["roviden"]["box"] = [20, 100, 180, 60]
    view = osszerak.crop(step, measurement)
    spec = {"image": "page.png", "crop": view, "nezet": "telefon"}
    base, transform = osszerak.base_frame(tmp_path, spec)
    assert base.getpixel((750, 80)) == (0, 0, 255)
    assert base.getpixel((735, 300)) == (255, 0, 0)
    assert 960 <= view[2] < 1920
    assert view[2] / view[3] == pytest.approx(16 / 9)
    picture = osszerak.frame(tmp_path, spec)
    x = round((750 - view[0]) * 1920 / view[2])
    y = round((80 - view[1]) * 1080 / view[3])
    assert picture.getpixel((x, y)) == (0, 0, 255)


def test_latest_selected_work_folder_is_used_on_later_days(tmp_path):
    folder = tmp_path / ".school-notes/out/hasznalat"
    for day in ["20200101", "20200103", "20200105"]:
        (folder / day).mkdir(parents=True)
    for day in ["20200101", "20200103"]:
        (folder / day / "valasztas.json").write_text("{}")
    args = argparse.Namespace(out=None, elonezet=None, jeloltek=None)
    local = argparse.Namespace(repo=tmp_path, name="fixture")
    assert lanc.output_folder(args, local) == folder / "20200103"
    args.out = tmp_path / "explicit"
    assert lanc.output_folder(args, local) == args.out


def test_recorded_actions_approach_then_expand_the_ring():
    script, measurements, times = filled(), measured(), timing()
    steps(script)[1]["atmenet_s"] = 0.9
    measurements[1]["motion"] = [
        {"image": "before.png", "seconds": 0.6, "cursor": [100, 150], "approach": True},
        {"image": "after.png", "seconds": 0.3, "cursor": [100, 150], "ring": True},
    ]
    frames = osszerak.plan(script, measurements, times)["kockak"][33:60]
    assert len({tuple(f["kurzor"]) for f in frames[:18]}) == 18
    assert frames[17]["kurzor"] == [100, 150]
    assert [f["gyuru"] for f in frames[18:]] == list(range(6, 31, 3))
    assert transition_seconds({"allapot": [{"muvelet": "nyit"}]}, None) == 0.9


def test_tap_without_anchor_is_rejected_by_schema():
    script = read(ROOT / "forgatokonyv.json")
    steps(script)[0]["allapot"] = [{"szereplo": "menugomb", "muvelet": "koppint"}]
    with pytest.raises(ValidationError):
        validate(script, read(ROOT / "szereplok.json"))
