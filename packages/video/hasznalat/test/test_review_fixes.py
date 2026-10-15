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
    assert content == crop(step, measurement)
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
        "magas": True,
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


def test_dated_lesson_is_eligible_without_uncertain_date():
    payload = fixture()
    topic = payload['pages'][-1]
    topic['html'] = topic['html'].replace("<span class='study-when-unsure'>~ősz</span>", "<span class='study-when'>okt. 4.</span>")
    accepted, rejected = candidates(payload)
    assert len(accepted) == 1 and not rejected
    topic['html'] = topic['html'].replace('🔖 Tankönyv', '')
    assert not candidates(payload)[0]
    assert 'Óra-sor tankönyvvel' in candidates(payload)[1][0]['hiany']


def test_preview_rejects_focus_ring_without_highlight():
    script, measurements = filled(), measured()
    steps(script)[0]['kiemel'] = []
    measurements[0]['focus_visible'] = [{'text': 'Keresés', 'box': [100, 10, 80, 30]}]
    assert any('fókuszkeret' in f['uzenet'] for f in checked(script, measurements)['leletek'])


def test_crop_avoids_sidebar_and_shows_complete_small_target_context():
    from hasznalat.kamera import cuts_text
    step, m = steps(filled())[0], measured()[0]
    step['kamera'] = 'elem'
    m['layout'] = {'top': 88, 'content': [300, 100, 660, 1800]}
    m['roles']['roviden'].update(box=[800, 180, 100, 25], context=[300, 160, 660, 60])
    m['text_rects'] = [{'text': 'sidebar', 'box': [220, 300, 50, 20]},
                       {'text': 'line', 'box': [320, 460, 150, 22]}]
    view = crop(step, m)
    assert 276 <= view[0] <= 296 and 964 <= view[0] + view[2] <= 984
    assert view[1] + 24 <= 160 and view[1] + view[3] >= 220
    assert not cuts_text(view, m['text_rects'])


def test_gate_rejects_word_cut_at_each_crop_edge():
    from hasznalat.kamera import cuts_text
    view = [100, 100, 500, 300]
    for box in ([90, 200, 20, 20], [590, 200, 20, 20], [200, 90, 20, 20], [200, 390, 20, 20]):
        assert cuts_text(view, [{'text': 'word', 'box': box}])
    script, measurements = filled(), measured()
    steps(script)[0]['kamera'] = 'elem'
    view = crop(steps(script)[0], measurements[0])
    measurements[0]['text_rects'] = [{'text': 'broken', 'box': [view[0] - 10, view[1] + 30, 20, 20]}]
    assert any('ketté' in f['uzenet'] for f in checked(script, measurements)['leletek'])


def test_label_camera_keeps_preceding_paragraph_and_label_in_lower_half():
    step, m = steps(filled())[0], measured()[0]
    step['kamera'] = 'elem'
    m['layout'] = {'top': 88, 'content': [300, 100, 660, 1800]}
    m['roles']['roviden'].update(box=[300, 400, 200, 24], context=[300, 180, 660, 244], label_context=True)
    view = crop(step, m)
    assert view[1] <= 180 and view[1] + view[3] >= 424
    assert 400 > view[1] + view[3] / 2


def test_ordered_title_then_label_does_not_move_camera_back_up():
    step, m = steps(filled())[0], measured()[0]
    step.update(kamera='elem', dom_sorrend=True)
    m['layout'] = {'top': 88, 'content': [300, 100, 660, 1800]}
    m['roles']['roviden'].update(box=[300, 400, 660, 24], context=[300, 400, 660, 24])
    title = crop(step, m)
    m['roles']['roviden'].update(box=[300, 500, 200, 24], context=[300, 450, 660, 74], label_context=True)
    label = crop(step, m)
    assert title[1] <= label[1]


def test_review_narration_uses_filled_lesson_and_visible_guide_name():
    script, _ = fill(read(ROOT / 'forgatokonyv.json'), candidates(fixture())[0][0])
    by_id = {s['id']: s for s in steps(script)}
    assert '{Minta}' in by_id['3-03']['text']
    assert by_id['3-03']['kiemel'][0]['horgony'] == 'Minta'
    assert by_id['1-05']['kiemel'][0]['kell'] == 'Hogyan használd'
    assert 'szerkezet' not in by_id['1-05']['kiemel'][0]
    assert by_id['4-10']['kiemel'][0]['szerkezet'] == 'cimke-nelkuli'


def test_gate_rejects_label_detached_from_its_preceding_prose():
    script, measurements = filled(), measured()
    m = measurements[0]
    m['roles']['roviden'].update(label_context=True, context=[20, -50, 100, 200])
    assert any('címke fölötti' in f['uzenet'] for f in checked(script, measurements)['leletek'])


