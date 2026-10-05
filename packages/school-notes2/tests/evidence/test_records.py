import hashlib

import pytest

from school_notes2.evidence import records

PAGES = [{"seq": 1, "package": "Óra 1", "file": "füzet.pdf", "page": 2,
          "path": "sources/gazdasag/ora-1/p0001.jpg", "sha256": "0" * 64, "duplicate_of": None}]


def setup(tmp_path):
    img = tmp_path / "sources/gazdasag/ora-1/p0001.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"jpeg-bytes")
    fig = tmp_path / "wiki/assets/abra.svg"
    fig.parent.mkdir(parents=True)
    fig.write_bytes(b"<svg/>")
    return hashlib.sha256(b"jpeg-bytes").hexdigest()


def test_record_path():
    assert str(records.record_path("wiki/gazdasag/szukosseg.md")) == \
        "docs/evidence/pages/gazdasag/szukosseg.md"
    with pytest.raises(records.RecordError):
        records.record_path("docs/x.md")


def test_writer_checks_resolve_seq_and_are_idempotent(tmp_path):
    digest = setup(tmp_path)
    checks = [{"page": "wiki/gazdasag/szukosseg.md", "image": 1, "locator": "2. feladat",
               "observed": "A táblázat három sora.", "decision": "changed", "note": "pótolva"},
              {"page": "wiki/gazdasag/szukosseg.md", "image": "wiki/assets/abra.svg",
               "locator": "ábra", "observed": "Nyíl balra.", "decision": "confirmed"}]
    kw = dict(run_id="run-1", checker="astra/high", at="2026-10-03T10:00:00+02:00",
              fetch_pages=PAGES)
    written = records.append(tmp_path, records.from_writer(checks), **kw)
    assert written == ["docs/evidence/pages/gazdasag/szukosseg.md"]
    text = (tmp_path / written[0]).read_text(encoding="utf-8")
    assert text.startswith("# Bizonyítékrekord: wiki/gazdasag/szukosseg.md\n\n## 2026-10-03")
    assert f"`sources/gazdasag/ora-1/p0001.jpg` (sha256 `{digest}`)" in text
    assert "Forrás: Óra 1 / füzet.pdf, 2. oldal" in text and "Megjegyzés: pótolva" in text
    records.append(tmp_path, records.from_writer(checks), **kw)          # same run again
    assert (tmp_path / written[0]).read_text(encoding="utf-8") == text
    records.append(tmp_path, records.from_writer(checks[:1]), **{**kw, "run_id": "run-2"})
    assert (tmp_path / written[0]).read_text(encoding="utf-8").startswith(text)


def test_rerun_replaces_only_its_own_kind(tmp_path):
    setup(tmp_path)
    page = "wiki/gazdasag/szukosseg.md"
    kw = dict(run_id="run-1", checker="astra/high", at="T", fetch_pages=PAGES)
    image = [{"page": page, "image": "wiki/assets/abra.svg", "locator": "kép",
              "observed": "Kép.", "decision": "confirmed"}]
    records.append(tmp_path, records.from_writer(image), kind="image:abra", **kw)
    first = [{"page": page, "image": 1, "locator": "1", "observed": "Első.", "decision": "changed"}]
    records.append(tmp_path, records.from_writer(first), **kw)
    second = [{**first[0], "observed": "Javított."}]
    out = records.append(tmp_path, records.from_writer(second), **kw)
    text = (tmp_path / out[0]).read_text(encoding="utf-8")
    assert "Javított." in text and "Első." not in text and "Kép." in text
    assert text.count("– run-1 – astra/high – checks") == 1


def test_only_committed_image_locations(tmp_path):
    setup(tmp_path)
    bad = [{"page": "wiki/gazdasag/szukosseg.md", "image": ".school-notes/images/x.png",
            "locator": "x", "observed": "o", "decision": "confirmed"}]
    (tmp_path / ".school-notes/images").mkdir(parents=True)
    (tmp_path / ".school-notes/images/x.png").write_bytes(b"x")
    with pytest.raises(records.RecordError):
        records.append(tmp_path, records.from_writer(bad), run_id="r", checker="c", at="T")


@pytest.mark.parametrize("image", ["../outside.jpg", "/etc/passwd", "wiki/assets/nincs.png", 7])
def test_bad_images_are_refused(tmp_path, image):
    setup(tmp_path)
    entry = records.Entry("wiki/a/b.md", image, "x", "y", "confirmed")
    with pytest.raises(records.RecordError):
        records.append(tmp_path, [entry], run_id="r", checker="c", at="t", fetch_pages=PAGES)
