"""Nightly follows only run/chat author changes, never repair or maintenance."""

import pytest

from school_notes2.flows import night_topics
from school_notes2.llm import launch
from school_notes2.review import topics
from .conftest import sh
from .test_topics import context, prepare


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("message", ["fix\n\nSchool-Notes-Run: fix", "repair\n\nSchool-Notes-Run: repair",
                                      "migráció", "⏳-frissítés", "közös szabályok frissítése", "tool"])
def test_no_new_material_no_llm(tmp_path, repos, log, monkeypatch, learner, message):
    repos.commit({"wiki/a.md": "# A\n\nRégi.\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\nVáltozott.\n", "instructions/example.md": "Szabály."}, message)
    task, ctx = prepare(tmp_path, repos, learner), context(tmp_path, repos, log, learner)
    assert task.get("units") == []
    monkeypatch.setattr(launch, "run_headless", lambda *a, **kw: pytest.fail("no nightly LLM without new material"))
    night_topics.run(ctx, task)
    assert task.get("all_topics_done") and task.get("topic_results", []) == []


@pytest.mark.parametrize("mode", ["run", "chat"])
def test_tagged_material_full_final_state_once(tmp_path, repos, mode):
    repos.commit({"wiki/a.md": "# A\n\nRégi.\n", "wiki/b.md": "# B\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\nÚj anyag.\n"}, f"anyag\n\nSchool-Notes-Run: {mode}")
    head = repos.commit({"wiki/a.md": "# A\n\nJavított új anyag.\n", "wiki/b.md": "# B\n\nJavítás.\n"}, "fix\n\nSchool-Notes-Run: fix")
    task = prepare(tmp_path, repos)
    assert [(u["topic"], u["mode"]) for u in task.get("units")] == [("wiki/a.md", "full")]
    assert "Javított új anyag." in topics.patch(repos.repo, task.get("units")[0], head)


def test_run_tool_only_does_not_trigger(tmp_path, repos):
    repos.commit({"wiki/a.md": "# A\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\n<!-- school-notes:generated pending -->\n⏳\n<!-- /school-notes:generated -->\n"})
    assert prepare(tmp_path, repos).get("units") == []


def test_saved_targeted_assignment_is_retired_on_resume(tmp_path, repos):
    from school_notes2.review import nightly
    repos.commit({"wiki/a.md": "Régi.\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "Javított.\n"}, "fix\n\nSchool-Notes-Run: fix")
    task = prepare(tmp_path, repos)
    task.update(material_policy=None, units=[{"topic": "wiki/a.md", "mode": "targeted"}])
    nightly.resume_prepared(task, repos.repo, repos.wt, lambda *a: [])
    assert task.get("units") == [] and task.get("material_policy") == 1


@pytest.mark.parametrize("material", [["wiki/a.md"], []])
def test_package_p4_backlog_is_not_nightly_material(tmp_path, repos, material):
    import json
    repos.commit({"wiki/a.md": "# A\n\nRégi.\n", "wiki/b.md": "# B\n\nHátralék.\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({"wiki/a.md": "# A\n\nÚj anyag.\n", "wiki/b.md": "# B\n\nJavított hátralék.\n"},
                 "csomag\n\nSchool-Notes-Run: run\nSchool-Notes-Material: " + json.dumps(material))
    assert [u["topic"] for u in prepare(tmp_path, repos).get("units")] == material
