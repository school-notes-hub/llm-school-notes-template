"""The writer guard (controller decision D5) and the candidate preflight (D4): read-only checks
that stop `sn close` before any write and make `sn done` non-zero."""

import os

from school_notes2.local import close, done, guard, tool_writes
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter
from tests.local.conftest import git
from tests.local.test_close import ACCEPT, PAGE, handoff, learner_tree, quiet, tree  # noqa: F401
from tests.local.test_close_data import FOLDER, place


def found(repo, fake_local):
    return guard.violations(repo, fake_local(repo).git())


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")


def with_decision(repo):
    text = frontmatter.set_keys(safefs.read_text(repo, PAGE), {"decisions": [
        {"id": "forces-a", "claim": "Két erő.", "answer": "Igen.", "by": "owner", "on": "2026-10-01"}]})
    safefs.write_text(repo, PAGE, text)
    commit(repo)


def test_a_clean_tree_and_a_writers_ordinary_edit_pass(repo, fake_local):
    assert found(repo, fake_local) == []
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "Új bekezdés.\n")
    assert found(repo, fake_local) == []


def test_an_existing_decision_may_not_change_but_one_may_be_added(repo, fake_local):
    with_decision(repo)
    text = safefs.read_text(repo, PAGE)
    added = text.replace("---\n# Forces", "  - {id: forces-b, claim: Új., answer: Igen., by: owner, 'on': '2026-10-02'}\n---\n# Forces")
    safefs.write_text(repo, PAGE, added)
    assert found(repo, fake_local) == []
    safefs.write_text(repo, PAGE, text.replace("answer: Igen.", "answer: Nem."))
    assert found(repo, fake_local) == [f"{PAGE}: an existing `decisions` entry was removed or changed"]


def test_committed_sources_are_immutable_and_new_ones_need_a_manifest(repo, fake_local):
    place(repo)
    assert found(repo, fake_local) == []
    commit(repo)
    safefs.write_bytes(repo, f"{FOLDER}/p0001.jpg", b"edited")
    safefs.write_bytes(repo, "sources/physics/stray.jpg", b"x")
    assert found(repo, fake_local) == [f"{FOLDER}/p0001.jpg: a committed source changed or was deleted (M)",
                                       "sources/physics/stray.jpg: new file under sources/ that no source manifest names"]


def test_a_new_source_file_must_match_its_manifest(repo, fake_local):
    place(repo)
    safefs.write_bytes(repo, f"{FOLDER}/p0002.jpg", b"swapped")
    assert found(repo, fake_local) == [f"{FOLDER}/p0002.jpg: differs from its source manifest"]


def test_a_new_reference_file_must_come_from_sn_book(repo, fake_local):
    safefs.write_text(repo, "references/physics/book/README.md", "# Könyv\n")
    assert found(repo, fake_local) == ["references/physics/book/README.md: new file under references/ that sn book did not write"]
    tool_writes.record(repo, files=["references/physics/book/README.md"])
    assert found(repo, fake_local) == []


def test_dotfiles_and_symlinks_under_wiki(repo, fake_local, tmp_path):
    safefs.write_text(repo, "wiki/physics/.gitattributes", "* merge=union\n")
    (tmp_path / "secret.md").write_text("x")
    os.symlink(tmp_path / "secret.md", repo / "wiki/physics/link.md")
    assert found(repo, fake_local) == ["wiki/physics/.gitattributes: dotfile under wiki/",
                                       "wiki/physics/link.md: symlink under wiki/"]


def test_machine_keys_and_generated_blocks_are_the_tools(repo, fake_local):
    text = safefs.read_text(repo, PAGE)
    safefs.write_text(repo, PAGE, frontmatter.set_keys(text, {"generated": {"by": "me", "at": "now"}}))
    assert found(repo, fake_local) == [f"{PAGE}: a machine frontmatter key was written by hand (generated)"]
    tool_writes.record(repo, parts=[PAGE])
    assert found(repo, fake_local) == []                       # the tool's own write
    index = "wiki/physics/index.md"
    old = safefs.read_text(repo, index)
    start = old.index("<!-- school-notes:generated chapters -->")
    safefs.write_text(repo, index, old[:start] + old[start:].replace("\n", "\nKézi sor.\n", 1))
    assert found(repo, fake_local) == [f"{index}: the generated block `chapters` was written by hand"]


def test_a_raster_image_goes_in_only_through_a_figure_block(repo, fake_local):
    safefs.write_bytes(repo, "wiki/assets/physics/photo.png", b"png")
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE) + "![x](../assets/physics/photo.png)\n")
    assert found(repo, fake_local) == [f"{PAGE}: new raster image link wiki/assets/physics/photo.png outside a figure "
                                       "block (a raster image goes in through a commission and the reviewer's accept)"]
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("photo.png", "drawing.svg"))
    safefs.write_text(repo, "wiki/assets/physics/drawing.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert found(repo, fake_local) == []                       # an own SVG needs no commission (D7)


def test_close_stops_on_a_guard_finding_and_done_counts_it(repo, fake_local):
    with_decision(repo)
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("answer: Igen.", "answer: Nem."))
    local = fake_local(repo)
    before = tree(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert lines[1].startswith("  író-őr: wiki/physics/forces.md") and tree(repo) == before
    assert done.report(repo, quiet, git=local.git()) == 1
    assert dict(done.problems(repo, local.git()))["író-őr: tiltott módosítás"]


def test_a_rightsless_raster_stops_before_any_write(repo, make_figure, fake_local):
    """Opus M5 probe: without a rights path the accepted raster used to be inserted, then the
    public build failed on every rerun. Now the preflight stops and the tree stays as it was."""
    make_figure()
    safefs.unlink(repo, "wiki/assets/physics/render.json")
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    local = fake_local(repo)
    lines = []
    assert close.snapshot(local, None, None, lines.append) == close.STOP
    assert any("no rights path" in line for line in lines)
    before = tree(repo)
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert tree(repo) == before and "school-notes:generated figure-forces" not in safefs.read_text(repo, PAGE)


def test_a_banner_needs_a_generated_webp(repo, make_figure, fake_local):
    make_figure(kind="banner")
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "image", "replaces": None}], {"forces": ACCEPT})
    lines = []
    assert close.snapshot(fake_local(repo), None, None, lines.append) == close.STOP
    assert any("banner/infographic needs a generated .webp" in line for line in lines)


def test_a_crop_outside_the_source_image_stops(repo, make_figure, fake_local):
    brief, candidate = make_figure(kind="notebook-drawing",
                                   source_image={"path": "wiki/assets/physics/forces.png", "crop": [0, 0, 1001, 500]})
    candidate["corrections"] = []
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    lines = []
    assert close.snapshot(fake_local(repo), None, None, lines.append) == close.STOP
    assert any("source crop exceeds image bounds" in line for line in lines)
