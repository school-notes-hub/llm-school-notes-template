import io

import pytest
from PIL import Image

from school_notes2.drive.client import DriveClient
from school_notes2.local import fetch
from school_notes2.state.errors import NeedsOwner, Transient
from tests.drive.fakedrive import FakeDrive
from tests.local.conftest import git, init_repo


def jpeg(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def world(tmp_path, fake_local):
    drive = FakeDrive()
    root = drive.folder("Barna")
    subject = drive.folder("Matek", drive.folder("Füzet", root))
    ready = drive.folder("Feltöltés_Kész", subject)
    done = drive.folder("Feldolgozva", subject)
    pkg = drive.folder("2026-10-07", ready)
    drive.file("b.jpg", pkg, jpeg("red"))
    drive.file("a.jpg", pkg, jpeg("blue"))
    repo = init_repo(tmp_path / "repo")
    local = fake_local(repo, drive=DriveClient(drive), drive_root=root)
    return {"drive": drive, "local": local, "repo": repo, "pkg": pkg, "done": done, "ready": ready}


def folders(repo):
    base = repo / "sources" / "matek"
    return sorted(p.name for p in base.iterdir()) if base.is_dir() else []


def test_list_only_touches_nothing(world):
    lines = []
    assert fetch.run(world["local"], apply=False, out=lines.append) == 0
    assert lines[0] == "barna: 1 csomag a Feltöltés_Kész mappákban"
    assert "fuzet/Matek/2026-10-07 (2 fájl;" in lines[1]
    assert not world["drive"].patches and not (world["repo"] / "sources").exists()
    assert not world["local"].downloads().exists()


def test_apply_places_then_moves_then_deletes_the_download(world, monkeypatch):
    order = []
    real_place, real_move = fetch.place_package, fetch.move_to_processed
    monkeypatch.setattr(fetch, "place_package", lambda *a, **k: order.append("place") or real_place(*a, **k))
    monkeypatch.setattr(fetch, "move_to_processed", lambda *a, **k: order.append("move") or real_move(*a, **k))
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    assert order == ["place", "move"]
    assert folders(world["repo"]) == ["2026-10-07"]
    assert sorted(p.name for p in (world["repo"] / "sources/matek/2026-10-07").iterdir()) == ["a.jpg", "b.jpg"]
    assert (world["repo"] / "wiki/matek/index.md").is_file()        # new subject skeleton
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]]
    assert not (world["local"].downloads() / world["pkg"]).exists()


def test_interrupted_before_the_move_resumes_with_the_move_only(world, monkeypatch):
    def broken(*a, **k):
        raise Transient("network down")
    monkeypatch.setattr(fetch, "move_to_processed", broken)
    with pytest.raises(Transient):
        fetch.run(world["local"], apply=True, out=lambda *_: None)
    folder = world["local"].downloads() / world["pkg"]
    assert fetch.stage(folder) == "placed" and folders(world["repo"]) == ["2026-10-07"]
    monkeypatch.undo()
    calls = []
    real = fetch.place_package
    monkeypatch.setattr(fetch, "place_package", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    assert calls == [] and folders(world["repo"]) == ["2026-10-07"]
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]] and not folder.exists()


def test_moved_but_download_left_behind_is_finished_from_the_leftover(world, monkeypatch):
    real = fetch.move_to_processed

    def lost_answer(*a, **k):
        real(*a, **k)
        raise Transient("answer lost")
    monkeypatch.setattr(fetch, "move_to_processed", lost_answer)
    with pytest.raises(Transient):
        fetch.run(world["local"], apply=True, out=lambda *_: None)
    monkeypatch.undo()
    lines = []
    assert fetch.run(world["local"], apply=False, out=lines.append) == 0
    assert lines[0].startswith("barna: 0 csomag") and "(placed)" in lines[1]
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    assert not world["local"].downloads().joinpath(world["pkg"]).exists()
    assert folders(world["repo"]) == ["2026-10-07"]


def test_placement_cut_off_halfway_is_replaced_once(world, monkeypatch):
    def half(repo, pkg, seq, known, settings):
        target = repo / "sources/matek/2026-10-07"
        target.mkdir(parents=True)
        (target / "a.jpg").write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(fetch, "place_package", half)
    with pytest.raises(OSError):
        fetch.run(world["local"], apply=True, out=lambda *_: None)
    assert fetch.stage(world["local"].downloads() / world["pkg"]) == "placing"
    monkeypatch.undo()
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    assert folders(world["repo"]) == ["2026-10-07"]
    assert (world["repo"] / "sources/matek/2026-10-07/a.jpg").read_bytes() != b"partial"


def test_a_cut_off_placement_already_in_git_is_left_to_the_owner(world, monkeypatch):
    def half(repo, pkg, seq, known, settings):
        target = repo / "sources/matek/2026-10-07"
        target.mkdir(parents=True)
        (target / "a.jpg").write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(fetch, "place_package", half)
    with pytest.raises(OSError):
        fetch.run(world["local"], apply=True, out=lambda *_: None)
    monkeypatch.undo()
    git(world["repo"], "add", "-A")
    git(world["repo"], "commit", "-q", "-m", "someone committed it")
    with pytest.raises(NeedsOwner):
        fetch.run(world["local"], apply=True, out=lambda *_: None)
    assert (world["repo"] / "sources/matek/2026-10-07/a.jpg").read_bytes() == b"partial"


def test_changed_on_drive_after_download_is_not_moved_and_redone_next_time(world, monkeypatch):
    monkeypatch.setattr(fetch, "move_to_processed", lambda *a, **k: "changed")
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 1
    assert any(line.startswith("NEM KÉSZ") for line in lines)
    assert world["drive"].items[world["pkg"]]["parents"] == [world["ready"]]
    folder = world["local"].downloads() / world["pkg"]
    assert fetch.stage(folder) == "downloading"
    monkeypatch.undo()
    world["drive"].file("c.jpg", world["pkg"], jpeg("green"))
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    assert folders(world["repo"]) == ["2026-10-07"]
    assert sorted(p.name for p in (world["repo"] / "sources/matek/2026-10-07").iterdir()) == ["a.jpg", "b.jpg", "c.jpg"]


def test_nested_doc_extract_package_is_unwrapped(world):
    drive = world["drive"]
    pkg = drive.folder("2026-10-08-dia", world["ready"])
    inner = drive.folder("dia-extract", pkg)
    drive.file("document.md", inner, b"# Dia\n\nSzoveg.\n", mime="text/markdown")
    drive.file("manifest.json", inner, b"{}", mime="application/json")
    assert fetch.run(world["local"], apply=True, out=lambda *_: None) == 0
    placed = world["repo"] / "sources/matek/2026-10-08-dia"
    assert sorted(p.name for p in placed.iterdir()) == ["document.md", "manifest.json"]
    assert drive.items[pkg]["parents"] == [world["done"]]


def test_list_order_is_content_derived_and_repeatable(world):
    drive = world["drive"]
    drive.folder("2026-10-01", world["ready"], minutes_ago=1)
    drive.file("x.jpg", drive.folder("2026-09-30", world["ready"], minutes_ago=999), jpeg("red"))
    runs = []
    for _ in range(2):
        lines = []
        fetch.run(world["local"], apply=False, out=lines.append)
        runs.append(lines)
    assert runs[0] == runs[1]
    labels = [line.split(" (")[0].strip() for line in runs[0][1:] if line.startswith("  fuzet")]
    assert labels == sorted(labels)
