"""`sn close` writes the machine data from the hand-over's adatok.json and the source manifests
(controller decisions D1, D2, D3, D8): lesson-log machine frontmatter, `generated` stamps, page
evidence records, docs/figure-requests.json, the draft notice. The writer never writes them."""

import hashlib
import io
import json

import pytest
from PIL import Image

from school_notes2.figures import requests
from school_notes2.local import close, done
from school_notes2.sources import manifest
from school_notes2.state import safefs
from school_notes2.wiki import drafts, frontmatter
from tests.local.conftest import git
from tests.local.test_close import learner_tree, quiet, tree  # noqa: F401 - the learner repo

LOG = "wiki/physics/2026-10-01-forces-jegyzet.md"
FOLDER = "sources/physics/2026-10-02"


def jpeg(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, "JPEG")
    return out.getvalue()


def place(repo, folder=FOLDER, colors=("red", "blue"), role="fuzet", pdf=False):
    """A placed package as `sn fetch` leaves it: page images and the manifest."""
    pages, written = [], {}
    for n, color in enumerate(colors, start=1):
        rel = f"{folder}/p{n:04d}.jpg"
        data = jpeg(color)
        safefs.write_bytes(repo, rel, data)
        sha = hashlib.sha256(data).hexdigest()
        written[rel] = sha
        original = ("a" * 64 + f"#p{n}") if pdf else hashlib.sha256(b"upload" + data).hexdigest()
        pages.append({"path": rel, "file": "f.pdf" if pdf else f"{n}.jpg", "page": n if pdf else None,
                      "sha256": sha, "original_key": original, "duplicate_of": None})
    package = {"drive_id": "pkg1", "drive_folder": folder.rsplit("/", 1)[1], "subject_name": "Physics",
               "role": role, "description": ""}
    drive_ids = {p["file"]: f"drive-{p['file']}" for p in pages}
    safefs.write_text(repo, f"{folder}/{manifest.NAME}", manifest.dumps(manifest.build(package, pages, drive_ids, written)))
    return [p["path"] for p in pages]


def write_log(repo, rel=LOG, extra=""):
    safefs.write_text(repo, rel, "---\ntitle: Erők\ndescription: Az erők órája.\nlessons:\n"
                      "  - {date: '2026-10-01', title: Erők, topics: [forces.md]}\n" + extra + "---\n"
                      "# Mit tanultunk ezen az órán\n\n* Egy [pont](forces.md#forces).\n* Kettő [pont](forces.md#forces).\n"
                      "* Három [pont](forces.md#forces).\n")


def adatok(repo, subject="physics", **data):
    safefs.write_json(repo, f".school-notes/out/{subject}/adatok.json", {"writer": "claude-opus-5-5/high", **data})


def test_close_writes_the_lesson_logs_machine_keys_from_the_manifest(repo, fake_local):
    paths = place(repo)
    write_log(repo)
    adatok(repo, notes=[{"file": LOG, "pages": paths}])
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == 0, lines
    meta = frontmatter.split(safefs.read_text(repo, LOG)).meta
    assert meta["type"] == "lesson-notes" and meta["grade"] == 9
    assert meta["source_file"] == "physics/2026-10-02/"
    assert meta["drive_folder"] == "2026-10-02"
    assert list(meta["content_sha256"]) == ["p0001.jpg", "p0002.jpg"]
    assert meta["sources"][0]["resource"] == "../../sources/physics/2026-10-02/p0001.jpg"
    assert meta["generated"]["by"] == "claude-opus-5-5/high"
    assert "📎 Füzet: 2026. 10. 01." in safefs.read_text(repo, LOG)
    before = tree(repo)
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    assert tree(repo) == before                                  # a repeated close changes nothing


