import json

import pytest

from school_notes2.figures import insert
from school_notes2.local import close, done, figure_close
from school_notes2.local.common import today
from school_notes2.state import safefs
from tests.local.conftest import git

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


def edit(repo, old, new, page=PAGE):
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace(old, new))


def quiet(*_):
    pass


RECHECK = [{"id": "forces", "page": PAGE, "anchor": "Forces", "asset": "wiki/assets/physics/forces.png"}]


@pytest.fixture(autouse=True)
def learner_tree(repo):
    from school_notes2.wiki import generate, public
    from tests.local.conftest import learner_files
    from tests.wiki.conftest import INDEX
    files = learner_files()
    files["tools/subjects.json"] = json.dumps({"subjects": {
        "proba": {"name": "Próba", "emoji": "🧪"}, "physics": {"name": "Physics", "emoji": "🧲"},
        "chemistry": {"name": "Chemistry", "emoji": "⚗️"}}})
    for subject, page, title in (("physics", PAGE, "Forces"), ("chemistry", "wiki/chemistry/acid.md", "Acid")):
        files[f"wiki/{subject}/index.md"] = INDEX.replace("Próba", subject.title())
        files[page] = (f"---\ntitle: {title}\ndescription: Two forces\ntype: topic\nchapter: alapok\n"
                       "order: 10\n---\n# Forces\n\nTwo forces act.\n\n")
    for rel, text in files.items():
        safefs.write_text(repo, rel, text)
    safefs.write_text(repo, ".gitignore", ".school-notes/\n")
    generate.write_indexes(repo)
    public.write(repo, public.render_rights(repo))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")


@pytest.fixture
def setup(repo, make_figure, fake_local):
    brief, candidate = make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    local = fake_local(repo)
    assert close.snapshot(local, None, None, quiet) == 0
    return local, brief


def inserted(repo, local):
    assert close.close(local, repo, None, quiet) == 0


def test_accepted_figure_is_inserted_once_by_the_owners_fixed_reviewer(setup, repo):
    local, brief = setup
    lines = []
    assert close.close(local, repo, None, lines.append) == 0
    assert "beillesztve: physics/forces" in lines
    text = safefs.read_text(repo, PAGE)
    assert "<!-- figure: forces -->" not in text and "school-notes:generated figure-forces" in text
    evidence = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
    assert evidence["verifier"] == close.REVIEWER == "claude-opus-5-5/high"   # not the config's model-x
    assert evidence["verdict"]["key"] == json.loads(
        safefs.read_text(repo, ".school-notes/out/physics/keys.json"))["forces"]
    before = tree(repo)
    assert close.close(local, repo, None, quiet) == 0
    assert tree(repo) == before                 # a repeated close changes nothing


def test_snapshot_writes_keys_and_the_subjects_diff(setup, repo):
    patch = safefs.read_text(repo, ".school-notes/out/physics/diff.patch")
    assert "wiki/physics/forces.md" in patch and "+<!-- figure: forces -->" in patch
    assert "wiki/assets/physics/forces.png" in patch


def test_figure_without_accept_is_not_inserted(setup, repo):
    local, _ = setup
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}],
            {"forces": {**ACCEPT, "verdict": "reject"}})
    lines = []
    close.close(local, repo, None, lines.append)
    assert "nincs accept, nem illesztem be: physics/forces" in lines
    assert "<!-- figure: forces -->" in safefs.read_text(repo, PAGE)


