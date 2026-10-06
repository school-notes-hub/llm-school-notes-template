import json

import pytest

from school_notes2.figures import insert
from school_notes2.local import close
from school_notes2.local.common import today
from school_notes2.state import safefs

ACCEPT = {"verdict": "accept", "observed": "Two opposite arrows.", "defects": [], "text_mismatch": [],
          "relates_to": None}
PAGE = "wiki/physics/forces.md"


def handoff(repo, figures=(), verdicts=None, rechecks=(), recheck=None, subject="physics"):
    base = f".school-notes/out/{subject}"
    safefs.write_json(repo, f"{base}/figures.json", list(figures))
    safefs.write_json(repo, f"{base}/verdicts.json", verdicts or {})
    safefs.write_json(repo, f"{base}/ujranezes.json", list(rechecks))
    safefs.write_json(repo, f"{base}/recheck.json", recheck or {})


def tree(repo):
    return {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}


@pytest.fixture(autouse=True)
def learner_tree(repo):
    from school_notes2.wiki import generate, public
    from tests.e2e.test_run_e2e import learner_files
    for rel, text in learner_files().items():
        safefs.write_text(repo, rel, text)
    generate.write_indexes(repo)
    public.write(repo, public.render_rights(repo))


@pytest.fixture
def setup(repo, make_figure, fake_local):
    brief, candidate = make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    return fake_local(repo), brief


def test_accepted_figure_is_inserted_once_with_the_reviewer_model(setup, repo):
    local, brief = setup
    lines = []
    code = close.close(local, repo, None, lines.append)
    assert code in (0, 1)                       # 1 only from the content check of the tiny page
    assert "beillesztve: physics/forces" in lines
    text = safefs.read_text(repo, PAGE)
    assert "<!-- figure: forces -->" not in text and "school-notes:generated figure-forces" in text
    evidence = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
    assert evidence["verifier"] == "model-x/high" and evidence["verdict"]["observed"] == ACCEPT["observed"]
    before = tree(repo)
    close.close(local, repo, None, lambda *_: None)
    assert tree(repo) == before                 # a repeated close changes nothing


def test_figure_without_accept_is_not_inserted(repo, make_figure, fake_local):
    make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}],
            {"forces": {**ACCEPT, "verdict": "reject"}})
    lines = []
    close.close(fake_local(repo), repo, None, lines.append)
    assert "nincs accept, nem illesztem be: physics/forces" in lines
    assert "<!-- figure: forces -->" in safefs.read_text(repo, PAGE)


def test_invalidated_verdict_without_recheck_accept_stops_and_deletes_nothing(setup, repo):
    local, _ = setup
    close.close(local, repo, None, lambda *_: None)
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("Two forces act.", "Three forces act."))
    verdicts = safefs.read_bytes(repo, insert.VERDICTS)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any(line.startswith("STOP") for line in lines) and f"  {PAGE}#forces" in lines
    assert safefs.read_bytes(repo, insert.VERDICTS) == verdicts
    handoff(repo, rechecks=[{"id": "forces", "page": PAGE, "anchor": "Forces", "asset": "x"}],
            recheck={"forces": {**ACCEPT, "verdict": "reject", "defects": [
                {"location": "a", "observed": "b", "expected": "c", "severity": "hiba"}]}})
    assert close.close(local, repo, None, lambda *_: None) == close.STOP


def test_recheck_accept_renews_the_key(setup, repo):
    local, _ = setup
    close.close(local, repo, None, lambda *_: None)
    safefs.write_text(repo, PAGE, safefs.read_text(repo, PAGE).replace("Two forces act.", "Three forces act."))
    handoff(repo, rechecks=[{"id": "forces", "page": PAGE, "anchor": "Forces", "asset": "x"}],
            recheck={"forces": {**ACCEPT, "observed": "Still two arrows."}})
    lines = []
    assert close.close(local, repo, None, lines.append) != close.STOP
    assert "ítélet megújítva (újranézés): physics/forces" in lines
    assert not insert.invalidated(repo)
    assert "<!-- figure: forces -->" not in safefs.read_text(repo, PAGE)
    assert safefs.read_json(repo, "docs/evidence/media/forces/figure.json")["verdict"]["observed"] == "Still two arrows."


def test_close_writes_no_decision_record(setup, repo):
    local, _ = setup
    close.close(local, repo, None, lambda *_: None)
    for rel in safefs.walk_files(repo):
        if rel.endswith(".md"):
            assert "by: owner" not in safefs.read_text(repo, rel)


def test_check_mode_leaves_the_working_copy_untouched(setup, repo):
    local, _ = setup
    before = tree(repo)
    lines = []
    close.run(local, None, check=True, out=lines.append)
    assert tree(repo) == before
    assert any(line.startswith("--check: a lezárás") for line in lines)
    assert f"  {PAGE}" in lines and "  docs/evidence/media/forces/figure.json" in lines


def test_subject_filter(setup, repo):
    local, _ = setup
    with pytest.raises(SystemExit):
        close.close(local, repo, ["chemistry"], lambda *_: None)
    lines = []
    close.close(local, repo, ["physics"], lines.append)
    assert "beillesztve: physics/forces" in lines


def test_svg_receipt_run_id_is_dated_and_per_subject(repo, make_figure):
    brief, candidate = make_figure()
    safefs.write_text(repo, "wiki/assets/physics/forces.svg", "<svg/>")
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", {**candidate, "asset": "wiki/assets/physics/forces.svg"})
    changed = []
    close.svg_receipts(repo, [("physics", {"id": "forces"})], changed)
    data = json.loads(safefs.read_text(repo, "docs/evidence/media/writer-svg.json"))
    assert data["svgs"][0]["run_id"] == f"helyi-{today()}-physics" and changed
