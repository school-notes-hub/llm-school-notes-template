from pathlib import Path
import tomllib

from school_notes2.wiki.check import TYPOGRAPHY

ROOT = Path(__file__).resolve().parents[4]


def test_wording_keys_and_catch_up_typography():
    profile = (ROOT / "PROFILE.md").read_text()
    notice = next(line for line in profile.splitlines() if line.startswith("| catch-up notice |"))
    assert not TYPOGRAPHY.search(notice)
    for key in ("lesson-log heading", "lesson-log source line", "undated source lesson",
                "notebook correction request"):
        assert f"| {key} |" in profile
    structure = (ROOT / "instructions/wiki-structure.md").read_text()
    for key in ("lesson-log heading", "lesson-log source line", "undated source lesson"):
        assert f"*{key}*" in structure
    content = (ROOT / "instructions/content-and-curriculum.md").read_text()
    assert '*notebook correction request* from PROFILE *Wording*' in content
    assert "Not initialized yet" in profile


def test_handoff_is_executable_and_reviewer_does_not_ask_family():
    for file in ("media-workflows.md", "visual-policy.md", "school-notes-run.md"):
        text = (ROOT / "instructions" / file).read_text()
        assert "leave the marker and the commission; the tool queues it" in text
        assert "submit for independent figure review" not in text
        assert "submit to the independent figure checker" not in text
    workflows = (ROOT / "instructions/wiki-workflows.md").read_text()
    assert "before proposing a question to the writer" in workflows
    assert "before raising a question for the family" not in workflows


def test_example_reviewer_timeout_is_ninety_minutes():
    path = ROOT / "packages/school-notes2/src/school_notes2/ops/config.example.toml"
    data = tomllib.loads(path.read_text())
    assert data["roles"]["reviewer"]["timeout_s"] == 5400


def test_pending_figure_retry_uses_worktree_relative_paths():
    text = (ROOT / "instructions/school-notes-run.md").read_text()
    paragraph = next(p for p in text.split("\n\n") if p.startswith("For each `fetch.json.pending_figures`"))
    assert "restored commission at `.school-notes/figures/<id>.json`" in paragraph
    assert "write `.school-notes/figures/<id>/figure.json`" in paragraph
    assert "`figures/<id>/figure.json`" not in paragraph


def test_wording_migration_belongs_to_profile_release():
    import json
    version = json.loads((ROOT / "shared-files.json").read_text())["version"]
    assert f"**Template version**: `{version}`" in (ROOT / "PROFILE.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## {version} - " in changelog
    # The Wording keys were introduced by the 1.17.0 release and stay documented there.
    release = changelog.split("## 1.17.0 - ", 1)[1].split("\n## ", 1)[0]
    for key in ("lesson-log heading", "lesson-log source line", "undated source lesson",
                "notebook correction request"):
        assert f"`{key}`" in release
    assert "Unreleased" not in changelog.split("## 1.16.2", 1)[0]