def test_accept_without_a_snapshot_stops_before_writing(setup, repo):
    local, _ = setup
    safefs.unlink(repo, ".school-notes/out/physics/keys.json")
    before = tree(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert lines[0] == "STOP (nem írtam semmit):" and tree(repo) == before


def test_section_changed_in_the_fix_round_without_confirmation_stops(setup, repo):
    local, _ = setup
    edit(repo, "Two forces act.", "Three forces act.")            # the fix round touched the section
    before = tree(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any("physics/forces: az accept nem erre a változatra szól" in line for line in lines)
    assert tree(repo) == before
    assert close.snapshot(local, None, ["forces"], quiet) == 0     # the confirmation pass saw it
    inserted(repo, local)


def test_replaces_mismatch_with_the_commission_stops(setup, repo):
    local, _ = setup
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": "wiki/assets/physics/old.png"}],
            {"forces": ACCEPT})
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any("replaces" in line for line in lines)


def test_invalidated_verdict_without_recheck_accept_stops_and_deletes_nothing(setup, repo):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")
    verdicts = safefs.read_bytes(repo, insert.VERDICTS)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any(line.startswith("STOP") for line in lines) and f"  {PAGE}#forces" in lines
    assert safefs.read_bytes(repo, insert.VERDICTS) == verdicts
    handoff(repo, rechecks=RECHECK, recheck={"forces": {**ACCEPT, "verdict": "reject", "defects": [
        {"location": "a", "observed": "b", "expected": "c", "severity": "hiba"}]}})
    close.snapshot(local, None, None, quiet)
    assert close.close(local, repo, None, quiet) == close.STOP
    assert safefs.read_bytes(repo, insert.VERDICTS) == verdicts


def test_recheck_accept_renews_once_and_a_second_edit_stops(setup, repo):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")
    handoff(repo, rechecks=RECHECK, recheck={"forces": {**ACCEPT, "observed": "Still two arrows."}})
    close.snapshot(local, None, None, quiet)
    lines = []
    assert close.close(local, repo, None, lines.append) == 0
    assert "ítélet megújítva (újranézés): physics/forces" in lines
    assert not insert.invalidated(repo)
    assert safefs.read_json(repo, "docs/evidence/media/forces/figure.json")["verdict"]["observed"] == "Still two arrows."
    page = safefs.read_text(repo, PAGE)
    assert "<!-- figure: forces -->" not in page
    edit(repo, "Three forces act.", "Four forces act.")             # edited again, no new review
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any("az újranézési accept nem erre a szövegre szól" in line for line in lines)


def test_interrupted_renewal_resumes_and_leaves_no_marker(setup, repo, monkeypatch):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")
    handoff(repo, rechecks=RECHECK, recheck={"forces": ACCEPT})
    close.snapshot(local, None, None, quiet)
    # a temporary marker the 0.1.0 renewal could leave behind after an interruption
    end = "<!-- /school-notes:generated -->"
    text = safefs.read_text(repo, PAGE)
    start = text.index("<!-- school-notes:generated figure-forces -->")
    stop = text.index(end, start) + len(end)
    safefs.write_text(repo, PAGE, text[:stop] + "\n\n<!-- figure: forces -->" + text[stop:])

    def killed(*a, **k):
        raise OSError("killed")
    monkeypatch.setattr(insert, "_record_verdict", killed)
    with pytest.raises(OSError):
        close.close(local, repo, None, quiet)
    monkeypatch.undo()
    assert close.close(local, repo, None, quiet) == 0
    page = safefs.read_text(repo, PAGE)
    assert "<!-- figure: forces -->" not in page and page.count("figure-forces -->") == 1
    assert not insert.invalidated(repo)


def test_a_figure_gone_from_its_page_stops_and_keeps_its_verdict(setup, repo):
    local, _ = setup
    inserted(repo, local)
    text = safefs.read_text(repo, PAGE)
    start = text.index("<!-- school-notes:generated figure-forces -->")
    end = text.index("<!-- /school-notes:generated -->", start) + len("<!-- /school-notes:generated -->")
    safefs.write_text(repo, PAGE, text[:start] + text[end:])
    handoff(repo)
    lines = []
    assert close.close(local, repo, None, lines.append) == close.STOP
    assert any("beillesztett ábra eltűnt a lapról" in line for line in lines)
    assert any(r.get("id") == "forces" for r in safefs.read_json(repo, insert.VERDICTS, []))
    assert dict(done.problems(repo))["beillesztett ábra eltűnt a lapról"] == [f"{PAGE}#forces"]


def test_close_writes_no_decision_record(setup, repo):
    local, _ = setup
    inserted(repo, local)
    for rel in safefs.walk_files(repo):
        if rel.endswith(".md"):
            assert "by: owner" not in safefs.read_text(repo, rel)


def test_check_mode_leaves_the_working_copy_untouched(setup, repo):
    local, _ = setup
    before = tree(repo)
    lines = []
    assert close.run(local, None, check=True, out=lines.append) == 0
    assert tree(repo) == before
    assert any(line.startswith("--check: a lezárás") for line in lines)
    assert f"  {PAGE}" in lines and "  docs/evidence/media/forces/figure.json" in lines


def test_subject_scope_of_the_stop_checks(setup, repo, make_figure):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")              # physics: invalidated, no recheck
    make_figure(fid="acid", page="wiki/chemistry/acid.md")
    handoff(repo, [{"id": "acid", "page": "wiki/chemistry/acid.md", "route": "figure", "replaces": None}],
            {"acid": ACCEPT}, subject="chemistry")
    close.snapshot(local, ["chemistry"], None, quiet)
    with pytest.raises(close.Refused):
        close.close(local, repo, ["biology"], quiet)
    lines = []
    assert close.close(local, repo, ["chemistry"], lines.append) == 1   # not STOP; done stays strict
    assert "beillesztve: chemistry/acid" in lines
    assert "érvénytelenedett ábraítélet: 1" in lines
    assert close.close(local, repo, None, quiet) == close.STOP


def test_svg_receipt_run_id_is_dated_and_per_subject(repo, make_figure):
    brief, candidate = make_figure()
    safefs.write_text(repo, "wiki/assets/physics/forces.svg", "<svg/>")
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", {**candidate, "asset": "wiki/assets/physics/forces.svg"})
    changed = []
    figure_close.svg_receipts(repo, [("physics", {"id": "forces"})], changed)
    data = json.loads(safefs.read_text(repo, "docs/evidence/media/writer-svg.json"))
    assert data["svgs"][0]["run_id"] == f"helyi-{today()}-physics" and changed
