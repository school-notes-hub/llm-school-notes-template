"""sn 0.3.9: a lesson-line edit keeps a figure's verdict (lesson and textbook lines are out of the
key; the sn 0.3.8 key is accepted and rekeyed by `sn close`); a recheck keeps the image
description; a commission whose section is gone is reported. Each test fails on 3c0b811."""

from school_notes2.figures import context, insert
from school_notes2.local import close
from school_notes2.state import safefs
from school_notes2.wiki import check
from tests.local.test_close import ACCEPT, PAGE, RECHECK, edit, handoff, inserted, learner_tree, quiet, setup  # noqa: F401

EVIDENCE = "docs/evidence/media/forces/figure.json"


def test_a_lesson_line_edit_keeps_the_figure_verdict(setup, repo):
    local, _ = setup
    edit(repo, "Two forces act.", "Two forces act.\n\n<sub>🗓️ Óra: szept. 3. · 🔖 Tankönyv: 2. lecke</sub>")
    close.snapshot(local, None, None, quiet)
    inserted(repo, local)
    assert insert.invalidated(repo) == []
    edit(repo, "<sub>🗓️ Óra: szept. 3. · 🔖 Tankönyv: 2. lecke</sub>",
         '<sub>🗓️ Óra: <span class="study-when study-when-unsure" title="Dátum nélküli óra: szept. 1–5.">~szept. eleje</span></sub>')
    assert insert.invalidated(repo) == []
    edit(repo, "Two forces act.", "Three forces act.")                 # the text itself still counts
    assert [r["id"] for r in insert.invalidated(repo)] == ["forces"]


def test_a_verdict_with_the_old_key_stays_valid_and_close_rekeys_it(setup, repo):
    local, brief = setup
    edit(repo, "Two forces act.", "Two forces act.\n\n<sub>🗓️ Óra: szept. 3.</sub>")
    close.snapshot(local, None, None, quiet)
    inserted(repo, local)
    records = safefs.read_json(repo, insert.VERDICTS)
    [record] = [r for r in records if r.get("role") == "figure-review"]
    old = context.verdict_key(repo, record["commission"], record["candidate"], legacy=True)
    new = record["key"]
    assert old != new
    record["key"] = old                                             # a verdict recorded by sn 0.3.8
    safefs.write_json(repo, insert.VERDICTS, records)
    evidence = safefs.read_json(repo, EVIDENCE)
    safefs.write_json(repo, EVIDENCE, {**evidence, "verdict": {**evidence["verdict"], "key": old}})
    assert insert.invalidated(repo) == []                            # valid before any close
    assert close.close(local, repo, None, quiet) == 0
    assert [r["key"] for r in safefs.read_json(repo, insert.VERDICTS) if r.get("role") == "figure-review"] == [new]
    assert safefs.read_json(repo, EVIDENCE)["verdict"]["key"] == new


def test_a_recheck_keeps_the_image_description(setup, repo):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")
    handoff(repo, rechecks=RECHECK, recheck={"forces": {**ACCEPT, "observed": "Date only, figure unchanged."}})
    close.snapshot(local, None, None, quiet)
    assert close.close(local, repo, None, quiet) == 0
    evidence = safefs.read_json(repo, EVIDENCE)
    assert evidence["verdict"]["observed"] == "Two opposite arrows."
    assert [r["observed"] for r in evidence["rechecks"]] == ["Date only, figure unchanged."]


def test_a_commission_whose_section_is_gone_is_reported(setup, repo):
    local, _ = setup
    inserted(repo, local)
    edit(repo, "# Forces\n", "# Erők\n")
    [found] = [i for i in check.check_files(repo, [PAGE], fix=False) if "commission names the section" in i["message"]]
    assert found["severity"] == "error"
    assert "figure forces" in found["message"] and "„Forces”" in found["message"]
    assert "docs/evidence/media/forces/figure.json" in found["message"]
