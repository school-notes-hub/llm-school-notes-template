"""sn 0.3.6: `sn close` writes the pass's `wiki/log.md` entries from `adatok.json` `log`, `sn done`
reports a finished pass whose hand-over had none, and `sn fetch` records the day it placed a
package (the upper bound of an undated catch-up lesson). Each test fails on 4c1e22c."""

import pytest

from school_notes2.local import close, done
from school_notes2.state import safefs
from tests.local.test_close import handoff, learner_tree, quiet  # noqa: F401 - the learner repo
from tests.local.test_fetch import world  # noqa: F401 - the fake Drive

OUT = ".school-notes/out"


def pass_with_log(repo, subject="physics", entries=None):
    handoff(repo, subject=subject)
    safefs.write_json(repo, f"{OUT}/{subject}/keys.json", {})
    data = {"writer": "claude-opus-5-5/high"}
    if entries is not None:
        data["log"] = entries
    safefs.write_json(repo, f"{OUT}/{subject}/adatok.json", data)


def section(text, day):
    head = f"## {day}\n\n"
    start = text.index(head) + len(head)
    end = text.find("\n## ", start)
    return text[start:end if end >= 0 else len(text)]


def entries(text, day):
    return [line for line in section(text, day).splitlines() if line.startswith("* **")]


def test_close_writes_the_log_entries_under_todays_heading_newest_first(repo, fake_local):
    old = safefs.read_text(repo, "wiki/log.md")
    pass_with_log(repo, "physics", [{"kind": "Update", "text": "Fizika: [Forces](physics/forces.md) bővült."}])
    pass_with_log(repo, "chemistry", [{"kind": "Creation", "text": "Kémia: új lap."},
                                      {"kind": "Update", "text": "Kémia: javítás."}])
    day = close.today()
    assert close.run(fake_local(repo), None, out=quiet) == 0
    text = safefs.read_text(repo, "wiki/log.md")
    # passes in retirement order (subject name order), each newest on top: physics, then chemistry
    assert entries(text, day) == ["* **Update**: Fizika: [Forces](physics/forces.md) bővült.",
                                  "* **Creation**: Kémia: új lap.", "* **Update**: Kémia: javítás."]
    assert old.splitlines()[0] == text.splitlines()[0]
    pass_with_log(repo, "physics", [{"kind": "Update", "text": "Fizika: második menet."}])
    assert close.run(fake_local(repo), None, out=quiet) == 0
    text = safefs.read_text(repo, "wiki/log.md")
    assert entries(text, day)[0] == "* **Update**: Fizika: második menet."
    assert close.run(fake_local(repo), None, out=quiet) == 0          # nothing left to close: no change
    assert safefs.read_text(repo, "wiki/log.md") == text


def test_a_log_link_outside_the_wiki_is_a_stop(repo, fake_local):
    pass_with_log(repo, "physics", [{"kind": "Update", "text": "Rossz: [lap](physics/nincs.md)."}])
    lines = []
    assert close.run(fake_local(repo), None, out=lines.append) == 2
    assert any("log: physics/nincs.md is not a wiki page" in line for line in lines)


def test_done_reports_a_finished_pass_without_log_until_noted_by_hand(repo, fake_local):
    pass_with_log(repo, "physics", None)
    lines = []
    close.run(fake_local(repo), None, out=lines.append)
    assert any("nincs `log`" in line for line in lines)
    [found] = dict(done.problems(repo))["lezárt menet naplóbejegyzés nélkül"]
    assert found.startswith("wiki/physics/: .school-notes/done/helyi-")
    base = found.split(": ", 1)[1].split(" ", 1)[0]
    closed = safefs.read_json(repo, f"{base}/closed.json")
    safefs.write_json(repo, f"{base}/closed.json", {**closed, "log_by_hand": "kézzel beírva"})
    assert dict(done.problems(repo))["lezárt menet naplóbejegyzés nélkül"] == []


@pytest.mark.parametrize("entries", [[{"kind": "Note", "text": "x"}], [{"kind": "Update", "text": "a\nb"}],
                                     [{"kind": "Update", "text": "  "}]])
def test_the_log_entry_form_is_fixed(entries):
    from school_notes2.schemas import validate
    validate("handoff-data", {"writer": "w/high", "log": [{"kind": "Creation", "text": "Új lap."}]})
    with pytest.raises(ValueError):
        validate("handoff-data", {"writer": "w/high", "log": entries})


def test_the_source_manifest_records_the_day_the_package_was_placed(world):
    import json
    from school_notes2.local import common, fetch
    assert fetch.run(world["local"], apply=True, out=quiet) == 0
    data = json.loads((world["repo"] / "sources/matek/2026-10-07/sn-fetch.json").read_text())
    assert data["package"]["placed"] == common.today()
