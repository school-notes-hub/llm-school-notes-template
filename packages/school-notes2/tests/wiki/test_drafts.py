"""Draft age follows received lessons, not incidental page edits."""

from datetime import date, timedelta

import pytest

from school_notes2.wiki import check, drafts, frontmatter, guard, markers
from tests.wiki.conftest import write
from tests.wiki.test_guard import run, snapshot

REL = "wiki/proba/elso.md"
START = date(2026, 9, 1)


def start(repo):
    text = frontmatter.set_keys((repo / REL).read_text(), {"status": "draft"})
    new = drafts.update(text, drafts.lesson_keys(repo)[REL], START)
    write(repo, REL, new)
    return new


def test_draft_notice_clock_and_status_removal(repo):
    text = start(repo)
    assert markers.read(text, "pending") == drafts.NOTICE
    assert text.index("![ábra]") < text.index("⏳")
    assert not drafts.warnings(repo, START + timedelta(days=14))
    assert drafts.warnings(repo, START + timedelta(days=15))[0][0] == REL
    assert drafts.update(text, drafts.lesson_keys(repo)[REL], START + timedelta(days=30)) == text
    stable = frontmatter.set_keys(text, {"status": "stable"})
    stable = drafts.update(stable, [], START + timedelta(days=30))
    assert drafts.KEY not in frontmatter.split(stable).meta
    assert "⏳" not in stable
    reopened = drafts.update(frontmatter.set_keys(stable, {"status": "draft"}), [], date(2026, 10, 1))
    assert frontmatter.split(reopened).meta[drafts.KEY]["since"] == "2026-10-01"


def test_new_undated_lesson_resets_timer_but_prose_edit_does_not(repo):
    text = start(repo)
    write(repo, REL, text + "\nTovábbi magyarázat.\n")
    assert drafts.warnings(repo, START + timedelta(days=15))
    old_log = "wiki/proba/2026-09-10-elso-jegyzet.md"
    new_log = "wiki/proba/2026-09-20-uj-jegyzet.md"
    write(repo, new_log, (repo / old_log).read_text())
    assert not drafts.warnings(repo, START + timedelta(days=15))
    new = drafts.update((repo / REL).read_text(), drafts.lesson_keys(repo)[REL], START + timedelta(days=15))
    write(repo, REL, new)
    assert frontmatter.split(new).meta[drafts.KEY]["since"] == "2026-09-16"
    assert not drafts.warnings(repo, START + timedelta(days=29))
    assert drafts.warnings(repo, START + timedelta(days=30))


def test_check_limits_old_drafts_to_changed_pages_and_rejects_unknown_status(repo):
    start(repo)
    assert not check.check_files(repo, [], today=START + timedelta(days=15))
    found = check.check_files(repo, [REL], today=START + timedelta(days=15))
    assert [(i["file"], i["severity"]) for i in found] == [(REL, "warning")]
    write(repo, REL, frontmatter.set_keys((repo / REL).read_text(), {"status": "oops"}))
    assert any("status must" in i["message"] for i in check.errors(check.check_files(repo, [REL])))


def test_writer_cannot_reset_draft_tracking(repo):
    text = start(repo)
    base = snapshot(repo)
    write(repo, REL, text.replace("2026-09-01", "2026-10-01"))
    for interactive in (False, True):
        assert run(repo, base, [(REL, "modified")], interactive=interactive)


@pytest.mark.parametrize("lessons", [None, 42, ["lesson"], [{"topics": 42}]])
def test_status_reports_malformed_lesson_metadata(repo, lessons):
    from school_notes2.flows.status import _drafts
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    write(repo, rel, frontmatter.set_keys((repo / rel).read_text(), {"lessons": lessons}))
    assert rel in _drafts(repo)["error"]
