import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hasznalat.adatok import ROOT, read, write, encoded, steps
from hasznalat.kitolt import article, fill, validate, contract
from hasznalat.jeloltek import candidates, listing
from hasznalat.kapu_h import gate
from hasznalat.osszerak import plan, render
from hasznalat.lapok_h import contacts, review_key, review


def fixture():
    return read(ROOT / "test/fixtures/payload.json")


def simple():
    return {
        "sema": "hasznalati-forgatokonyv/1",
        "jelenetek": [
            {
                "id": "1",
                "nezet": "asztal",
                "lepesek": [
                    {
                        "id": "1-01",
                        "text": "A {Minta} látható.",
                        "lap": "lecke",
                        "kamera": "teljes",
                        "szunet": 2,
                        "kiemel": [{"szereplo": "roviden", "horgony": "Minta"}],
                    },
                    {
                        "id": "1-02",
                        "text": "Új {Minta} látható.",
                        "lap": "lecke",
                        "kamera": "teljes",
                        "szunet": 2,
                        "kiemel": [{"szereplo": "roviden", "horgony": "Minta"}],
                    },
                ],
            }
        ],
    }


def measured():
    return [
        {
            "id": f"1-0{i}",
            "url": "/fixture/proba/minta/",
            "nezet": "asztal",
            "image": "kepek/1.png",
            "frames": [],
            "viewport": {"width": 1280, "height": 720},
            "status": 200,
            "errors": [],
            "theme": "light",
            "content": True,
            "broken": [],
            "roles": {
                "roviden": {
                    "count": 1,
                    "visible": True,
                    "box": [20, 100, 100, 50],
                    "uncovered": [True] * 5,
                    "text": "Minta",
                }
            },
        }
        for i in (1, 2)
    ]


def timing():
    return {
        "kocka_osszes": 120,
        "fps": 30,
        "lepesek": [
            {
                "id": f"1-0{i + 1}",
                "kezd_kocka": i * 60,
                "veg_kocka": (i + 1) * 60,
                "horgonyok": {"Minta": {"kocka": i * 60 + 3}},
            }
            for i in (0, 1)
        ],
    }


def filled():
    return fill(simple(), candidates(fixture())[0][0])[0]


def test_full_schema_and_current_contract():
    validate(read(ROOT / "forgatokonyv.json"), read(ROOT / "szereplok.json"))
    assert len(steps(read(ROOT / "forgatokonyv.json"))) == 70
    assert contract() == []
    bad = read(ROOT / "forgatokonyv.json")
    bad["jelenetek"][0]["lepesek"][1]["kiemel"][0]["horgony"] = "más"
    with pytest.raises(ValueError, match="horgony"):
        validate(bad, read(ROOT / "szereplok.json"))


@pytest.mark.parametrize(
    "word,expected",
    [
        ("Alma", "az"),
        ("Árnyék", "az"),
        ("Erdő", "az"),
        ("Őrség", "az"),
        ("Próba", "a"),
        ("Minta", "a"),
    ],
)
def test_articles(word, expected):
    assert article(word) == expected


def test_fill_deterministic_optional_gap():
    choice = candidates(fixture())[0][0]
    a = read(ROOT / "forgatokonyv.json")
    one = fill(a, choice, set())[0]
    two = fill(a, choice, set())[0]
    assert encoded(one) == encoded(two)
    assert "2-16" not in [s["id"] for s in steps(one)]
    assert all("[[" not in s["text"] for s in steps(one))
    assert max(s["szunet"] for s in steps(one)) >= 1.6


def test_candidates_complete_order_and_reasons():
    p = fixture()
    valid = p["pages"][-1]
    missing = {
        **valid,
        "route": "proba/hiany",
        "html": valid["html"].replace("study-open-questions", "other"),
    }
    previous = {**valid, "route": "proba/regi", "chapterId": "elso"}
    p["pages"] += [missing, previous]
    a, r = candidates(p)
    assert [c["lecke"]["route"] for c in a] == ["proba/minta"]
    assert [x["lap"] for x in r] == ["proba/hiany", "proba/regi"]
    assert listing(a, r) == listing(*candidates(p))
    q = fixture()
    other = {
        **q["pages"][-1],
        "route": "proba/masik",
        "url": "/fixture/proba/masik/",
        "title": "Másik",
    }
    q["pages"].insert(3, other)
    q["pages"][1]["html"] = (
        "<p>Most: <a href='/fixture/proba/masik/'>Másik</a></p>"
        + q["pages"][1]["html"].replace(
            "</ul>", "<li>📄 <a href='/fixture/proba/masik/'>Másik</a></li></ul>"
        )
    )
    q["pages"][2]["html"] += (
        "<p>Részletesen: <a href='/fixture/proba/masik/'>Másik</a></p>"
    )
    assert [c["lecke"]["route"] for c in candidates(q)[0]] == [
        "proba/minta",
        "proba/masik",
    ]
    for p in q["pages"]:
        if p.get("kind") == "topic":
            p["html"] = p["html"].replace("study-open-questions", "missing")
    assert [r["lap"] for r in candidates(q)[1]] == ["proba/minta", "proba/masik"]


