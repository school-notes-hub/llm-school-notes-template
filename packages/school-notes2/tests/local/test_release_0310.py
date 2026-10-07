"""sn 0.3.10: the legacy-key rekey runs first in `sn close` and alone as `--rekey`, never over a
content change; inserted figures without a `verdicts.json` record are checked and reported;
`--dates` rewrites only date spans and no figure needs a recheck for it. Each test fails on ce7d7a5."""

from school_notes2.figures import context, insert
from school_notes2.local import close, done
from school_notes2.state import safefs
from tests.local.test_close import PAGE, edit, inserted, learner_tree, quiet, setup, tree  # noqa: F401

EVIDENCE = "docs/evidence/media/forces/figure.json"


def legacy(repo, local):
    """An inserted figure whose verdict carries the sn 0.3.8 key of the content as it is now."""
    edit(repo, "Two forces act.", "Two forces act.\n\n<sub>🗓️ Óra: szept. 3.</sub>")
    close.snapshot(local, None, None, quiet)
    inserted(repo, local)
    records = safefs.read_json(repo, insert.VERDICTS)
    record = next(r for r in records if r.get("role") == "figure-review")
    old, new = context.verdict_key(repo, record["commission"], record["candidate"], legacy=True), record["key"]
    record["key"] = old
    safefs.write_json(repo, insert.VERDICTS, records)
    evidence = safefs.read_json(repo, EVIDENCE)
    safefs.write_json(repo, EVIDENCE, {**evidence, "verdict": {**evidence["verdict"], "key": old}})
    return old, new


def keys(repo):
    return [r["key"] for r in safefs.read_json(repo, insert.VERDICTS) if r.get("role") == "figure-review"]


def test_the_rekey_runs_first_even_when_the_close_stops(setup, repo, monkeypatch):
    local, _ = setup
    old, new = legacy(repo, local)
    monkeypatch.setattr(close.figs, "figure_blockers", lambda *a: ["STOP for the test"])
    assert close.close(local, repo, None, quiet) == close.STOP
    assert keys(repo) == [new] and safefs.read_json(repo, EVIDENCE)["verdict"]["key"] == new


def test_rekey_alone_writes_only_the_keys_and_is_idempotent(setup, repo):
    local, _ = setup
    old, new = legacy(repo, local)
    before = tree(repo)
    assert close.rekey_only(local, quiet) == 0
    after = tree(repo)
    assert sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)) == [EVIDENCE, insert.VERDICTS]
    assert keys(repo) == [new]
    assert close.rekey_only(local, quiet) == 0 and tree(repo) == after


def test_a_legacy_key_over_a_real_content_change_is_not_renewed(setup, repo):
    local, _ = setup
    old, _ = legacy(repo, local)
    edit(repo, "Two forces act.", "Three forces act.")
    assert close.rekey_only(local, quiet) == 0
    assert keys(repo) == [old]
    assert [r["id"] for r in insert.invalidated(repo)] == ["forces"]


def test_an_inserted_figure_without_its_record_is_checked_and_reported(setup, repo):
    local, _ = setup
    inserted(repo, local)
    safefs.write_json(repo, insert.VERDICTS, [r for r in safefs.read_json(repo, insert.VERDICTS)
                                             if r.get("role") != "figure-review"])
    assert dict(done.problems(repo))["beillesztett ábra verdicts.json-rekord nélkül"] == [f"{PAGE}#forces"]
    assert insert.invalidated(repo) == []                       # its evidence key still holds
    edit(repo, "Two forces act.", "Three forces act.")
    assert [r["id"] for r in insert.invalidated(repo)] == ["forces"]
