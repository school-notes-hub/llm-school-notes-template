"""One nightly review end to end (plan 5.6, 6.9): fake reviewer, real Git, atomic push."""

import json
import subprocess

from school_notes2.flows import nightly as nightly_flow
from school_notes2.state import phase
from tests.e2e.test_run_e2e import show, world  # noqa: F401 - shared fixture

ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "L",
       "GIT_AUTHOR_EMAIL": "l@x", "GIT_COMMITTER_NAME": "L", "GIT_COMMITTER_EMAIL": "l@x"}


def laptop_commit(tmp_path, origin, rel, text):
    clone = tmp_path / "laptop"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, env=ENV)
    (clone / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "commit", "-qam", "laptop edit\n\nSchool-Notes-Run: chat"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=ENV)


def test_nightly_review_end_to_end(world, tmp_path, monkeypatch):
    ctx, origin, drive, package = world
    from school_notes2.notify import Mailer
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, msg: delivered.append(msg) or True)
    seed = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", f"--git-dir={origin}", "update-ref", "refs/heads/claude-reviewed", seed],
                   check=True)
    laptop_commit(tmp_path, origin, "wiki/proba/elso.md",
                  show(origin, "main:wiki/proba/elso.md") + "\nÚj bekezdés.\n")
    ctx.log = ctx.log.bind(run_id="previous-notes-run")
    assert nightly_flow.nightly(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    task = [t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review"][-1]
    assert task.phase == "done"
    assert len(delivered) == 1 and "éjszakai review" in delivered[0].get_content()
    assert "{" not in delivered[0].get_content()
    launches = [json.loads(line) for line in ctx.cfg.log_path.read_text().splitlines()
                if json.loads(line)["action"].startswith("llm.launch role=")]
    assert launches and all(event["run_id"] == task.run_id for event in launches)
    files = subprocess.run(["git", f"--git-dir={origin}", "ls-tree", "-r", "--name-only", "main",
                            "docs/review/"], capture_output=True, text=True).stdout.split()
    report = [f for f in files if f.endswith("-review.md")]
    assert report, files
    text = show(origin, f"main:{report[0]}")
    assert "R1: open" in text and "### R1" in text and "R2:" not in text
    assert "Régi sor gondja." in text  # A finding on an unchanged line is an owner note.
    reviewed = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "claude-reviewed", "main"],
                              capture_output=True, text=True).stdout.split()
    assert reviewed[0] == reviewed[1]          # quiet close: M=R
    assert nightly_flow.nightly(ctx) == 0      # nothing new: empty range, no call
    again = [t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review"]
    assert len(again) == 1
    assert subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip() == reviewed[1]
    assert nightly_flow.nightly(ctx) == 0      # the third night is still empty
    assert len([t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review"]) == 1
    assert len(delivered) == 1  # Empty nights add no mail.


def test_admin_only_commit_reaches_the_reviewer_but_gives_no_item(world, tmp_path, monkeypatch):
    """Owner, 2026-10-05: the reviewer decides from the diff; a tool-only change (here a ⏳
    block) cannot become an item, and a range without a wiki diff needs no call at all."""
    ctx, origin, drive, package = world
    seed = subprocess.run(["git", f"--git-dir={origin}", "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", f"--git-dir={origin}", "update-ref", "refs/heads/claude-reviewed", seed], check=True)
    laptop_commit(tmp_path, origin, "docs/review/index.md", "# Review\n\nadmin\n")
    assert nightly_flow.nightly(ctx) == 0
    assert not [t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review"]
    text = show(origin, "main:wiki/proba/elso.md")
    notice = "<!-- school-notes:generated pending -->\n⏳ Ezt az oldalt még ellenőrizzük.\n<!-- /school-notes:generated -->\n"
    clone = tmp_path / "laptop"
    (clone / "wiki/proba/elso.md").write_text(text + notice, encoding="utf-8")
    subprocess.run(["git", "-C", str(clone), "commit", "-qam", "tool notice\n\nSchool-Notes-Run: fix"], check=True, env=ENV)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=ENV)
    assert nightly_flow.nightly(ctx) == 0, ctx.cfg.log_path.read_text()[-2000:]
    task = [t for t in phase.all_tasks(ctx.task_root(), "benedek") if t.kind == "review"][-1]
    assert task.phase == "done"
    assert [c["run"] for c in json.loads((task.dir / "in/commits.json").read_text())] == ["chat", "fix"]
    review = json.loads((task.dir / "review.json").read_text())
    assert review["findings"] == [] and any("Hiányzik egy példa." in n for n in review["owner_notes"])


def test_nightly_without_marker_needs_owner(world):
    ctx, origin, drive, package = world
    assert nightly_flow.nightly(ctx) == 1
    assert "marker" in ctx.cfg.log_path.read_text() or "claude-reviewed" in ctx.cfg.log_path.read_text()
