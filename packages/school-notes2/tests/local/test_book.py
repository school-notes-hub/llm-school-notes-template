import shutil

import pytest

from school_notes2.local import book
from tests.local.conftest import TEMPLATE

DOC = "\n".join(
    [f"<!-- element:p{p:03d}-e001 kind=text page={p} -->\nText {p}" for p in range(1, 4)]
    + ["<!-- element:p004-e001 kind=text page=4 -->", "## Tartalom",
       "<table><tr><td>Első lecke</td><td>3</td></tr><tr><td>Második lecke</td><td>5</td></tr>"
       "<tr><td>Harmadik</td><td>7</td></tr><tr><td>Negyedik</td><td>9</td></tr>"
       "<tr><td>Ötödik</td><td>11</td></tr></table>"]
    + [f"<!-- element:p{p:03d}-e001 kind=text page={p} -->\nText {p}" for p in range(5, 14)]) + "\n"


@pytest.fixture
def setup(repo, fake_local, tmp_path):
    (repo / "tools").mkdir()
    for name in ("book_index.py", "book-index.json"):
        shutil.copy(TEMPLATE / "tools" / name, repo / "tools" / name)
    source = tmp_path / "extract"
    (source / "figures").mkdir(parents=True)
    (source / "document.md").write_text(DOC)
    (source / "manifest.json").write_text("{}")
    (source / "figures" / "f1.png").write_bytes(b"png")
    (source / "OH-X__teljes.pdf").write_bytes(b"%PDF")
    return fake_local(repo), source


def test_book_places_writes_readme_table_and_map(setup, repo, capsys):
    local, source = setup
    assert book.run(local, "irodalom", "OH-X11TB", source, 1) == 0
    base = repo / "references/irodalom/oh-x11tb"
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()) == [
        "README.md", "document.md", "figures/f1.png", "index.md", "manifest.json"]
    readme = (base / "README.md").read_text()
    assert "printed-page offset: 1" in readme and "| Első lecke | 3 |" in readme and "| Ötödik | 11 |" in readme
    assert "Első lecke" in (base / "index.md").read_text()
    first = (base / "index.md").read_bytes()
    assert book.run(local, "irodalom", "OH-X11TB", None, None) == 0      # map again from the README
    assert (base / "index.md").read_bytes() == first


def test_book_refuses_an_existing_book_and_needs_an_offset(setup):
    local, source = setup
    with pytest.raises(SystemExit):
        book.run(local, "irodalom", "OH-X11TB", source, None)
    book.run(local, "irodalom", "OH-X11TB", source, 1)
    with pytest.raises(SystemExit):
        book.run(local, "irodalom", "OH-X11TB", source, 1)
