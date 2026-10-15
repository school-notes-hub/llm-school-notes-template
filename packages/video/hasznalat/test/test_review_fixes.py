"""Regressions for the independent review: no real video or paid provider needed."""

import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from PIL import Image, ImageDraw
from school_notes2.local import usage_video

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat import lanc
from hasznalat.adatok import ROOT, read, steps
from hasznalat.kapu_h import gate
from hasznalat.kitolt import contract, fill, validate
from hasznalat.osszerak import crop, frame, plan
from hasznalat import lapok_h
from test_hasznalat import simple, fixture, filled, measured, timing
from hasznalat.jeloltek import candidates


def checked(script, measurements, frames=None, times=None, definition=None):
    return gate(
        script,
        measurements,
        frames,
        times,
        payload=fixture(),
        commit="head",
        expected_commit="head",
        preview=True,
        contract=definition or {"szovegek": []},
    )


def test_typing_and_clicks_reserve_time_before_the_sentence():
    script = simple()
    script["jelenetek"][0]["lepesek"][1]["allapot"] = [
        {"szereplo": "input", "muvelet": "nyit"},
        {"szereplo": "input", "muvelet": "gepel", "text": "abcdefghij"},
    ]
    result, _ = fill(script, candidates(fixture())[0][0])
    first, second = steps(result)
    assert second["atmenet_s"] >= 2.1
    assert first["szunet"] >= second["atmenet_s"]


def test_recorded_action_frames_and_tap_ring_reach_the_plan():
    script, measurements, times = filled(), measured(), timing()
    steps(script)[1]["atmenet_s"] = 0.6
    measurements[1]["motion"] = [
        {"image": "before.png", "seconds": 0.3, "cursor": [50, 100]},
        {"image": "after.png", "seconds": 0.3, "cursor": [50, 100], "ring": True},
    ]
    measurements[1]["frames"] = ["before.png", "after.png"]
    steps(script)[0]["kurzor"] = {
        "szereplo": "roviden",
        "horgony": "Minta",
        "kattint": False,
    }
    measurements[0]["anchor_cursor"] = [40, 110]
    frames = plan(script, measurements, times)
    assert frames["kockak"][3]["kurzor"] == [40, 110]
    assert {"before.png", "after.png"} <= {f["image"] for f in frames["kockak"]}
    assert any(f.get("gyuru") and f["image"] == "after.png" for f in frames["kockak"])


def test_gate_detects_unused_recorded_frames():
    script, measurements, times = filled(), measured(), timing()
    frames = plan(script, measurements, times)
    measurements[1]["frames"] = ["lost-typing.png"]
    assert any(
        f["kod"] == "H4" and "lost-typing.png" in f["uzenet"]
        for f in checked(script, measurements, frames, times)["leletek"]
    )


@pytest.mark.parametrize("direction", [("asztal", "telefon"), ("telefon", "asztal")])
def test_fade_starts_at_the_previous_rendered_frame_even_with_scroll(
    tmp_path, direction
):
    script, measurements, times = filled(), measured(), timing()
    for index, view in enumerate(direction):
        step = steps(script)[index]
        step["nezet"], measurements[index]["nezet"] = view, view
        step["kamera"] = "elem"
        if view == "telefon":
            measurements[index]["viewport"] = {"width": 390, "height": 844}
    steps(script)[1]["atmenet_s"] = 0.6
    measurements[1]["frames"] = ["kepek/scroll.png"]
    (tmp_path / "kepek").mkdir()
    for name in ("1.png", "scroll.png"):
        pic = Image.new("RGB", (3840, 2532), "#abcdef")
        ImageDraw.Draw(pic).rectangle((0, 0, 400, 2532), fill="red")
        pic.save(tmp_path / "kepek" / name)
    frames = plan(script, measurements, times)["kockak"]
    start = times["lepesek"][1]["kezd_kocka"] - 18
    assert isinstance(frames[start]["fade"], dict)
    assert frames[start]["fade"]["crop"] == frames[start - 1]["crop"]
    assert (
        frame(tmp_path, frames[start]).tobytes()
        == frame(tmp_path, frames[start - 1]).tobytes()
    )
    assert any(f["image"] == "kepek/scroll.png" for f in frames)


def test_content_camera_uses_the_column_and_mobile_camera_zooms():
    step, measurement = steps(filled())[0], measured()[0]
    measurement["layout"] = {"content": [200, -600, 760, 2400], "top": 88}
    step["kamera"] = "tartalom"
    content = crop(step, measurement)
    step["kamera"] = "elem"
    assert content != crop(step, measurement)
    assert content[2] == 792
    step["nezet"] = "telefon"
    measurement["viewport"] = {"width": 390, "height": 844}
    assert 960 <= crop(step, measurement)[2] < 1920


def test_highlight_clipping_does_not_draw_a_fake_bottom_border(tmp_path):
    (tmp_path / "kepek").mkdir()
    Image.new("RGB", (3840, 2160), "white").save(tmp_path / "kepek/1.png")
    spec = {
        "image": "kepek/1.png",
        "crop": [0, 0, 1280, 720],
        "nezet": "asztal",
        "box": [200, 100, 400, 1000],
        "kiemel": "large",
        "alpha": 1,
    }
    picture = frame(tmp_path, spec)
    assert picture.getpixel((600, 1075)) == (255, 255, 255)


