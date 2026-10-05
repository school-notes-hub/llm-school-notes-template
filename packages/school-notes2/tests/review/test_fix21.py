"""Targeted nightly input and results enforce the repair boundary."""

from school_notes2.review import topic_input, topic_result
from school_notes2.state import safefs
from .test_topics import prepare, FIX
from .conftest import sh


def test_targeted_input_and_outside_finding(tmp_path, repos):
    page = "wiki/a.md"
    repos.commit({page: "# A\n\nUntouched.\n\nBad.\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({page: "# A\n\nUntouched.\n\nFixed.\n"}, FIX)
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    folder = task.dir / "input"
    assigned = topic_input.prepare(repos.repo, repos.wt_path, task, unit, folder)
    value = safefs.read_json(folder, "input.json")
    assert value["mode"] == "targeted" and not value["pages"] and not value["sources"]
    assert value["changed_lines"][page] == [{"line": 5, "text": "Fixed."}]
    findings = [{"file": page, "quote": quote, "problem": "Wrong", "relates_to": None}
                for quote in ["Untouched.", "Fixed."]]
    task.update(topic_results=[{"unit": unit, "input": assigned, "receipt": {
        "status": "reviewed", "review": {"findings": findings, "hits": []}}}])
    result = topic_result.assemble(task, repos.repo, repos.wt_path)
    assert [f["quote"] for f in result["findings"]] == ["Fixed."]
    assert result["findings"][0]["chain"] == 1
    assert len(result["owner_notes"]) == 1 and "Untouched." in result["owner_notes"][0]
    assert topic_result.assemble(task, repos.repo, repos.wt_path) == result


def test_targeted_figures_skip_unchanged_embeddings(tmp_path, repos):
    from school_notes2.review import night_figures
    page, asset = "wiki/a.md", "wiki/assets/a.png"
    text = "# A\n\n![Ábra](assets/a.png)\n\nBad.\n"
    repos.commit({page: text, asset: b"old"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({page: text.replace("Bad.", "Fixed.")}, FIX)
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    assert night_figures.targeted(repos.repo, repos.wt_path, unit, []) == []
    assert len(night_figures.targeted(repos.repo, repos.wt_path, unit, [{"file": asset}])) == 1
    safefs.write_bytes(repos.wt_path, asset, b"new")
    assert len(night_figures.targeted(repos.repo, repos.wt_path, unit, [])) == 1


def test_migration_uses_real_git_history(repos, git_factory):
    from school_notes2.figures import migrate_pending, pending
    import json
    brief = {"id": "header", "kind": "banner", "page": "wiki/a.md", "anchor": "A",
             "purpose": "A", "must_show": [], "avoid_misreading": "A", "taught_conventions": [],
             "text_complete_without_figure": True}
    entry = {"commission": brief, "status": "pending", "runs": 2, "run_ids": ["a", "b"],
             "owner_required": False, "defects": [{"location": "text", "observed": "small", "expected": "large"}]}
    repos.commit({pending.PATH: json.dumps([entry]), "wiki/a.md": "<!-- figure: header -->\n# A\n"})
    entry["defects"] = [{"location": "header", "observed": "nem készült új jelölt", "expected": "new"}]
    repos.commit({pending.PATH: json.dumps([entry])})
    migrate_pending.migrate(repos.laptop, state_dir=repos.laptop.parent / "state",
                            repo=git_factory(repos.laptop / ".git", repos.laptop))
    restored = pending.load(repos.laptop)[0]
    assert restored["runs"] == 0 and restored["defects"][0]["observed"] == "small"
