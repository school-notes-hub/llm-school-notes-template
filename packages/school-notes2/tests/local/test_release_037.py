"""sn 0.3.7: the log of a pass is written once, by its pass id, only for a hand-over the close
retires; an interrupted close is repaired; a pass without `log` holds only its own subject (the
0.3.6 review: Astra A3, A9, A10; Opus O1, O2, O12). Each test fails on 1bbf485."""

from school_notes2.local import close, done, wiki_log
from school_notes2.state import safefs
from tests.local.test_close import learner_tree, quiet  # noqa: F401 - the learner repo
from tests.local.test_release_036 import entries, pass_with_log

OUT, DONE = ".school-notes/out", ".school-notes/done"


def log(repo):
    return safefs.read_text(repo, "wiki/log.md")


def test_a_stopped_close_writes_no_log_and_the_retry_writes_it_once(repo, fake_local, monkeypatch):
    pass_with_log(repo, "physics", [{"kind": "Update", "text": "Fizika: egy menet."}])
    before = log(repo)
    monkeypatch.setattr(close.figs, "figure_blockers", lambda *a: ["STOP for the test"])
    assert close.run(fake_local(repo), None, out=quiet) == 2
    assert log(repo) == before                                      # nothing retired, nothing logged
    monkeypatch.undo()
    monkeypatch.setattr(close, "today", lambda: "2026-10-08")       # the retry is on another day
    assert close.run(fake_local(repo), None, out=quiet) == 0
    assert log(repo).count("Fizika: egy menet.") == 1
    assert close.run(fake_local(repo), None, out=quiet) == 0
    assert log(repo).count("Fizika: egy menet.") == 1


def test_two_passes_with_the_same_wording_are_both_logged(repo, fake_local):
    same = [{"kind": "Update", "text": "Kis javítás."}]
    pass_with_log(repo, "physics", same)
    pass_with_log(repo, "chemistry", same)
    assert close.run(fake_local(repo), None, out=quiet) == 0
    assert log(repo).count("* **Update**: Kis javítás.") == 2
    assert log(repo).count("<!-- pass: helyi-") == 2


def test_a_close_interrupted_after_the_move_is_repaired(repo, fake_local, monkeypatch):
    pass_with_log(repo, "physics", [{"kind": "Update", "text": "Fizika: megszakadt."}])
    def boom(*a):
        raise KeyboardInterrupt
    monkeypatch.setattr(wiki_log, "write_pass", boom)
    try:
        close.run(fake_local(repo), None, out=quiet)
    except KeyboardInterrupt:
        pass
    [retired] = safefs.listdir(repo, DONE)
    assert safefs.read_json(repo, f"{DONE}/{retired}/closed.json")["logged"] is False
    assert "Fizika: megszakadt." not in log(repo)
    assert dict(done.problems(repo))["lezárt menet naplóbejegyzés nélkül"]      # reported meanwhile
    monkeypatch.undo()
    lines = []
    close.run(fake_local(repo), None, out=lines.append)
    assert log(repo).count("Fizika: megszakadt.") == 1 and any("pótolva" in line for line in lines)
    assert dict(done.problems(repo))["lezárt menet naplóbejegyzés nélkül"] == []


def test_a_pass_without_log_holds_only_its_own_subject(repo, fake_local):
    pass_with_log(repo, "physics", None)
    close.run(fake_local(repo), None, out=quiet)                     # physics retired without log
    assert close.open_subjects(repo) == {"physics"}
    pass_with_log(repo, "chemistry", [{"kind": "Update", "text": "Kémia."}])
    close.run(fake_local(repo), ["chemistry"], out=quiet)
    assert not safefs.is_dir(repo, f"{OUT}/chemistry")                # retired despite physics
    pass_with_log(repo, "chemistry", [{"kind": "Update", "text": "Kémia 2."}])
    close.run(fake_local(repo), None, out=quiet)
    assert not safefs.is_dir(repo, f"{OUT}/chemistry")
    assert entries(log(repo), close.today())[0] == "* **Update**: Kémia 2."