def test_h2_explains_why_scrolling_cannot_fix_a_tall_element():
    script, measurements = filled(), measured()
    measurements[0]["roles"]["roviden"]["box"][3] = 784
    measurements[0]["layout"] = {"top": 88}
    assert any(
        "784 > 632 CSS px, görgetés nem segít" in f["uzenet"]
        for f in checked(script, measurements)["leletek"]
    )


def test_empty_required_text_is_invalid_and_structure_is_checked():
    script = read(ROOT / "forgatokonyv.json")
    steps(script)[1]["kiemel"][0]["kell"] = ""
    with pytest.raises(ValidationError):
        validate(script, read(ROOT / "szereplok.json"))
    script = filled()
    steps(script)[0]["kiemel"][0] = {"szereplo": "roviden", "szerkezet": "kerdes"}
    assert any(f["kod"] == "H3" for f in checked(script, measured())["leletek"])


def test_h4_checks_motion_during_highlight_instead_of_filtering_it_out():
    script, measurements, times = filled(), measured(), timing()
    frames = plan(script, measurements, times)
    frames["kockak"][10]["mozgas"] = True
    assert any(
        f["kod"] == "H4"
        for f in checked(script, measurements, frames, times)["leletek"]
    )


def test_missing_interaction_step_is_a_contract_error():
    definition = {
        "szovegek": [],
        "interakciok": [
            {
                "lepes": "9-99",
                "szereplo": "missing",
                "feltetel": "buborek",
                "ok": "tooltip",
            }
        ],
    }
    assert any(
        f["kod"] == "H10"
        for f in checked(filled(), measured(), definition=definition)["leletek"]
    )


def test_contract_is_about_text_not_unrelated_file_bytes(tmp_path):
    (tmp_path / "surface.txt").write_text("Label\nunrelated edit\n")
    definition = {
        "szovegek": [{"file": "surface.txt", "text": "Label"}],
        "forras_sha256": {"surface.txt": "an obsolete whole-file hash"},
    }
    assert contract(tmp_path, definition) == []
    (tmp_path / "surface.txt").write_text("changed label")
    assert contract(tmp_path, definition)


def test_phone_contact_cell_keeps_near_css_pixel_size(tmp_path):
    (tmp_path / "kepek").mkdir()
    Image.new("RGB", (1170, 2532), "#abcdef").save(tmp_path / "kepek/1.png")
    step, measurement = steps(filled())[0], measured()[0]
    step.update(nezet="telefon", kamera="teljes")
    measurement["viewport"] = {"width": 390, "height": 844}
    cell = lapok_h.contact_cell(tmp_path, step, measurement, None)
    assert cell.height >= 1000
    assert sum(cell.getpixel((x, 100)) == (171, 205, 239) for x in range(640)) >= 390


def test_missing_lesson_is_input_error_and_internal_keyerror_is_tool_error(
    tmp_path, monkeypatch
):
    args = ["fixture", "build", "--tantargy", "proba", "--out", str(tmp_path)]
    assert lanc.main(args) == 2

    def broken(_):
        raise KeyError("internal defect")

    monkeypatch.setattr(lanc, "execute", broken)
    assert lanc.main(args + ["--lecke", "minta"]) == 3


def test_publisher_removes_every_old_pair_including_unrecorded_orphans(tmp_path):
    work = tmp_path / "work/20261015"
    work.mkdir(parents=True)
    folder = tmp_path / "wiki/assets/hasznalat"
    folder.mkdir(parents=True)
    for name in ("hasznalat-20200101.mp4", "hasznalat-20200202.png", "keep.txt"):
        (folder / name).write_bytes(b"fixture")
    names = {
        "hasznalat.mp4": "hasznalat-20261015.mp4",
        "hasznalat.png": "hasznalat-20261015.png",
    }
    for name in names:
        (work / name).write_bytes(b"fixture")
    usage_video.write_assets(
        tmp_path, work, {"outputs": {name: "fixture" for name in names}}, names, []
    )
    assert sorted(p.name for p in folder.iterdir()) == [
        "hasznalat-20261015.mp4",
        "hasznalat-20261015.png",
        "keep.txt",
        "render.json",
    ]


def test_cursor_target_must_be_visible_but_input_adornments_are_allowed():
    script, measurements = filled(), measured()
    step = steps(script)[0]
    step["kurzor"] = {"szereplo": "input", "kattint": False}
    measurements[0]["roles"]["input"] = {
        "box": [200, 200, 200, 50],
        "count": 1,
        "visible": True,
        "uncovered": [True, False, True, False, True],
    }
    assert not any(f["kod"] == "H2" for f in checked(script, measurements)["leletek"])
    measurements[0]["roles"]["input"]["uncovered"][-1] = False
    assert any(f["kod"] == "H2" for f in checked(script, measurements)["leletek"])