@pytest.mark.parametrize(
    "code,mutation",
    [
        ("H1", lambda m: m[0]["roles"]["roviden"].update(count=0)),
        ("H2", lambda m: m[0]["roles"]["roviden"].update(uncovered=[False] * 5)),
        ("H3", lambda m: m[0]["roles"]["roviden"].update(text="más")),
        ("H5", lambda m: m[0].update(broken=["missing.png"])),
        ("H8", lambda m: m[0].update(status=404)),
    ],
)
def test_gate_measurements(code, mutation):
    s = filled()
    m = measured()
    args = {
        "payload": fixture(),
        "commit": "head",
        "expected_commit": "head",
        "preview": True,
        "contract": {"szovegek": []},
    }
    assert gate(s, m, **args)["kep_zold"]
    mutation(m)
    report = gate(s, m, **args)
    assert code in [f["kod"] for f in report["leletek"]]
    assert encoded(report) == encoded(gate(s, m, **args))
    assert not report["zold"]


def test_gate_missing_sound_video_slots_and_contract():
    s = filled()
    s["jelenetek"][0]["lepesek"][0]["text"] = "[[maradt]]"
    g = gate(
        s,
        measured(),
        payload=fixture(),
        commit="head",
        expected_commit="head",
        contract={"szovegek": [{"html": True, "text": "nem létezik"}]},
    )
    assert {"H6", "H7", "H9", "H10"} <= set(f["kod"] for f in g["leletek"])


def test_frames_anchors_transition_and_video_determinism(tmp_path):
    s = filled()
    m = measured()
    t = timing()
    (tmp_path / "kepek").mkdir()
    Image.new("RGB", (3840, 2160), "#c0d0e0").save(tmp_path / "kepek/1.png")
    f = plan(s, m, t)
    assert len(f["kockak"]) == 120
    assert f["kockak"][2]["kiemel"] is None and f["kockak"][3]["kiemel"] == "roviden"
    render(tmp_path, f)
    first = (tmp_path / "fo.mp4").read_bytes()
    render(tmp_path, f)
    assert first == (tmp_path / "fo.mp4").read_bytes()
    s["jelenetek"][0]["lepesek"][1]["atmenet_s"] = 3
    with pytest.raises(ValueError, match="H4"):
        plan(s, m, t)


def test_review_key_tracks_image_actor_and_caption(tmp_path):
    s = filled()
    m = measured()
    (tmp_path / "kepek").mkdir()
    Image.new("RGB", (3840, 2160), "#b0d0e0").save(tmp_path / "kepek/1.png")
    write(tmp_path / "forgatokonyv-kitoltott.json", s)
    write(tmp_path / "szereplok.json", {})
    write(tmp_path / "dobozok.json", m)
    write(tmp_path / "felvetel-nyugta.json", {"images": {"kepek/1.png": "hash"}})
    contacts(tmp_path, s, m)
    key = review(tmp_path)
    assert key == review_key(tmp_path)
    write(tmp_path / "szereplok.json", {"changed": True})
    assert key != review_key(tmp_path)


def test_h4_short_highlight_fails():
    s = filled()
    t = timing()
    t["lepesek"][0]["horgonyok"]["Minta"]["kocka"] = 58
    g = gate(
        s,
        measured(),
        plan(s, measured(), t),
        t,
        payload=fixture(),
        commit="head",
        expected_commit="head",
        preview=True,
        contract={"szovegek": []},
    )
    assert "H4" in [f["kod"] for f in g["leletek"]]


@pytest.mark.parametrize('label', ['Auto', 'Világos', 'Sötét'])
def test_theme_step_uses_visible_selected_label_and_sequential_ids(label):
    choice = candidates(fixture())[0][0]
    choice['kezdolap']['usageThemeLabel'] = label
    script, actors = fill(read(ROOT / 'forgatokonyv.json'), choice)
    first = script['jelenetek'][0]['lepesek']
    assert [s['id'] for s in first] == [f'1-{i:02}' for i in range(1, 12)]
    theme = first[8]
    prefix = 'az' if label == 'Auto' else 'a'
    assert theme['text'] == f'Jobbra fent {prefix} {{{label}}} gombbal világos vagy sötét megjelenést választhatsz.'
    assert theme['kiemel'] == [{'szereplo': 'temavalaszto', 'horgony': label, 'kell': label}]


def test_theme_surface_contract_rejects_missing_or_changed_options():
    from hasznalat.kapu_h import h10_interactions
    script, _ = fill(read(ROOT / 'forgatokonyv.json'), candidates(fixture())[0][0])
    definition = {'valasztok': read(ROOT / 'felulet.json')['valasztok']}
    item = {'text': 'Auto', 'options': ['Sötét', 'Világos', 'Auto']}
    measurements = {'1-09': {'roles': {'temavalaszto': item}}}
    findings = []
    h10_interactions(script, measurements, definition, lambda *f: findings.append(f))
    assert not findings
    item['options'].remove('Sötét')
    h10_interactions(script, measurements, definition, lambda *f: findings.append(f))
    assert findings[0][:3] == ('H10', '1-09', 'temavalaszto')
    item['options'].append('Sötét')
    item['text'] = 'Auto Auto'
    findings.clear()
    h10_interactions(script, measurements, definition, lambda *f: findings.append(f))
    assert findings
