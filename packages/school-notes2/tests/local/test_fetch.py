import io

import pytest
from PIL import Image

from school_notes2.drive.client import DriveClient
from school_notes2.local import fetch
from school_notes2.state.errors import Transient
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
    return {"drive": drive, "local": local, "repo": repo, "pkg": pkg, "done": done, "ready": ready,
            "root": root}


def folders(repo):
    base = repo / "sources" / "matek"
    return sorted(p.name for p in base.iterdir()) if base.is_dir() else []


def names(repo, folder="2026-10-07"):
    """The stored source files (the manifest `sn-fetch.json` left out)."""
    return sorted(p.name for p in (repo / "sources/matek" / folder).iterdir() if p.name != "sn-fetch.json")


def quiet(*a):
    pass


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
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert order == ["place", "move"]
    assert folders(world["repo"]) == ["2026-10-07"] and names(world["repo"]) == ["a.jpg", "b.jpg"]
    assert (world["repo"] / "wiki/matek/index.md").is_file()        # new subject skeleton
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]]
    assert not (world["local"].downloads() / world["pkg"]).exists()
    assert not (world["repo"] / ".school-notes/fetch" / world["pkg"]).exists()


def test_interrupted_before_the_move_resumes_with_the_move_only(world, monkeypatch):
    def broken(*a, **k):
        raise Transient("network down")
    monkeypatch.setattr(fetch, "move_to_processed", broken)
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    folder = world["local"].downloads() / world["pkg"]
    assert fetch.stage(folder) == "placed" and folders(world["repo"]) == ["2026-10-07"]
    monkeypatch.undo()
    calls = []
    real = fetch.place_package
    monkeypatch.setattr(fetch, "place_package", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert calls == [] and folders(world["repo"]) == ["2026-10-07"]
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]] and not folder.exists()


@pytest.mark.parametrize("where", ["move", "place"])
def test_package_changed_on_drive_during_an_interruption_is_never_moved_unplaced(world, monkeypatch, where):
    """The resumed move is checked against the download's listing (real move_to_processed)."""
    def broken(*a, **k):
        raise Transient("network down")
    monkeypatch.setattr(fetch, "move_to_processed" if where == "move" else "place_package", broken)
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    monkeypatch.undo()
    world["drive"].file("c.jpg", world["pkg"], jpeg("green"))     # the owner adds a page meanwhile
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert names(world["repo"]) == ["a.jpg", "b.jpg", "c.jpg"] and folders(world["repo"]) == ["2026-10-07"]
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]]


def test_changed_between_listing_and_move_is_not_moved(world, monkeypatch):
    real = fetch.download_package

    def download_then_change(drive, pkg, dest, timeout):
        files = real(drive, pkg, dest, timeout)
        world["drive"].file("c.jpg", world["pkg"], jpeg("green"))
        return files
    monkeypatch.setattr(fetch, "download_package", download_then_change)
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 1
    assert world["drive"].items[world["pkg"]]["parents"] == [world["ready"]]
    monkeypatch.undo()
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert names(world["repo"]) == ["a.jpg", "b.jpg", "c.jpg"]
    assert world["drive"].items[world["pkg"]]["parents"] == [world["done"]]


def test_moved_but_download_left_behind_is_finished_from_the_leftover(world, monkeypatch):
    real = fetch.move_to_processed

    def lost_answer(*a, **k):
        real(*a, **k)
        raise Transient("answer lost")
    monkeypatch.setattr(fetch, "move_to_processed", lost_answer)
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    monkeypatch.undo()
    lines = []
    assert fetch.run(world["local"], apply=False, out=lines.append) == 0
    assert lines[0].startswith("barna: 0 csomag") and "(placed)" in lines[1]
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert not world["local"].downloads().joinpath(world["pkg"]).exists()
    assert folders(world["repo"]) == ["2026-10-07"]


def test_preparation_cut_off_halfway_is_redone_once(world, monkeypatch):
    def half(repo, pkg, seq, known, settings, folder):
        folder.mkdir(parents=True)
        (folder / "a.jpg").write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(fetch, "place_package", half)
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    assert fetch.stage(world["local"].downloads() / world["pkg"]) == "placing"
    assert names(world["repo"]) == []                       # only the empty reservation in the repo
    monkeypatch.undo()
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert folders(world["repo"]) == ["2026-10-07"] and names(world["repo"]) == ["a.jpg", "b.jpg"]
    assert (world["repo"] / "sources/matek/2026-10-07/a.jpg").read_bytes() != b"partial"


@pytest.mark.parametrize("change", ["foreign-file", "edited-file", "committed"])
def test_a_placement_with_work_it_did_not_write_is_left_to_the_owner(world, monkeypatch, change):
    real = fetch.move_to_processed
    monkeypatch.setattr(fetch, "move_to_processed", lambda *a, **k: (_ for _ in ()).throw(Transient("down")))
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    monkeypatch.setattr(fetch, "move_to_processed", real)
    target = world["repo"] / "sources/matek/2026-10-07"
    if change == "foreign-file":
        (target / "javitas.md").write_text("finished work")
    elif change == "edited-file":
        (target / "a.jpg").write_bytes(b"retouched by hand")
    else:
        git(world["repo"], "add", "-A")
        git(world["repo"], "commit", "-q", "-m", "someone committed it")
    world["drive"].file("c.jpg", world["pkg"], jpeg("green"))     # forces a new placement
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 1
    assert any("NeedsOwner" in line for line in lines)
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
    assert world["drive"].items[world["pkg"]]["parents"] == [world["ready"]]


