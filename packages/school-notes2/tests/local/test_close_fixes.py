"""The fix round of sn 0.3.0 (review of step 5): each test fails on 5d9f108."""

import os
import shutil

import pytest

from school_notes2.local import close, done, guard, machine_data, tool_writes
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter, machine
from tests.local.conftest import git
from tests.local.test_close import ACCEPT, PAGE, handoff, learner_tree, quiet, tree  # noqa: F401
from tests.local.test_close_data import LOG, adatok, place, write_log


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def found(repo, fake_local, subjects=None):
    return guard.violations(repo, fake_local(repo).git(), subjects)


def closed_log(repo, fake_local):
    paths = place(repo)
    write_log(repo)
    adatok(repo, notes=[{"file": LOG, "pages": paths}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    commit(repo)
    safefs.unlink(repo, ".school-notes/out/physics/adatok.json")


# 2. A crash after the first write never turns into a guard finding; bad input stops first.

def test_an_interrupted_close_is_finished_by_running_it_again(repo, make_figure, fake_local, monkeypatch):
    make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    local = fake_local(repo)
    assert close.snapshot(local, None, None, quiet) == 0

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(machine_data, "write", boom)
    with pytest.raises(OSError):
        close.close(local, repo, None, quiet)                    # the figure is already inserted
    monkeypatch.undo()
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == 0, lines


def test_a_bad_later_verdict_stops_before_the_first_insertion(repo, make_figure, fake_local):
    make_figure()
    make_figure(fid="forces2")
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None},
                   {"id": "forces2", "page": PAGE, "route": "figure", "replaces": None}],
            {"forces": ACCEPT, "forces2": {**ACCEPT, "observed": ""}})
    local = fake_local(repo)
    assert close.snapshot(local, None, None, quiet) == 0
    before = tree(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any("physics/forces2: verdicts.json" in line for line in lines) and tree(repo) == before


def test_an_unreadable_lesson_log_stops_before_any_note_is_written(repo, fake_local):
    paths = place(repo)
    write_log(repo)
    other = "wiki/physics/2026-10-02-masik-jegyzet.md"
    safefs.write_text(repo, other, "---\ntitle: [nyitott\n---\n# Másik\n")
    adatok(repo, notes=[{"file": LOG, "pages": paths}, {"file": other, "pages": paths}])
    before = tree(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == close.STOP
    assert any(f"{other}: unreadable frontmatter" in line for line in lines) and tree(repo) == before


# 3. The writer's own `sources` entries.

def test_a_writers_web_and_textbook_sources_are_not_machine_data(repo, fake_local):
    closed_log(repo, fake_local)
    text = safefs.read_text(repo, LOG)
    meta = frontmatter.split(text).meta
    sources = meta["sources"] + [{"id": "wiki-ero", "resource": "https://hu.wikipedia.org/wiki/Er%C5%91", "title": "Erő"},
                                 {"id": "tk", "resource": "../../references/physics/book/document.md", "title": "Fizika 9."}]
    safefs.write_text(repo, LOG, frontmatter.set_keys(text, {"sources": sources}))
    assert found(repo, fake_local) == []
    tampered = [dict(meta["sources"][0], title="kézzel")]
    safefs.write_text(repo, LOG, frontmatter.set_keys(text, {"sources": tampered}))
    assert found(repo, fake_local)[0].startswith(f"{LOG}: a machine frontmatter key was written by hand (sources)")


# 4. Renamed and deleted pages; decisions as YAML.

def test_a_renamed_lesson_log_is_compared_with_its_old_version(repo, fake_local):
    closed_log(repo, fake_local)
    os.rename(repo / LOG, repo / LOG.replace("forces-jegyzet", "erok-jegyzet"))
    assert found(repo, fake_local) == []


def with_decisions(repo, flow=False):
    entry = "{id: forces-a, claim: Két erő., answer: Igen., by: owner, 'on': '2026-10-01'}"
    block = f"decisions: [{entry}]\n" if flow else f"decisions:\n  - {entry}\n"
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("---\n# Forces", block + "---\n# Forces", 1))
    commit(repo)


def test_a_deleted_page_keeps_its_decisions_somewhere(repo, fake_local):
    with_decisions(repo)
    keep = safefs.read_text(repo, PAGE)
    safefs.unlink(repo, PAGE)
    assert found(repo, fake_local) == [f"{PAGE}: the page was deleted with `decisions` entries that stand on no other page"]
    safefs.write_text(repo, "wiki/physics/uj.md", keep.replace("# Forces", "# Erők"))     # moved with it
    assert found(repo, fake_local) == []


def test_an_inline_decision_list_is_protected_too(repo, fake_local):
    with_decisions(repo, flow=True)
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("answer: Igen.", "answer: Nem."))
    assert found(repo, fake_local) == [f"{PAGE}: an existing `decisions` entry was removed or changed"]


