"""T7: every converted host entry point refuses planted symlinks in the worktree."""

import os

import pytest

from school_notes2.sources.duplicates import Known
from school_notes2.sources.place import Downloaded, place_package
from school_notes2.state.safefs import UnsafePath
from school_notes2.wiki import check, generate


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "wiki/proba").mkdir(parents=True)
    (r / "wiki/proba/a.md").write_text("---\ntitle: A\n---\n# A\n")
    canary = tmp_path / "canary"
    canary.mkdir()
    (canary / "secret.md").write_text("SECRET\n")
    return r, canary


def test_check_does_not_read_or_fix_through_a_link(repo):
    r, canary = repo
    (canary / "secret.md").write_bytes(b"SECRET\r\n")
    os.symlink(canary / "secret.md", r / "wiki/proba/b.md")
    with pytest.raises(UnsafePath):
        check.check_files(r, ["wiki/proba/b.md"])
    assert (canary / "secret.md").read_bytes() == b"SECRET\r\n"


def test_linked_subject_folder_is_not_indexed(repo):
    r, canary = repo
    os.symlink(canary, r / "wiki/evil")
    assert "evil" not in generate.subject_order(r)


def test_sources_never_placed_through_a_linked_subject(repo, tmp_path):
    r, canary = repo
    os.symlink(canary, r / "sources")
    download = tmp_path / "dl.md"
    download.write_text("# doc\n")
    pkg = Downloaded("Csomag", "proba", "tanari", "", False, True,
                     [{"rel": "document.md", "path": str(download), "sha256": "0" * 64}])
    with pytest.raises(UnsafePath):
        place_package(r, pkg, 1, Known())
    assert sorted(os.listdir(canary)) == ["secret.md"]