def test_two_packages_with_the_same_name_never_share_or_delete_a_folder(world, monkeypatch):
    drive = world["drive"]
    teacher = drive.folder("Matek", drive.folder("Tanári-tanulni", world["root"]))
    t_ready = drive.folder("Feltöltés_Kész", teacher)
    drive.folder("Feldolgozva", teacher)
    second = drive.folder("2026-10-07", t_ready)
    drive.file("t.jpg", second, jpeg("white"))
    real = fetch.place_package
    calls = []

    def first_fails(repo, pkg, *a, **k):
        calls.append(pkg.role)
        if pkg.role == "fuzet" and calls.count("fuzet") == 1:
            raise OSError("killed")
        return real(repo, pkg, *a, **k)
    monkeypatch.setattr(fetch, "place_package", first_fails)
    assert fetch.run(world["local"], apply=True, out=quiet) == 1
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert folders(world["repo"]) == ["2026-10-07", "2026-10-07-2"]
    contents = sorted(names(world["repo"], f) for f in folders(world["repo"]))
    assert contents == [["a.jpg", "b.jpg"], ["t.jpg"]]


def test_one_package_failing_does_not_stop_the_others(world, monkeypatch):
    drive = world["drive"]
    other = drive.folder("2026-10-08", world["ready"])
    drive.file("x.jpg", other, jpeg("white"))
    real = fetch.place_package

    def fails_for_first(repo, pkg, *a, **k):
        if pkg.drive_folder == "2026-10-07":
            raise OSError("broken file")
        return real(repo, pkg, *a, **k)
    monkeypatch.setattr(fetch, "place_package", fails_for_first)
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 1
    assert drive.items[other]["parents"] == [world["done"]]
    assert any(line.startswith(f"NEM KÉSZ: {world['pkg']}") for line in lines)


def test_an_older_scripts_download_is_adopted_only_when_it_is_exactly_this_package(world):
    folder = world["local"].downloads() / world["pkg"]
    folder.mkdir(parents=True)
    drive = world["drive"]
    for fid, meta in drive.items.items():
        if meta["parents"] == [world["pkg"]]:
            (folder / meta["name"]).write_bytes(drive.content[fid])
    assert fetch.stage(folder) == "unknown"
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert names(world["repo"]) == ["a.jpg", "b.jpg"]


def test_an_unknown_folder_that_is_not_this_package_is_left_alone(world):
    folder = world["local"].downloads() / world["pkg"]
    folder.mkdir(parents=True)
    (folder / "a.jpg").write_bytes(b"something else")
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 1
    assert (folder / "a.jpg").read_bytes() == b"something else"
    assert world["drive"].items[world["pkg"]]["parents"] == [world["ready"]]


def test_nested_doc_extract_package_is_unwrapped(world):
    drive = world["drive"]
    pkg = drive.folder("2026-10-08-dia", world["ready"])
    inner = drive.folder("dia-extract", pkg)
    drive.file("document.md", inner, b"# Dia\n\nSzoveg.\n", mime="text/markdown")
    drive.file("manifest.json", inner, b"{}", mime="application/json")
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    assert names(world["repo"], "2026-10-08-dia") == ["document.md", "manifest.json"]
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


def test_ignored_files_are_listed_by_path_not_upload_time(world):
    drive = world["drive"]
    for name, age in (("b-pkg", 500), ("a-pkg", 5)):          # upload order: b before a
        folder = drive.folder(name, world["ready"], minutes_ago=age)
        drive.file("p.jpg", folder, jpeg("red"), created_ago=age)
        drive.file("notes.txt", folder, b"x", created_ago=age, mime="text/plain")
    lines = []
    fetch.run(world["local"], apply=False, out=lines.append)
    ignored = [line for line in lines if "kihagyva" in line]
    assert ignored == sorted(ignored) and len(ignored) == 2


def test_the_placed_folder_keeps_a_source_manifest_and_a_new_subject_its_entry(world):
    import json
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    repo = world["repo"]
    data = json.loads((repo / "sources/matek/2026-10-07/sn-fetch.json").read_text())
    assert data["package"]["drive_folder"] == "2026-10-07" and data["package"]["role"] == "fuzet"
    assert [p["file"] for p in data["pages"]] == ["a.jpg", "b.jpg"]
    assert all(p["drive_id"] and len(p["content_sha256"]) == 64 for p in data["pages"])
    assert sorted(data["written"]) == ["sources/matek/2026-10-07/a.jpg", "sources/matek/2026-10-07/b.jpg"]
    subjects = json.loads((repo / "tools/subjects.json").read_text())["subjects"]
    assert subjects["matek"] == {"name": "Matek"}                      # D10; emoji/colour from the report


def test_a_reuploaded_page_is_reported_and_not_placed_twice(world):
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    again = world["drive"].folder("2026-10-08", world["ready"])
    world["drive"].file("ujra.jpg", again, jpeg("red"))                  # the same photo as b.jpg
    world["drive"].file("uj.jpg", again, jpeg("green"))
    lines = []
    assert fetch.run(world["local"], apply=True, out=lines.append) == 0
    assert names(world["repo"], "2026-10-08") == ["uj.jpg"]
    assert any(line.startswith("  már ismert, nem tároltam újra: ujra.jpg = sources/matek/2026-10-07/") for line in lines)
