"""sn 0.3.11: `sn close --subject` records the pages outside the subject it wrote (the root
index); an `ujranezes.json` entry for a figure that is not inserted is a STOP line, not a crash;
`sn book` with a negative printed-page offset. Each test fails on d50c803, except three guards of
behaviour that must stay: a hand edit the close did not write stays a finding, an inserted
figure in `ujranezes.json` still snapshots, and the CLI's negative `--offset`."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from school_notes2.local import book, close, done, guard, tool_writes
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter
from tests.local.conftest import TEMPLATE, git
from tests.local.test_close import (ACCEPT, PAGE, RECHECK, handoff, inserted, learner_tree, quiet,  # noqa: F401
                                    setup, tree)
from tests.local.test_close_data import adatok

CHEM = "wiki/chemistry/acid.md"


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def violations(repo, local):
    return guard.violations(repo, local.git(), None)


# 3. sn close --subject: the root index it writes is the tool's.

def new_topic(repo, rel="wiki/physics/motion.md", title="Motion"):
    safefs.write_text(repo, rel, f"---\ntitle: {title}\ndescription: Moving\ntype: topic\nchapter: alapok\n"
                                 "order: 20\n---\n# Motion\n\nThings move.\n")


def describe(repo, subject="physics", text="Erők és mozgás."):
    """The writer changes the subject's description: the root index's `subjects` block follows."""
    rel = f"wiki/{subject}/index.md"
    safefs.write_text(repo, rel, safefs.read_text(repo, rel).replace("A próba tantárgy témakörei.", text, 1))


def test_a_subject_close_records_the_root_index_it_wrote(repo, fake_local):
    local = fake_local(repo)
    new_topic(repo)
    describe(repo)
    adatok(repo)
    root = safefs.read_text(repo, "wiki/index.md")
    lines = []
    assert close.close(local, repo, ["physics"], lines.append) in (0, 1), lines
    assert "Erők és mozgás." in safefs.read_text(repo, "wiki/index.md") != root   # the subjects block
    assert "wiki/index.md" in tool_writes.load(repo)["parts"]
    assert violations(repo, local) == []                            # sn done's guard is learner-wide
    assert not any("written by hand" in line for _, items in done.problems(repo) for line in items)


def test_a_hand_edit_outside_the_subject_is_not_recorded_by_a_subject_close(repo, fake_local):
    local = fake_local(repo)
    chem = safefs.read_text(repo, CHEM)
    safefs.write_text(repo, CHEM, frontmatter.set_keys(chem, {"generated": {"by": "kéz", "at": "x"}}))
    safefs.write_text(repo, "wiki/chemistry/index.md",                # makes the close write this index
                      safefs.read_text(repo, "wiki/chemistry/index.md").replace("Chemistry", "Kémia", 1))
    new_topic(repo)
    adatok(repo)
    lines = []
    assert close.close(local, repo, ["physics"], lines.append) in (0, 1), lines
    parts = tool_writes.load(repo)["parts"]
    assert CHEM not in parts                                          # the close did not write it
    assert any(CHEM in v and "generated" in v for v in violations(repo, local))


def hand_block(repo, rel, name, body="* kézzel írt sor\n"):
    from school_notes2.wiki import markers
    safefs.write_text(repo, rel, markers.replace(safefs.read_text(repo, rel), name, body))


def test_a_block_left_by_an_unrecorded_earlier_close_is_taken_over_when_rewritten(repo, fake_local):
    """sn 0.3.10 left the root index's `subjects` block unrecorded; the next subject close
    rewrites the block, so it is the tool's again."""
    local = fake_local(repo)
    hand_block(repo, "wiki/index.md", "subjects")
    assert violations(repo, local)
    new_topic(repo)
    describe(repo)
    adatok(repo)
    lines = []
    assert close.close(local, repo, ["physics"], lines.append) in (0, 1), lines
    assert "wiki/index.md" in tool_writes.load(repo)["parts"] and violations(repo, local) == []


def test_a_hand_edited_part_the_close_did_not_overwrite_is_not_recorded(repo, fake_local):
    local = fake_local(repo)
    rel = "wiki/chemistry/index.md"
    safefs.write_text(repo, rel, frontmatter.set_keys(safefs.read_text(repo, rel), {"generated": {"by": "kéz", "at": "x"}}))
    hand_block(repo, rel, "chapters")                               # the close rewrites this block
    new_topic(repo)
    adatok(repo)
    lines = []
    assert close.close(local, repo, ["physics"], lines.append) in (0, 1), lines
    assert "kézzel írt sor" not in safefs.read_text(repo, rel)      # the close wrote the page
    assert rel not in tool_writes.load(repo)["parts"]
    assert any(rel in line and "nem rögzítem" in line for line in lines)
    assert violations(repo, local) == [f"{rel}: a machine frontmatter key was written by hand (generated)"
                                       f"{guard.INTERRUPTED}"]


