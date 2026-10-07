"""sn 0.3.3 (fix round of 0.3.2, decisions F2, F3): the hand-overs this close read, per
subject, only when that subject's part succeeded; a failed move is recorded and a re-run goes
on. Each test fails on 9b85754."""

import pytest

from school_notes2.local import close
from school_notes2.state import safefs
from tests.local.test_close import edit, handoff, learner_tree, quiet  # noqa: F401
from tests.local.test_close_data import LOG, adatok, place, write_log

OUT = ".school-notes/out"
DONE = ".school-notes/done"


def snapshotted(repo, subject="physics"):
    handoff(repo, subject=subject)
    safefs.write_json(repo, f"{OUT}/{subject}/keys.json", {})
    # since 0.3.6 every pass hands over its log entry (`sn done` reports one without)
    if not safefs.is_file(repo, f"{OUT}/{subject}/adatok.json"):
        safefs.write_json(repo, f"{OUT}/{subject}/adatok.json", {
            "writer": "claude-opus-5-5/high", "log": [{"kind": "Update", "text": f"{subject}: menet."}]})


def done_dirs(repo):
    return safefs.listdir(repo, DONE) if safefs.is_dir(repo, DONE) else []


def test_a_subject_is_retired_despite_another_subjects_open_problem(repo, fake_local):
    snapshotted(repo)
    snapshotted(repo, "chemistry")
    edit(repo, "Two forces act.", "Two forces act.\n\n[broken](nincs.md)", page="wiki/chemistry/acid.md")
    lines = []
    assert close.run(fake_local(repo), None, out=lines.append) == 1
    assert safefs.listdir(repo, OUT) == ["chemistry"] and [d for d in done_dirs(repo) if d.endswith("-physics")]
    assert f"az átadás marad (tartalmi hiba a tantárgyban): {OUT}/chemistry" in lines


def test_a_full_close_leaves_a_hand_over_without_a_snapshot(repo, fake_local):
    snapshotted(repo)
    handoff(repo, subject="chemistry")                      # never snapshotted: an unfinished pass
    lines = []
    assert close.run(fake_local(repo), None, out=lines.append) == 0
    assert safefs.listdir(repo, OUT) == ["chemistry"]
    assert f"az átadás marad (nincs pillanatkép, befejezetlen menet): {OUT}/chemistry" in lines
    assert close.run(fake_local(repo), ["chemistry"], out=quiet) == 0     # named: the controller's word
    assert not safefs.listdir(repo, OUT)


def test_a_problem_that_names_no_subject_holds_every_hand_over(repo, fake_local):
    snapshotted(repo)
    safefs.write_text(repo, "wiki/index.md", safefs.read_text(repo, "wiki/index.md") + "\n[broken](nincs.md)\n")
    assert close.run(fake_local(repo), None, out=quiet) == 1
    assert safefs.listdir(repo, OUT) == ["physics"]


def test_only_the_hand_overs_read_at_the_start_are_retired(repo, fake_local, monkeypatch):
    """A2: a hand-over that arrives or changes during the close is never retired unprocessed."""
    snapshotted(repo)
    snapshotted(repo, "chemistry")
    report = close.done.report

    def meanwhile(repo_, out=print, git=None):
        safefs.write_json(repo, f"{OUT}/biology/keys.json", {})                       # arrives
        safefs.write_json(repo, f"{OUT}/chemistry/verdicts.json", {"x": {"verdict": "reject"}})  # changes
        return report(repo_, out, git)
    monkeypatch.setattr(close.done, "report", meanwhile)
    lines = []
    assert close.run(fake_local(repo), None, out=lines.append) == 0
    assert safefs.listdir(repo, OUT) == ["biology", "chemistry"]
    assert f"az átadás marad (a lezárás közben változott vagy eltűnt): {OUT}/chemistry" in lines


@pytest.mark.parametrize("failure", [OSError(18, "Invalid cross-device link"), KeyboardInterrupt()])
def test_a_failed_or_interrupted_move_is_recorded_and_a_re_run_goes_on(repo, fake_local, monkeypatch, failure):
    snapshotted(repo)
    snapshotted(repo, "chemistry")
    move = safefs.move

    def second_fails(root, src, dest):
        if src.endswith("/physics"):
            raise failure
        return move(root, src, dest)
    monkeypatch.setattr(safefs, "move", second_fails)
    local = fake_local(repo)
    if isinstance(failure, OSError):
        assert close.run(local, None, out=quiet) == 1
    else:
        with pytest.raises(KeyboardInterrupt):
            close.run(local, None, out=quiet)
    command, outcome, fields = local.records[-1]
    [chem] = done_dirs(repo)
    assert command == "close" and fields["moved"] == [chem] and chem.endswith("-chemistry")
    assert (outcome, fields["failed"]) == (("retire-failed", ["physics"]) if isinstance(failure, OSError)
                                           else ("error", []))
    monkeypatch.setattr(safefs, "move", move)
    lines = []
    assert close.run(fake_local(repo), ["chemistry", "physics"], out=lines.append) == 0
    assert lines[0].startswith("már elrakva, kihagyom: chemistry (.school-notes/done/helyi-")
    assert not safefs.listdir(repo, OUT) and len(done_dirs(repo)) == 2


def test_a_re_run_does_not_miss_a_retired_hand_overs_new_lesson_log(repo, fake_local):
    paths = place(repo)
    write_log(repo)
    adatok(repo, notes=[{"file": LOG, "pages": paths}], log=[{"kind": "Creation", "text": "Új óranapló."}])
    safefs.write_json(repo, f"{OUT}/physics/keys.json", {})
    assert close.run(fake_local(repo), None, out=quiet) == 0 and not safefs.listdir(repo, OUT)
    snapshotted(repo, "chemistry")                       # another subject, before the commit
    assert close.run(fake_local(repo), None, out=quiet) == 0    # the new lesson log is noted in done/
    lines = []
    assert close.run(fake_local(repo), ["physics"], out=lines.append) == 0
    assert lines[0].startswith("már elrakva, kihagyom: physics")