# 5. A v1 lesson log keeps its hashes when continued.

V1 = """---
title: Erőfajták
description: Az erőfajták órája.
lessons:
  - {date: '2026-09-26', title: Erőfajták, topics: [forces.md]}
type: lesson-notes
generated: {by: claude-opus-5.5/high, at: '2026-10-06T12:40:00+02:00'}
grade: 11
source_file: sources/2026-09-26-statika-fuzet/page-07.jpeg
content_sha256: f16984137fcad1deea94a61123196e95daa0878cb8c83a5afa216ebb6f1b8ba5
source_files:
  - { file: sources/2026-09-26-statika-fuzet/page-07.jpeg, sha256: f16984137fcad1deea94a61123196e95daa0878cb8c83a5afa216ebb6f1b8ba5 }
  - { file: sources/2026-09-26-statika-fuzet/page-08.jpeg, sha256: 9a3ca12999b04ed8a2b7b4efde1f95493ca9b73baac45765ee5d8c2bbf87a605 }
sources:
  - { id: uj-01, resource: ../../sources/2026-09-26-statika-fuzet/page-07.jpeg, title: "Statika-füzet, 7. oldal" }
  - { id: uj-02, resource: ../../sources/2026-09-26-statika-fuzet/page-08.jpeg, title: "Statika-füzet, 8. oldal" }
---
# Mit tanultunk ezen az órán
"""


def test_a_continued_v1_lesson_log_keeps_its_old_hashes(repo):
    """The frontmatter of a real v1 log (Barna, statika, 2026-09-26): string hash, file path
    in `source_file`, `source_files` list."""
    meta = frontmatter.split(V1).meta
    new = [{"path": "sources/statika/2026-10-09/p0001.jpg", "sha256": "c" * 64, "original_sha256": "d" * 64,
            "package": "2026-10-09"}]
    values = machine.lesson_values("wiki/statika/2026-09-26-erofajtak-jegyzet.md", new, 11, "w", "t", old=meta)
    assert values["source_file"] == ["2026-09-26-statika-fuzet/", "statika/2026-10-09/"]
    assert values["content_sha256"] == {
        "2026-09-26-statika-fuzet/page-07.jpeg": "f16984137fcad1deea94a61123196e95daa0878cb8c83a5afa216ebb6f1b8ba5",
        "2026-09-26-statika-fuzet/page-08.jpeg": "9a3ca12999b04ed8a2b7b4efde1f95493ca9b73baac45765ee5d8c2bbf87a605",
        "statika/2026-10-09/p0001.jpg": "c" * 64}
    merged = machine.merge_sources(meta["sources"], values["sources"])
    assert [s["id"] for s in merged] == ["2026-10-09", "uj-01", "uj-02"]


# 8. The pass identity of the evidence record.

def test_a_replayed_hand_over_is_the_same_pass_and_another_one_gets_its_own_section(repo, fake_local, monkeypatch):
    from school_notes2.local import common
    paths = place(repo)
    write_log(repo)
    check = {"page": LOG, "image": paths[0], "locator": "1. oldal", "observed": "Két nyíl.", "decision": "confirmed"}
    adatok(repo, notes=[{"file": LOG, "pages": paths}], checks=[check])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    record = "docs/evidence/pages/physics/2026-10-01-forces-jegyzet.md"
    first = safefs.read_text(repo, record)
    monkeypatch.setattr(common, "today", lambda: "2099-01-01")
    monkeypatch.setattr(machine_data, "today", lambda: "2099-01-01")
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    assert safefs.read_text(repo, record) == first                     # any day: the same pass
    adatok(repo, notes=[{"file": LOG, "pages": paths}], checks=[{**check, "observed": "Három nyíl."}])
    assert close.close(fake_local(repo), repo, None, quiet) == 0
    text = safefs.read_text(repo, record)
    assert "Két nyíl." in text and "Három nyíl." in text and text.count("\n## ") == 2


# 9. A directly linked writer SVG gets its receipt.

SVG = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><circle cx='5' cy='5' r='4'/></svg>"