# 2. --snapshot with a new figure listed in ujranezes.json.

def test_a_new_figure_in_ujranezes_is_a_stop_line_not_a_crash(repo, make_figure, fake_local):
    make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {}, rechecks=RECHECK)
    local = fake_local(repo)
    before = tree(repo)
    lines = []
    assert close.snapshot(local, ["physics"], ["forces"], lines.append) == close.STOP
    assert tree(repo) == before                                       # nothing written, no keys.json
    text = "\n".join(lines)
    assert lines[0].startswith("STOP") and "physics/forces" in text
    assert "az ujranezes.json csak beillesztett ábrát sorolhat" in text and "figures.json-ban marad" in text
    assert "--snapshot --only forces" in text
    assert close.snapshot(local, None, None, lines.append) == close.STOP      # without --only too


def test_an_unknown_figure_in_ujranezes_is_named(repo, make_figure, fake_local):
    make_figure()
    handoff(repo, [], {}, rechecks=[{**RECHECK[0], "id": "nincs-ilyen"}])
    lines = []
    assert close.snapshot(fake_local(repo), None, None, lines.append) == close.STOP
    assert any("physics/nincs-ilyen" in line and "nincs beillesztve" in line for line in lines)


def test_the_close_stops_on_it_too_before_writing(setup, repo):
    local, _ = setup
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT},
            rechecks=RECHECK, recheck={"forces": ACCEPT})
    before = tree(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert tree(repo) == before
    assert any("az ujranezes.json csak beillesztett ábrát sorolhat" in line for line in lines)


def test_an_inserted_figure_in_ujranezes_still_snapshots(setup, repo):
    local, _ = setup
    inserted(repo, local)
    handoff(repo, [], {}, rechecks=RECHECK)
    assert close.snapshot(local, None, ["forces"], quiet) == 0
    assert "forces" in json.loads(safefs.read_text(repo, ".school-notes/out/physics/keys.json"))


# 1. sn book with a negative offset (the excerpt's PDF page 1 is printed page 5).

DOC = "".join(f"<!-- element:p{p:03d}-e001 kind=text page={p} -->\nText {p}\n" for p in range(1, 13))


@pytest.fixture
def excerpt(repo, fake_local, tmp_path):
    (repo / "tools").mkdir(exist_ok=True)
    for name in ("book_index.py", "book-index.json"):
        shutil.copy(TEMPLATE / "tools" / name, repo / "tools" / name)
    source = tmp_path / "eptan_5-16"
    source.mkdir()
    (source / "document.md").write_text(DOC)
    (source / "manifest.json").write_text("{}")
    return fake_local(repo), source


def test_sn_book_with_a_negative_offset_maps_and_records(excerpt, repo):
    local, source = excerpt
    assert book.run(local, "epitestan", "eptan_5-16", source, -4) == 0
    base = "references/epitestan/eptan-5-16"
    assert "printed-page offset: -4" in safefs.read_text(repo, f"{base}/README.md")
    index = safefs.read_text(repo, f"{base}/index.md")
    assert "printed = PDF - (-4)" in index
    assert "* 5: 1 · 6: 3" in index and "16: 23" in index               # PDF 1 = printed 5, PDF 12 = 16
    assert sorted(tool_writes.load(repo)["files"]) == [f"{base}/README.md", f"{base}/document.md",
                                                       f"{base}/index.md", f"{base}/manifest.json"]
    first = safefs.read_bytes(repo, f"{base}/index.md")
    assert book.run(local, "epitestan", "eptan_5-16", None, None) == 0  # again from the README
    assert book.run(local, "epitestan", "eptan_5-16", None, -4) == 0    # and with the option
    assert safefs.read_bytes(repo, f"{base}/index.md") == first


def test_a_failed_map_still_records_the_placed_book(excerpt, repo, monkeypatch, capsys):
    local, source = excerpt
    real = subprocess.run
    monkeypatch.setattr(book.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "kaput"))
    assert book.run(local, "epitestan", "eptan_5-16", source, -4) == 1
    monkeypatch.setattr(book.subprocess, "run", real)
    base = "references/epitestan/eptan-5-16"
    assert f"{base}/document.md" in tool_writes.load(repo)["files"]
    assert f"{base}/index.md" not in tool_writes.load(repo)["files"]
    assert "forrásmappa nélkül" in capsys.readouterr().out
    assert book.run(local, "epitestan", "eptan_5-16", None, None) == 0
    assert f"{base}/index.md" in tool_writes.load(repo)["files"]


def test_the_cli_takes_a_negative_offset_in_both_forms():
    from school_notes2 import cli
    p = cli._parser()
    for argv in (["--offset", "-4"], ["--offset=-4"]):
        args = p.parse_args(["book", "barna", "epitestan", "eptan_5-8", "/src", *argv])
        assert args.offset == -4
