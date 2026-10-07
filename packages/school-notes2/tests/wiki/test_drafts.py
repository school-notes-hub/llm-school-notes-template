"""Draft age follows received lessons, not incidental page edits."""

from datetime import date, timedelta


from school_notes2.wiki import check, drafts, frontmatter
from tests.wiki.conftest import write

REL = "wiki/proba/elso.md"
START = date(2026, 9, 1)


def start(repo):
    """A draft page as the VM tool left it: `draft_tracking` started on START."""
    text = frontmatter.set_keys((repo / REL).read_text(), {"status": "draft"})
    meta = frontmatter.split(text).meta
    new = frontmatter.set_keys(text, {drafts.KEY: drafts.tracking(meta, drafts.lesson_keys(repo)[REL], START)})
    write(repo, REL, new)
    return new


def test_draft_warns_after_two_weeks_and_a_stable_page_never(repo):
    text = start(repo)
    assert not drafts.warnings(repo, START + timedelta(days=14))
    assert drafts.warnings(repo, START + timedelta(days=15))[0][0] == REL
    write(repo, REL, frontmatter.set_keys(text, {"status": "stable"}))
    assert not drafts.warnings(repo, START + timedelta(days=30))


def test_new_undated_lesson_resets_timer_but_prose_edit_does_not(repo):
    text = start(repo)
    write(repo, REL, text + "\nTovábbi magyarázat.\n")
    assert drafts.warnings(repo, START + timedelta(days=15))
    old_log = "wiki/proba/2026-09-10-elso-jegyzet.md"
    new_log = "wiki/proba/2026-09-20-uj-jegyzet.md"
    write(repo, new_log, (repo / old_log).read_text())
    assert not drafts.warnings(repo, START + timedelta(days=15))


def test_check_limits_old_drafts_to_changed_pages_and_rejects_unknown_status(repo):
    start(repo)
    assert not check.check_files(repo, [], today=START + timedelta(days=15))
    found = check.check_files(repo, [REL], today=START + timedelta(days=15))
    assert [(i["file"], i["severity"]) for i in found] == [(REL, "warning")]
    write(repo, REL, frontmatter.set_keys((repo / REL).read_text(), {"status": "oops"}))
    assert any("status must" in i["message"] for i in check.errors(check.check_files(repo, [REL])))
