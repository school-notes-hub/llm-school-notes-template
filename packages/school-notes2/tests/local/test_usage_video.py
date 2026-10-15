import hashlib
import json

import pytest
from pathlib import Path
from types import SimpleNamespace

from school_notes2 import VERSION
from school_notes2.local import usage_video
from hasznalat.lapok_h import review_key
from school_notes2.wiki.home_page import guide_block


def test_surface_contract():
    root = Path(__file__).resolve().parents[4]
    contract = json.loads((root / "packages/video/hasznalat/felulet.json").read_text())
    for row in contract["szovegek"]:
        assert row["text"] in (root / row["file"]).read_text()
    assert "forras_sha256" not in contract
    assert len(contract["interakciok"]) == 2


def test_usage_release_refuses_without_valid_receipt(tmp_path):
    local = SimpleNamespace(repo=tmp_path, name="fixture")
    assert usage_video.run(local, out=lambda s: None) == 2
    work = tmp_path / ".school-notes/out/hasznalat/20261015"
    work.mkdir(parents=True)
    (work / "nyugta.json").write_text("{}")
    assert usage_video.run(local, out=lambda s: None) == 2
    assert not (tmp_path / "wiki").exists()


def test_guide_unchanged_without_video_and_includes_published_chapters(tmp_path):
    original = guide_block(tmp_path)
    folder = tmp_path / "wiki/assets/hasznalat"
    folder.mkdir(parents=True)
    evidence = tmp_path / "docs/evidence/hasznalati-video/20261015.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {"hossz_s": 120, "fejezetek": [{"jelenet": "Kezdőlap", "masodperc": 5}]}
        )
    )
    (folder / "render.json").write_text(
        json.dumps(
            {
                "source": str(evidence.relative_to(tmp_path)),
                "outputs": {"hasznalat-20261015.mp4": {}},
            }
        )
    )
    actual = guide_block(tmp_path)
    assert "(assets/hasznalat/hasznalat-20261015.mp4)" in actual
    assert "0:05 Kezdőlap" in actual
    assert actual.splitlines()[0] == original.splitlines()[0]
    assert actual.index("hasznalat-20261015.mp4") < actual.index("* 📚")
    assert actual.count("\n# ") == 0
    assert actual.endswith(original.split("\n\n", 1)[1])


@pytest.mark.parametrize(
    "defect",
    [
        "no-accept",
        "stale-key",
        "red-gate",
        "other-owner",
        "other-head",
        "changed-video",
    ],
)
def test_release_preflight_never_writes_on_invalid_evidence(tmp_path, defect):
    work = tmp_path / ".school-notes/out/hasznalat/20261015"
    (work / "lapok").mkdir(parents=True)

    def put(name, value):
        (work / name).write_text(json.dumps(value))

    put("forgatokonyv-kitoltott.json", {"jelenetek": []})
    put("szereplok.json", {})
    put("dobozok.json", [])
    put("felvetel-nyugta.json", {"images": {}})
    key = review_key(work)
    gate = {"zold": defect != "red-gate", "elonezet": False}
    put("kapu.json", gate)
    put(
        "verdict.json",
        {
            "key": "old" if defect == "stale-key" else key,
            "verdict": "reject" if defect == "no-accept" else "accept",
        },
    )
    for name in ("hasznalat.mp4", "hasznalat.png"):
        (work / name).write_bytes(b"fixture")
    receipt = {
        "vegleges": True,
        "template": VERSION,
        "csonk": False,
        "hossz_s": 1,
        "fejezetek": [{"jelenet": "Minta", "masodperc": 0}],
        "forgatokonyv_sha256": hashlib.sha256(
            (work / "forgatokonyv-kitoltott.json").read_bytes()
        ).hexdigest(),
        "tanulo": "other" if defect == "other-owner" else "fixture",
        "key": key,
        "commit": "old" if defect == "other-head" else "head",
        "kapu_sha256": hashlib.sha256((work / "kapu.json").read_bytes()).hexdigest(),
        "outputs": {
            name: hashlib.sha256((work / name).read_bytes()).hexdigest()
            for name in ("hasznalat.mp4", "hasznalat.png")
        },
    }
    put("nyugta.json", receipt)
    if defect == "changed-video":
        (work / "hasznalat.mp4").write_bytes(b"different")
    local = SimpleNamespace(
        repo=tmp_path,
        name="fixture",
        git=lambda: SimpleNamespace(out=lambda *a: "head"),
    )
    assert usage_video.run(local, out=lambda s: None) == 2
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / "docs").exists()