def test_a_directly_linked_writer_svg_is_closed_with_its_receipt(repo, fake_local):
    safefs.write_text(repo, "wiki/assets/physics/korok.svg", SVG)
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "![Két kör](../assets/physics/korok.svg)\n")
    adatok(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == 0, lines
    asset = next(a for a in safefs.read_json(repo, "publication/public.json")["assets"] if a["path"] == "wiki/assets/physics/korok.svg")
    assert asset["rights"] == "authored"


def test_a_directly_linked_svg_with_an_embedded_image_stops(repo, fake_local):
    safefs.write_text(repo, "wiki/assets/physics/foto.svg", SVG.replace("<circle", "<image href='x.png'/><circle"))
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "![Fotó](../assets/physics/foto.svg)\n")
    adatok(repo)
    before = tree(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == close.STOP
    assert any("may not embed another image" in line for line in lines) and tree(repo) == before


# 10. --subject looks only at the named subjects (sources/ stays global).

def test_a_subject_close_is_not_blocked_by_another_subject(repo, fake_local):
    chem = "wiki/chemistry/acid.md"
    safefs.write_text(repo, chem, frontmatter.set_keys(safefs.read_text(repo, chem), {"generated": {"by": "x", "at": "y"}})
                      + "<!-- figure-request: sav -->\n")
    adatok(repo)
    lines = []
    assert close.close(fake_local(repo), repo, ["physics"], lines.append) in (0, 1), lines   # done is learner-wide
    assert not any(line.startswith("STOP") for line in lines)
    assert safefs.read_text(repo, chem).count("generated: {by: x") == 1                       # untouched
    assert found(repo, fake_local, ["physics"]) == [] and found(repo, fake_local)
    safefs.write_bytes(repo, "sources/physics/stray.jpg", b"x")
    assert found(repo, fake_local, ["chemistry"]) != []                                      # sources/ is global


# 11. What the guard counts as an image; staged sources; manifest files.

def test_render_receipts_and_drawing_sources_are_not_images(repo, fake_local):
    for rel, data in (("wiki/assets/physics/render.json", "{}"), ("wiki/assets/physics/drawing.py", "x = 1\n"),
                      ("wiki/assets/physics/photo.JPG", "jpg")):
        safefs.write_text(repo, rel, data)
    commit(repo)
    for rel in ("wiki/assets/physics/render.json", "wiki/assets/physics/drawing.py", "wiki/assets/physics/photo.JPG"):
        safefs.write_text(repo, rel, safefs.read_text(repo, rel) + "\n# changed\n")
    assert found(repo, fake_local) == ["wiki/assets/physics/photo.JPG: the bytes of a committed image changed "
                                       "(a replacement is a new file with `replaces`)"]


def test_staged_fetched_sources_are_fine_and_manifest_files_must_be_there(repo, fake_local):
    paths = place(repo)
    git(repo, "add", "sources")
    assert found(repo, fake_local) == []
    safefs.unlink(repo, paths[1])
    assert found(repo, fake_local) == [f"{paths[1]}: a file of its source manifest is missing or changed"]


# 12. A new lesson log must be in the hand-over.

def test_a_new_lesson_log_missing_from_adatok_stops(repo, fake_local):
    place(repo)
    write_log(repo)
    adatok(repo)
    before = tree(repo)
    lines = []
    assert close.close(fake_local(repo), repo, None, lines.append) == close.STOP
    assert f"  {LOG}: a new lesson log that is in no adatok.json `notes` (its source pages are needed)" in lines
    assert tree(repo) == before


# 13. sn book, request markers in sn done, failed candidates in --snapshot.

def test_sn_done_counts_a_request_marker_without_its_record(repo, fake_local):
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "<!-- figure-request: tabla -->\n")
    assert dict(done.problems(repo))["képkérés rögzítés nélkül"] == [f"{PAGE} tabla"]


def test_a_failed_candidate_may_stay_in_figures_json(repo, make_figure, fake_local):
    make_figure()
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", {"state": "failed", "reason": "nem sikerült"})
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {})
    lines = []
    assert close.snapshot(fake_local(repo), None, None, lines.append) == 0, lines
    assert "nem megy a lektorhoz (failed): physics/forces" in lines


def test_sn_book_records_only_what_it_wrote_and_only_on_success(repo, fake_local, tmp_path, monkeypatch):
    from school_notes2.local import book
    src = tmp_path / "extract"
    src.mkdir()
    (src / "document.md").write_text("<!-- element:p001-e001 kind=text page=1 -->\nText\n")
    shutil.copytree(book.__file__.rsplit("/packages/", 1)[0] + "/tools", repo / "tools", dirs_exist_ok=True)
    safefs.write_text(repo, "references/physics/other/x.md", "kézzel\n")
    assert book.run(fake_local(repo), "physics", "fiz9", src, 0) == 0
    files = tool_writes.load(repo)["files"]
    assert sorted(files) == ["references/physics/fiz9/README.md", "references/physics/fiz9/document.md",
                             "references/physics/fiz9/index.md"]
    assert found(repo, fake_local) == ["references/physics/other/x.md: new file under references/ that sn book did not write"]
