"""Regression tests for the findings of the first Opus code review (wiki part)."""

import hashlib

from school_notes2.figures.insert import comment_safe
from school_notes2.sources.duplicates import known_hashes, original_key
from school_notes2.wiki import check, frontmatter, guard, machine, public
from school_notes2.wiki.guard import Change, GuardInput
from tests.wiki.test_guard import base_reader, snapshot

SHA = "a" * 64


def fetch(seq, path, page=None, sha="1" * 64, package="Óra 1"):
    return {"pages": [{"seq": seq, "package": package, "file": "f.pdf" if page else "1.jpg",
                       "page": page, "path": path, "sha256": sha, "original_sha256": SHA,
                       "duplicate_of": None}]}


def test_extending_a_lesson_page_keeps_earlier_hashes_and_folders(repo):
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    machine.write_lesson_notes(repo, [{"file": rel, "pages": [1]}],
                               fetch(1, "sources/proba/ora-1/p0001.jpg", page=1), 9, "x", "T")
    machine.write_lesson_notes(repo, [{"file": rel, "pages": [1]}],
                               fetch(1, "sources/proba/ora-2/1.jpg", sha="2" * 64,
                                     package="Óra 2"), 9, "x", "T")
    meta = frontmatter.split((repo / rel).read_text()).meta
    assert meta["content_sha256"] == {"ora-1/p0001.jpg": "1" * 64, "ora-2/1.jpg": "2" * 64}
    assert meta["source_file"] == ["proba/ora-1/", "proba/ora-2/"]
    assert meta["drive_folder"] == ["Óra 1", "Óra 2"]


def test_pdf_page_key_written_is_the_key_the_duplicate_check_reads(repo):
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    machine.write_lesson_notes(repo, [{"file": rel, "pages": [1]}],
                               fetch(1, "sources/proba/ora-1/p0003.jpg", page=3), 9, "x", "T")
    assert original_key(SHA, 3) in known_hashes(repo).original


def test_lesson_page_needs_no_type_from_the_writer(repo):
    rel = "wiki/proba/2026-10-02-uj-jegyzet.md"
    (repo / rel).write_text("---\ntitle: Új\ndescription: d\nlessons:\n  - {date: '2026-10-02', "
                            "title: Óra, topics: [elso.md]}\n---\n\n# Új\n")
    found = [i["message"] for i in check.check_files(repo, [rel])]
    assert not any("'type'" in m for m in found), found


def test_check_judges_only_writer_files(repo):
    for rel in ("docs/review/x.md", "sources/proba/csomag/document.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("$$ [törött](nincs.md)\n")
    (repo / "references/proba").mkdir(parents=True)
    (repo / "references/proba/k.md").write_text("/home/dlaszlo/titok\n")
    found = check.check_files(repo, ["docs/review/x.md", "sources/proba/csomag/document.md",
                                     "references/proba/k.md"])
    assert [i["file"] for i in found] == ["references/proba/k.md"]


def test_guard_refuses_dotfiles_and_accepts_resolved_conflicts(repo):
    base = snapshot(repo)
    (repo / "wiki/.gitattributes").write_text("* merge=union\n")
    (repo / "docs/review").mkdir(parents=True)
    (repo / "docs/review/index.md").write_text("<<<feloldva\n")
    tool = {"docs/review/index.md": "0" * 64}
    found = guard.run(GuardInput(repo, [Change("wiki/.gitattributes", "added"),
                                        Change("docs/review/index.md", "added")],
                                 base_reader(base), tool_files=tool,
                                 conflict_files=frozenset({"docs/review/index.md"})))
    assert [v.path for v in found] == ["wiki/.gitattributes"]


def test_comment_safe_cannot_close_the_html_comment():
    assert "--" not in comment_safe("szép --> kép ---- vége")


def test_public_refuses_a_copied_source_photo_and_knows_generated_receipts(repo):
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    photo = b"source page bytes"
    machine.write_lesson_notes(repo, [{"file": rel, "pages": [1]}],
                               fetch(1, "sources/proba/csomag/01.jpg",
                                     sha=hashlib.sha256(photo).hexdigest()), 9, "x", "T")
    (repo / "wiki/assets/copy.jpg").write_bytes(photo)
    elso = repo / "wiki/proba/elso.md"
    elso.write_text(elso.read_text() + "\n![x](../assets/copy.jpg)\n")
    try:
        public.build(repo, lambda r: ("authored", "x"))
        raise AssertionError("expected PublicError")
    except public.PublicError as exc:
        assert exc.paths == ["wiki/assets/copy.jpg"] and "source photo" in exc.reason
    (repo / "docs/evidence/media/banner-1").mkdir(parents=True)
    (repo / "wiki/assets/banner").mkdir()
    (repo / "wiki/assets/banner/banner-1.webp").write_bytes(b"image")
    assert public.media_receipt_rights(repo)("wiki/assets/banner/banner-1.webp") is None
