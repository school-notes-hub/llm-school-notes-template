import io
import json
import urllib.error

import pytest

from school_notes2.drive import client as client_mod
from school_notes2.drive.download import download_package
from school_notes2.drive.inventory import scan
from school_notes2.drive.move import move_to_processed
from school_notes2.sources.toolload import load_tool
from school_notes2.state.errors import NeedsOwner, Prerequisite, Transient



def test_every_package_is_ready_at_once_in_content_order(fake, client, tree):
    """Feltöltés_Kész is filled by renaming: a just-uploaded package is complete (no settle time)."""
    fresh = fake.folder("Okt 3", tree["ready"])
    fake.file("1.jpg", fresh, created_ago=0, modified_ago=60 * 24 * 30)
    old = fake.folder("Szept 30", tree["ready"])
    fake.file("1.jpg", old, created_ago=60 * 24)
    assert [p.name for p in scan(client, tree["root"]).ready] == ["Okt 3", "Szept 30"]


def test_loose_office_and_unknown_files_are_ignored(fake, client, tree):
    fake.file("laza.jpg", tree["ready"])
    pkg = fake.folder("Óra", tree["ready"])
    fake.file("2.jpg", pkg)
    fake.file("dia.pptx", pkg, mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    fake.file("jegyzet.txt", pkg, mime="text/plain")
    only_office = fake.folder("Tanári", tree["ready"])
    fake.file("anyag.docx", only_office, mime="application/msword")
    inv = scan(client, tree["root"])
    assert [p.name for p in inv.ready] == ["Óra"]
    assert [f.rel for f in inv.ready[0].files] == ["2.jpg"]
    reasons = {i["path"]: i["reason"] for i in inv.skipped()}
    assert "loose file" in reasons["fuzet/Matek/Feltöltés_Kész/laza.jpg"]
    assert "doc-extract" in reasons["fuzet/Matek/Óra/dia.pptx"]
    assert reasons["fuzet/Matek/Óra/jegyzet.txt"] == "unsupported format"
    assert reasons["fuzet/Matek/Feltöltés_Kész/Tanári"] == "no usable file"


def test_subfolders_and_paging(fake, client, tree):
    pkg = fake.folder("Nagy", tree["ready"])
    sub = fake.folder("második nap", pkg)
    for name in ("1.jpg", "2.jpg", "3.jpg"):
        fake.file(name, pkg)
    fake.file("1.jpg", sub)
    inv = scan(client, tree["root"])
    assert sorted(f.rel for f in inv.ready[0].files) == ["1.jpg", "2.jpg", "3.jpg", "második nap/1.jpg"]


def test_download_verifies_md5(fake, client, tree, tmp_path):
    pkg = fake.folder("Óra", tree["ready"])
    fid = fake.file("1.jpg", pkg, data=b"photo")
    package = scan(client, tree["root"]).ready[0]
    records = download_package(client, package, tmp_path / "dl")
    assert (tmp_path / "dl" / "1.jpg").read_bytes() == b"photo" and records[0]["sha256"]
    fake.content[fid] = b"other"        # Drive metadata no longer matches the bytes
    with pytest.raises(Transient):
        download_package(client, package, tmp_path / "dl2")
    assert not list((tmp_path / "dl2").rglob("1.jpg*"))   # neither the file nor a .part stays


def _ready_package(fake, client, tree):
    pkg = fake.folder("Óra", tree["ready"])
    fake.file("1.jpg", pkg, data=b"one")
    return pkg, scan(client, tree["root"]).ready[0]


def test_move_after_unchanged_relist(fake, client, tree):
    pkg_id, package = _ready_package(fake, client, tree)
    assert move_to_processed(client, pkg_id, package.listed, tree["root"]) == "moved"
    assert fake.items[pkg_id]["parents"] == [tree["done"]]
    assert move_to_processed(client, pkg_id, package.listed, tree["root"]) == "already"


@pytest.mark.parametrize("change", ["new_file", "content"])
def test_changed_package_is_not_moved(fake, client, tree, change):
    pkg_id, package = _ready_package(fake, client, tree)
    if change == "new_file":
        fake.file("2.jpg", pkg_id)
    else:
        fid = next(i for i, m in fake.items.items() if m["name"] == "1.jpg")
        fake.items[fid]["md5Checksum"] = "0" * 32
    assert move_to_processed(client, pkg_id, package.listed, tree["root"]) == "changed"
    assert fake.patches == []


def test_foreign_root_is_not_moved(fake, client, tree):
    pkg_id, package = _ready_package(fake, client, tree)
    other_root = fake.folder("Barna")
    with pytest.raises(NeedsOwner):
        move_to_processed(client, pkg_id, package.listed, other_root)
    assert fake.patches == []


def test_lost_patch_answer_is_resolved_by_rereading(fake, client, tree):
    pkg_id, package = _ready_package(fake, client, tree)
    fake.lose_patch_answer = True
    assert move_to_processed(client, pkg_id, package.listed, tree["root"]) == "moved"
    assert fake.patches == [pkg_id]


class _Opener:
    def __init__(self, answer):
        self.answer = answer

    def open(self, req, timeout):
        if isinstance(self.answer, Exception):
            raise self.answer
        return io.BytesIO(json.dumps(self.answer).encode())


def _token(tmp_path, scope):
    path = tmp_path / "drive-token.json"
    path.write_text(json.dumps({"scopes": [scope], "client_id": "c", "client_secret": "s",
                                "refresh_token": "r"}))
    path.chmod(0o600)


def _transport(tmp_path, monkeypatch, answer):
    dm = load_tool("drive_media")
    monkeypatch.setattr(dm.urllib.request, "build_opener", lambda *a: _Opener(answer))
    return client_mod.DriveMediaTransport(tmp_path, timeout_s=30)


def test_full_scope_token_is_accepted(tmp_path, monkeypatch):
    _token(tmp_path, client_mod.FULL_SCOPE)
    t = _transport(tmp_path, monkeypatch, {"access_token": "a", "expires_in": 3600,
                                           "scope": client_mod.FULL_SCOPE})
    assert t.drive.token == "a" and t.drive.timeout == 30


def test_drive_file_token_is_a_missing_prerequisite(tmp_path, monkeypatch):
    _token(tmp_path, "https://www.googleapis.com/auth/drive.file")
    with pytest.raises(Prerequisite):
        _transport(tmp_path, monkeypatch, {})


def test_invalid_grant_is_a_missing_prerequisite(tmp_path, monkeypatch):
    _token(tmp_path, client_mod.FULL_SCOPE)
    error = urllib.error.HTTPError("https://oauth2.googleapis.com/token", 400, "Bad", {}, None)
    with pytest.raises(Prerequisite):
        _transport(tmp_path, monkeypatch, error)


@pytest.mark.parametrize("status,cls", [(429, Transient), (503, Transient), (404, NeedsOwner),
                                        (401, Prerequisite)])
def test_http_status_classes(status, cls):
    assert isinstance(client_mod._mapped(status), cls)


def test_changed_or_missing_file_is_file_changed(client, fake, tree, tmp_path):
    from school_notes2.drive.client import DriveClient, FileChanged
    pkg = fake.folder("Csomag", tree["ready"])
    fid = fake.file("1.jpg", pkg, b"abc")
    item = dict(fake.items[fid])
    fake.content[fid] = b"rotated"                      # replaced after the listing
    with pytest.raises(FileChanged):
        client.download(item, tmp_path / "1.jpg")

    class Gone:
        def stream(self, url, timeout):
            raise NeedsOwner("Drive HTTP 404")
    with pytest.raises(FileChanged):
        DriveClient(Gone()).download(item, tmp_path / "2.jpg")


def test_package_deadline_bounds_the_whole_download(client, fake, tree, tmp_path):
    import time as _time
    pkg = fake.folder("Csomag", tree["ready"])
    fid = fake.file("1.jpg", pkg, b"abc")
    with pytest.raises(Transient, match="out of time"):
        client.download(dict(fake.items[fid]), tmp_path / "1.jpg", _time.monotonic() - 1)


def test_package_with_two_same_named_files_is_not_taken(fake, client, tree):
    from school_notes2.drive import inventory
    pkg = fake.folder("Óra", tree["ready"], minutes_ago=60)
    fake.file("1.jpg", pkg, b"a")
    fake.file("1.jpg", pkg, b"b")
    inv = inventory.scan(client, tree["root"])
    assert not inv.ready
    assert any("same name" in i["reason"] for i in inv.skipped())


def test_equal_packages_are_ordered_by_id(fake, client, tree):
    from school_notes2.drive import inventory
    for _ in range(3):
        pkg = fake.folder("Óra", tree["ready"], minutes_ago=60)
        fake.file("1.jpg", pkg, b"a", created_ago=60)
    first = [p.id for p in inventory.scan(client, tree["root"]).ready]
    fake.items = dict(reversed(list(fake.items.items())))       # Drive answers in another order
    assert [p.id for p in inventory.scan(client, tree["root"]).ready] == first
    assert first == sorted(first)


def test_webp_photos_are_taken_and_a_nested_doc_extract_is_unwrapped(fake, client, tree):
    from school_notes2.drive import inventory
    photos = fake.folder("telefon", tree["ready"])
    fake.file("1.webp", photos, b"webp", mime="image/webp")
    nested = fake.folder("dia", tree["ready"])
    inner = fake.folder("dia-extract", nested)
    fake.file("document.md", inner, b"# Dia\n", mime="text/markdown")
    fake.file("p.png", fake.folder("figures", inner), b"png", mime="image/png")
    inv = inventory.scan(client, tree["root"])
    by_name = {p.name: p for p in inv.ready}
    assert [f.rel for f in by_name["telefon"].files] == ["1.webp"]
    doc = by_name["dia"]
    assert doc.preconverted and [f.rel for f in doc.files] == ["document.md", "figures/p.png"]
    assert sorted(e[1] for e in doc.listed) == ["dia-extract/document.md", "dia-extract/figures/p.png"]
