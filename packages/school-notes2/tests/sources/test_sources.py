import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from school_notes2.schemas import validate
from school_notes2.sources.batch import select_batch, split_ranges
from school_notes2.sources.duplicates import Known, known_hashes, original_key
from school_notes2.sources.naming import slug, subject_key, unique_dir
from school_notes2.sources.order import ordered
from school_notes2.sources.place import Downloaded, place_package
from school_notes2.sources.toolload import DEFAULT_TOOLS_DIR

# The owner's checkout of Benedek's repo, next to the template (read-only use).
ACTIVE = next((p / "school-notes-benedek-active" for p in Path(__file__).resolve().parents
               if (p / "school-notes-benedek-active").is_dir()), Path("/nonexistent"))


def photo(path: Path, size=(4000, 3000), color=(200, 120, 40), exif=True) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    for x in range(0, size[0], 97):            # some structure, so JPEG sizes differ
        im.putpixel((x, x % size[1]), (0, 0, 0))
    kwargs = {}
    if exif:
        data = Image.Exif()
        data[0x0112] = 6                       # rotated 90° on the phone
        data[0x010F] = "PhoneMaker"
        kwargs["exif"] = data
    im.save(path, "JPEG", quality=95, **kwargs)
    return record(path, path.name)


def record(path: Path, rel: str) -> dict:
    return {"rel": rel, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def pdf(path: Path, pages: int) -> dict:
    images = [Image.new("RGB", (595, 842), (255, 255 - i * 5, 255)) for i in range(pages)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=72)
    return record(path, path.name)


def package(files, name="Óra 1", subject="matek", preconverted=False):
    return Downloaded(drive_folder=name, subject=subject, role="fuzet", description="",
                      new_subject=False, preconverted=preconverted, files=files)


def test_natural_order_with_subfolders():
    assert ordered(["10.jpg", "2.jpg", "b/1.jpg", "B.jpg", "a/10.jpg", "a/9.jpg"]) == \
        ["2.jpg", "10.jpg", "a/9.jpg", "a/10.jpg", "b/1.jpg", "B.jpg"]


def test_photo_is_downscaled_upright_and_clean(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    placed = place_package(repo, package([photo(tmp_path / "dl" / "IMG 1.JPG")]), 1, Known())
    stored = repo / placed.pages[0]["path"]
    assert placed.pages[0]["path"] == "sources/matek/ora-1/img-1.jpg"
    with Image.open(stored) as im:
        assert im.format == "JPEG" and max(im.size) == 2000
        assert im.size == (1500, 2000)                  # EXIF orientation applied
        assert not im.getexif() and "icc_profile" not in im.info


def test_small_photo_is_not_enlarged(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    placed = place_package(repo, package([photo(tmp_path / "s.jpg", (800, 600), exif=False)]),
                           1, Known())
    with Image.open(repo / placed.pages[0]["path"]) as im:
        assert im.size == (800, 600)


def test_pdf_becomes_numbered_pages_without_the_pdf(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    placed = place_package(repo, package([pdf(tmp_path / "fuzet.pdf", 24)]), 5, Known())
    names = sorted(p.name for p in (repo / "sources/matek/ora-1").iterdir())
    assert names == [f"p{i:04d}.jpg" for i in range(1, 25)]
    assert [p["seq"] for p in placed.pages] == list(range(5, 29))
    assert [p["page"] for p in placed.pages] == list(range(1, 25))
    assert not list(repo.rglob("*.pdf"))
    assert placed.package["files"] == [{"file": "fuzet.pdf", "original_sha256":
                                        placed.pages[0]["original_sha256"], "pages": 24}]


def test_mixed_package_order_and_names(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    files = [photo(tmp_path / "10.jpg", (100, 80), exif=False),
             pdf(tmp_path / "3.pdf", 2),
             photo(tmp_path / "2.jpg", (100, 80), color=(1, 2, 3), exif=False)]
    placed = place_package(repo, package(files), 1, Known())
    assert [(p["file"], p["page"], p["path"].rsplit("/", 1)[1]) for p in placed.pages] == [
        ("2.jpg", None, "2.jpg"), ("3.pdf", 1, "p0002.jpg"), ("3.pdf", 2, "p0003.jpg"),
        ("10.jpg", None, "10.jpg")]


def test_duplicates_by_content_and_by_original(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    known = Known()
    first = place_package(repo, package([photo(tmp_path / "1.jpg", (300, 200), exif=False)]), 1, known)
    again = place_package(repo, package([photo(tmp_path / "x" / "1.jpg", (300, 200), exif=False)],
                                        name="Újra"), 2, known)
    assert again.pages[0]["duplicate_of"] == first.pages[0]["path"]
    assert again.written == [] and not (repo / "sources/matek/ujra").exists()
    # Rule 1: the same uploaded original counts even when the stored bytes would differ.
    other = photo(tmp_path / "y" / "2.jpg", (300, 200), color=(9, 9, 9), exif=False)
    by_original = Known(original={original_key(other["sha256"], None): "wiki/matek/old.md"})
    placed = place_package(repo, package([other], name="Harmadik"), 3, by_original)
    assert placed.pages[0]["duplicate_of"] == "wiki/matek/old.md"


def test_known_hashes_read_v1_maps_and_v2_keys(tmp_path):
    page = tmp_path / "wiki" / "matek" / "2026-09-25-ora-jegyzet.md"
    page.parent.mkdir(parents=True)
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    page.write_text(f"---\ntype: lesson-notes\ncontent_sha256:\n  01.jpg: {a}\n"
                    f"original_sha256:\n  p0001.jpg: {b}#p1\n  02.jpg: {c}\n---\n# x\n")
    known = known_hashes(tmp_path)
    assert known.content == {a: "wiki/matek/2026-09-25-ora-jegyzet.md"}
    assert set(known.original) == {f"{b}#p1", c}


@pytest.mark.skipif(not ACTIVE.is_dir(), reason="active learner repo not checked out")
def test_known_hashes_on_the_real_wiki(tmp_path):
    shutil.copytree(ACTIVE / "wiki", tmp_path / "wiki")
    assert len(known_hashes(tmp_path).content) > 20


def test_preconverted_package_is_one_item(tmp_path):
    repo, src = tmp_path / "repo", tmp_path / "dl"
    repo.mkdir()
    src.mkdir()
    (src / "document.md").write_text("# Dia\n")
    (src / "dia.pptx").write_bytes(b"PK-pptx")
    (src / "media").mkdir()
    (src / "media" / "k1.png").write_bytes(b"png")
    files = [record(src / "document.md", "document.md"), record(src / "dia.pptx", "dia.pptx"),
             record(src / "media" / "k1.png", "media/k1.png")]
    placed = place_package(repo, package(files, name="Tanári dia", preconverted=True), 7, Known())
    assert placed.pages == [{"seq": 7, "package": "Tanári dia", "file": "document.md", "page": None,
                             "path": "sources/matek/tanari-dia/document.md",
                             "sha256": hashlib.sha256(b"# Dia\n").hexdigest(),
                             "original_sha256": files[1]["sha256"], "duplicate_of": None}]
    assert (repo / "sources/matek/tanari-dia/media/k1.png").read_bytes() == b"png"


def test_fetch_entries_validate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    placed = place_package(repo, package([photo(tmp_path / "1.jpg", (100, 80), exif=False)]), 1, Known())
    validate("fetch", {"student": "benedek", "learner": {"grade": 9}, "run_id": "r1", "mode": "cron",
                       "packages": [placed.package], "pages": placed.pages,
                       "range": {"from": 1, "to": 1, "k": 1, "n": 1},
                       "open_review_items": [], "pending_images": []})


def _pkg(name, pages, pre=False):
    return SimpleNamespace(name=name, pages=pages, preconverted=pre)


def test_batching_rules():
    counted = []

    def count(p):
        counted.append(p.name)
        return p.pages

    three = [_pkg("a", 10), _pkg("b", 10), _pkg("c", 5)]
    selected, dropped = select_batch(three, count)
    assert [p.name for p, _ in selected] == ["a", "b", "c"] and dropped == []
    selected, dropped = select_batch([_pkg("a", 20), _pkg("b", 20)], count)
    assert [p.name for p, _ in selected] == ["a"] and [p.name for p in dropped] == ["b"]
    selected, _ = select_batch([_pkg("big", 75), _pkg("b", 1)], count)
    assert [(p.name, n) for p, n in selected] == [("big", 75)]
    selected, dropped = select_batch([_pkg("a", 3), _pkg("doc", 1, pre=True)], count)
    assert [p.name for p, _ in selected] == ["a"] and dropped == []
    assert "doc" not in counted                       # not downloaded when it cannot join
    selected, _ = select_batch([_pkg("doc", 1, pre=True), _pkg("a", 3)], count)
    assert [p.name for p, _ in selected] == ["doc"]
    assert split_ranges(75) == [(1, 30), (31, 60), (61, 75)]
    assert split_ranges(30) == [(1, 30)]


def test_naming(tmp_path):
    assert slug("Szeptember 30. – óra") == "szeptember-30-ora"
    (tmp_path / "ora").mkdir()
    assert unique_dir(tmp_path, "ora").name == "ora-2"
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/subjects.json").write_text(
        '{"subjects": {"gazdasag": {"name": "Gazdasági és jogi alapismeretek"}}}')
    assert subject_key("gazdasági és jogi  alapismeretek", tmp_path) == ("gazdasag", True)
    (tmp_path / "wiki/gazdasag").mkdir(parents=True)
    (tmp_path / "wiki/gazdasag/index.md").write_text("# Gazdaság\n")
    assert subject_key("gazdasági és jogi  alapismeretek", tmp_path) == ("gazdasag", False)
    assert subject_key("Fizika", tmp_path) == ("fizika", True)


def test_prepare_photo_cli_keeps_working(tmp_path):
    src = tmp_path / "in.jpg"
    photo(src, (3000, 1000), exif=False)
    plain = subprocess.run([sys.executable, str(DEFAULT_TOOLS_DIR / "prepare_photo.py"),
                            str(src), str(tmp_path / "a.jpg")], capture_output=True, text=True)
    assert plain.returncode == 0, plain.stderr
    with Image.open(tmp_path / "a.jpg") as im:
        assert im.size == (3000, 1000)               # default: same resolution as before
    small = subprocess.run([sys.executable, str(DEFAULT_TOOLS_DIR / "prepare_photo.py"),
                            "--max-side", "1000", "--quality", "85", str(src), str(tmp_path / "b.jpg")])
    assert small.returncode == 0
    with Image.open(tmp_path / "b.jpg") as im:
        assert im.size == (1000, 333)
