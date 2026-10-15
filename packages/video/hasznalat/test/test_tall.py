"""Tall highlights are explicit, visible and open at the clipped boundary."""

import copy
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat import keret, osszerak
from hasznalat.adatok import ROOT, read, steps
from hasznalat.kapu_h import h2
from hasznalat.kamera import crop
from hasznalat.kitolt import validate
from hasznalat.jeloltek import candidates
from test_hasznalat import fixture


def scene():
    step = {
        "id": "1-01",
        "nezet": "asztal",
        "kamera": "elem",
        "kiemel": [{"szereplo": "diagram", "magas": True}],
    }
    measurement = {
        "viewport": {"width": 1280, "height": 720},
        "layout": {"top": 88},
        "roles": {
            "diagram": {
                "box": [280, 112, 720, 1080],
                "uncovered": [True, True, False, False, False],
                "visible_uncovered": [True] * 5,
            }
        },
    }
    return step, measurement


def findings(step, measurement):
    result = []
    h2(step, measurement, lambda *finding: result.append(finding))
    return result


def test_tall_highlight_is_opt_in_and_keeps_the_top_under_the_header():
    step, measurement = scene()
    assert not findings(step, measurement)
    camera = crop(step, measurement)
    assert camera[1] == 0 and camera[2] < 1280
    for mutate in (
        lambda s, m: s["kiemel"][0].pop("magas"),
        lambda s, m: m["roles"]["diagram"]["box"].__setitem__(1, 50),
        lambda s, m: m["roles"]["diagram"]["box"].__setitem__(2, 100),
        lambda s, m: m["roles"]["diagram"]["visible_uncovered"].__setitem__(0, False),
    ):
        altered, observed = copy.deepcopy(step), copy.deepcopy(measurement)
        mutate(altered, observed)
        assert findings(altered, observed)


def test_gate_checks_the_rendered_open_border(monkeypatch):
    step, measurement = scene()
    assert not findings(step, measurement)

    def closed(image, spec, color):
        ImageDraw.Draw(image).rectangle((0, 0, 1919, 1079), outline=color, width=4)

    monkeypatch.setattr(keret, "outline", closed)
    assert "nem nyitott" in findings(step, measurement)[0][-1]


@pytest.mark.parametrize('column', [False, True])
def test_tall_border_is_open_in_the_actual_frame(tmp_path, column):
    step, measurement = scene()
    if column:
        measurement['layout']['content'] = [280, -800, 720, 3000]
    image = Image.new("RGB", (3840, 2160), "white")
    image.save(tmp_path / "page.png")
    spec = {
        "image": "page.png",
        "crop": crop(step, measurement),
        "nezet": "asztal",
        "box": measurement["roles"]["diagram"]["box"],
        "kiemel": "diagram",
        "magas": True,
    }
    picture = osszerak.frame(tmp_path, spec)
    assert keret.clipped_sides(spec) == ["also"]
    assert keret.open_border(spec)
    left, top, right, bottom = keret.bounds(spec)
    assert (right - left) / picture.width >= 0.6
    assert picture.getpixel((round(left) + 1, 800)) == (217, 72, 15)
    assert picture.getpixel((960, 1079)) == (255, 255, 255)
    assert picture.getpixel((960, round(top) + 1)) == (217, 72, 15)


def test_tall_figure_stays_eligible_in_content_order():
    payload = fixture()
    topic = payload["pages"][-1]
    topic["usageFigures"] = [{"fits": False, "box": [0, 0, 720, 1080]}]
    found, rejected = candidates(payload)
    assert len(found) == 1 and not rejected
    assert found[0]["lecke"]["route"] == topic["route"]


def test_script_explicitly_permits_tall_figure():
    script = read(ROOT / "forgatokonyv.json")
    figure = next(s for s in steps(script) if s["id"] == "4-17")
    assert figure["kiemel"][0].get("magas") is True
    assert figure["text"] == "Az {ábra} szemlélteti, amiről a szöveg szól."
    validate(script, read(ROOT / "szereplok.json"))


def test_tall_column_camera_has_no_sidebar_and_preserves_the_open_bottom():
    step, measurement = scene()
    measurement['layout']['content'] = [280, -800, 720, 3000]
    view = crop(step, measurement)
    assert view[0] >= 256 and view[0] + view[2] <= 1024
    assert view[1] == 88
    assert measurement['roles']['diagram']['box'][1] - view[1] >= 24
    assert not findings(step, measurement)
    assert keret.clipped_sides({'nezet': 'asztal', 'box': measurement['roles']['diagram']['box'], 'crop': view}) == ['also']
    measurement['roles']['diagram']['box'][1] = 111.984
    assert not findings(step, measurement)


@pytest.mark.parametrize('offset', [0, 4, 15])
def test_gate_rejects_tall_crop_without_upper_border_room(monkeypatch, offset):
    step, measurement = scene()
    box = measurement['roles']['diagram']['box']
    monkeypatch.setattr('hasznalat.kapu_lathatosag.crop',
                        lambda *_: [264, box[1] - offset, 752, 423])
    assert 'felső éle' in findings(step, measurement)[0][-1]


@pytest.mark.parametrize('missing', ['edge', 'left-corner', 'right-corner'])
def test_gate_rejects_missing_rendered_upper_edge_or_corner(monkeypatch, missing):
    step, measurement = scene()
    measurement['layout']['content'] = [280, -800, 720, 3000]
    original = keret.outline

    def broken(image, spec, color):
        original(image, spec, color)
        left, top, right, _ = keret.bounds(spec)
        x = (left + right) / 2 if missing == 'edge' else left if missing == 'left-corner' else right - 12
        ImageDraw.Draw(image).rectangle((x, top, x + 12, top + 12), fill=0)

    monkeypatch.setattr(keret, 'outline', broken)
    assert 'felső éle' in findings(step, measurement)[0][-1]

def test_ordinary_edge_highlight_has_four_inset_sides_and_gate_checks_pixels(monkeypatch):
    step, measurement = scene()
    step.update(kamera='teljes', kiemel=[{'szereplo': 'diagram'}])
    measurement['roles']['diagram'].update(box=[0, 72, 256, 648], uncovered=[True] * 5)
    spec = {'nezet': 'asztal', 'box': [0, 72, 256, 648], 'crop': [0, 0, 1280, 720]}
    assert keret.bounds(spec) == (4, 100, 392, 1075)
    assert keret.closed_border(spec)
    assert not findings(step, measurement)

    def broken(image, spec, color):
        left, top, right, bottom = keret.bounds(spec)
        ImageDraw.Draw(image).line([(left, top), (right, top), (right, bottom)], fill=color, width=4)

    monkeypatch.setattr(keret, 'outline', broken)
    assert 'nem zárt' in findings(step, measurement)[0][-1]


def test_offscreen_ordinary_highlight_remains_a_gate_error_not_a_render_crash():
    step, measurement = scene()
    step.update(kamera='teljes', kiemel=[{'szereplo': 'diagram'}])
    box = [-200, 100, 100, 100]
    measurement['roles']['diagram'].update(box=box, uncovered=[False] * 5)
    keret.outline(Image.new('RGB', keret.SIZE), {
        'nezet': 'asztal', 'box': box, 'crop': [0, 0, 1280, 720],
    }, 'orange')
    assert 'nincs teljesen a kamerában' in findings(step, measurement)[0][-1]