def test_a_continued_lesson_keeps_its_earlier_pages(repo, fake_local):
    first = place(repo)
    write_log(repo)
    adatok(repo, notes=[{"file": LOG, "pages": first}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pass 1")
    second = place(repo, "sources/physics/2026-10-09", ("green",))
    adatok(repo, notes=[{"file": LOG, "pages": second}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    meta = frontmatter.split(safefs.read_text(repo, LOG)).meta
    assert meta["source_file"] == ["physics/2026-10-02/", "physics/2026-10-09/"]
    assert sorted(meta["content_sha256"]) == ["2026-10-02/p0001.jpg", "2026-10-02/p0002.jpg", "2026-10-09/p0001.jpg"]
    assert meta["drive_folder"] == ["2026-10-02", "2026-10-09"]


def test_a_source_page_without_a_manifest_stops_before_writing(repo, fake_local):
    write_log(repo)
    safefs.write_bytes(repo, "sources/physics/old/01.jpg", jpeg("red"))
    adatok(repo, notes=[{"file": LOG, "pages": ["sources/physics/old/01.jpg"]}])
    before = tree(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == close.STOP
    assert any("is in no source manifest" in line for line in lines) and tree(repo) == before


def test_checks_become_the_page_evidence_record(repo, fake_local):
    paths = place(repo)
    write_log(repo)
    adatok(repo, notes=[{"file": LOG, "pages": paths}],
           checks=[{"page": LOG, "image": paths[1], "locator": "a második oldal ábrája", "observed": "Két nyíl.",
                    "decision": "confirmed", "note": "Zoomolva."}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    record = safefs.read_text(repo, "docs/evidence/pages/physics/2026-10-01-forces-jegyzet.md")
    assert f"* Kép: `{paths[1]}`" in record and "Forrás: 2026-10-02 / 2.jpg" in record
    assert "claude-opus-5-5/high – checks" in record and "Megfigyelés: Két nyíl." in record


def test_a_teacher_image_request_is_recorded_listed_and_never_missing(repo, fake_local):
    paths = place(repo, role="tanari")
    page = "wiki/physics/forces.md"
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "<!-- figure-request: tabla -->\n")
    assert dict(done.problems(repo))["ábrahely elfogadott ábra nélkül"] == []         # D3
    adatok(repo, requests=[{"id": "tabla", "page": page, "source": paths[0], "crop": "a bal felső sarok",
                            "purpose": "A táblarajz", "origin": "unknown"}])
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == 0, lines
    [record] = requests.load(repo)
    assert record["content_sha256"] == hashlib.sha256(safefs.read_bytes(repo, paths[0])).hexdigest()
    assert "képkérés a tulajdonosnak: tabla (wiki/physics/forces.md, unknown): A táblarajz" in lines


def test_a_request_marker_without_its_request_stops(repo, fake_local):
    page = "wiki/physics/forces.md"
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "<!-- figure-request: tabla -->\n")
    adatok(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == close.STOP
    assert any("needs exactly one matching request" in line for line in lines)


def test_a_changed_topic_page_gets_the_writers_stamp_once(repo, fake_local):
    page = "wiki/physics/forces.md"
    safefs.write_text(repo, page, safefs.read_text(repo, page) + "Egy új mondat.\n")
    adatok(repo)
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    stamp = frontmatter.split(safefs.read_text(repo, page)).meta["generated"]
    assert stamp["by"] == "claude-opus-5-5/high"
    assert frontmatter.split(safefs.read_text(repo, "wiki/chemistry/acid.md")).meta.get("generated") is None
    before = tree(repo)
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    assert tree(repo) == before


def test_a_draft_topic_gets_the_pending_notice_and_loses_it_when_stable(repo, fake_local):
    page = "wiki/physics/forces.md"
    text = frontmatter.set_keys(safefs.read_text(repo, page), {"status": "draft"})
    safefs.write_text(repo, page, text)
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    text = safefs.read_text(repo, page)
    assert drafts.NOTICE.strip() in text and drafts.KEY in frontmatter.split(text).meta
    safefs.write_text(repo, page, frontmatter.set_keys(text, {"status": "stable"}))
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    text = safefs.read_text(repo, page)
    assert drafts.NOTICE.strip() not in text and drafts.KEY not in frontmatter.split(text).meta


def test_a_teacher_only_lesson_log_is_not_labelled_fuzet(repo, fake_local):
    paths = place(repo, role="tanari")
    write_log(repo, extra="")
    adatok(repo, notes=[{"file": LOG, "pages": paths}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    assert "📎 Óra: 2026. 10. 01." in safefs.read_text(repo, LOG)


def test_an_invalid_adatok_is_refused(repo, fake_local):
    safefs.write_json(repo, ".school-notes/out/physics/adatok.json", {"notes": []})       # no writer
    with pytest.raises(close.Refused, match="adatok.json"):
        close.close(fake_local(repo), repo, None, quiet)


def test_known_hashes_read_the_manifest(repo):
    from school_notes2.sources.duplicates import known_hashes
    paths = place(repo, pdf=True)
    known = known_hashes(repo)
    assert known.match("a" * 64 + "#p2", "x") == paths[1]
    data = json.loads(safefs.read_text(repo, f"{FOLDER}/{manifest.NAME}"))
    assert data["pages"][0]["drive_id"] == "drive-f.pdf"