def test_missing_secondary_role_is_a_gate_finding_with_column_camera():
    script, measurements = filled(), measured()
    steps(script)[0]['kamera'] = 'elem'
    steps(script)[0]['kiemel'].append({'szereplo': 'missing', 'kell': 'Missing'})
    measurements[0]['layout'] = {'top': 88, 'content': [200, 100, 760, 2000]}
    report = checked(script, measurements)
    assert any(f['kod'] == 'H1' and f['szereplo'] == 'missing' for f in report['leletek'])


def test_mobile_tooltip_is_not_subject_to_desktop_label_composition():
    script, measurements = filled(), measured()
    steps(script)[0]['nezet'] = 'telefon'
    measurements[0]['viewport'] = {'width': 390, 'height': 844}
    measurements[0]['roles']['roviden'].update(label_context=True, context=[20, 80, 300, 70])
    assert not any(f['kod'] == 'H2' for f in checked(script, measurements)['leletek'])


@pytest.mark.parametrize('title, expected', [
    ('A város', 'A város'), ('Az élet', 'Az élet'),
    ('a város', 'a város'), ('az élet', 'az élet'),
    ('Város', 'a Város'), ('Élet', 'az Élet'),
])
def test_filled_titles_have_one_article_and_keep_their_anchor(title, expected):
    choice = candidates(fixture())[0][0]
    choice['lecke']['title'] = title
    choice['lecke']['chapterTitle'] = title
    script, _ = fill(read(ROOT / 'forgatokonyv.json'), choice)
    rows = {s['id']: s for s in steps(script)}
    anchored = expected.replace(title, '{' + title + '}')
    assert 'ott van ' + anchored + ' lecke.' in rows['1-10']['text']
    assert rows['3-01']['text'] == f'Ez {expected} fejezet összefoglalója.'
    assert 'ez ' + anchored + ' lecke része.' in rows['3-03']['text']
    assert rows['3-06']['text'] == f'Most nyissuk meg részletesen {expected} leckét.'
    assert rows['3-03']['kiemel'][0]['horgony'] == title


def test_e2_requires_a_source_backed_body_paragraph():
    payload = fixture()
    payload['pages'][-1]['usageClassroomParagraphs'] = []
    accepted, rejected = candidates(payload)
    assert not accepted
    assert any('E2:' in reason for reason in rejected[0]['hiany'])


def test_second_review_script_order_actions_and_labels():
    script, actors = fill(read(ROOT / 'forgatokonyv.json'), candidates(fixture())[0][0])
    rows = {s['id']: s for s in steps(script)}
    assert '{A projektről és a felhasználásról}' in rows['1-03']['text']
    for id in ('2-03', '6-04'):
        assert 'Hogyan használd részéhez visz, ahol a lapok leírása áll' in rows[id]['text']
    assert rows['4-06']['gorget'] == rows['4-05']['gorget']
    assert rows['4-14']['kiemel'][0]['szereplo'] == 'podcast'
    assert rows['4-07']['kiemel'][0]['szereplo'] == 'cimke-elso'
    assert rows['4-08']['kiemel'][0]['szereplo'] == 'robot-jel'
    assert rows['6-02']['kiemel'][0]['horgony'] == 'Most'
    assert rows['6-03']['text'].endswith('nyisd meg.')
    assert actors['cimke-nelkuli']['forras_szovegek'] == ['Órai bekezdés.']
    pdf = rows['2-18']
    assert pdf['allapot'][0]['muvelet'] == 'zar'
    assert pdf['allapot'][1]['horgony'] == pdf['kurzor']['horgony'] == 'lenyitva'
    validate(read(ROOT / 'forgatokonyv.json'), actors)


def test_pdf_opens_at_the_spoken_word_with_cursor_click():
    from hasznalat.osszerak import still_frames
    from hasznalat.mozgas import cursor_frames
    script, _ = fill(read(ROOT / 'forgatokonyv.json'), candidates(fixture())[0][0])
    step = next(s for s in steps(script) if s['id'] == '2-18')
    measurement = measured()[0]
    measurement.update(before_image='closed.png', image='open.png', anchor_cursor=[300, 200])
    measurement['roles']['pdf-fejezetek-cim'] = measurement['roles'].pop('roviden')
    time = {'kezd_kocka':0, 'veg_kocka':60, 'horgonyok': {
        'Nyomtatható fejezetek': {'kocka':10}, 'lenyitva': {'kocka':30}}}
    frames = still_frames(step, measurement, time)
    cursor_frames(frames, step, measurement, time, {})
    assert all(f['image'] == 'closed.png' for f in frames[:30])
    assert all(f['image'] == 'open.png' for f in frames[30:])
    assert frames[29].get('kurzor') and not frames[29].get('gyuru')
    assert frames[30]['gyuru'] and frames[30]['kurzor'] == [300, 200]


def test_project_title_comes_from_the_info_link_on_home_not_the_first_info_page():
    payload = fixture()
    payload['pages'].insert(1, {'navigation':'info', 'url':'/fixture/audio/',
        'route':'audio', 'title':'Audio', 'html':''})
    choice = candidates(payload)[0][0]
    assert choice['projekt']['title'] == 'A projektről és a felhasználásról'
