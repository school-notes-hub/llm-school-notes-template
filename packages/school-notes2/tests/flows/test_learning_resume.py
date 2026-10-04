"""T-095: new generated writes can resume even between recording and replacing."""

from datetime import date
from types import SimpleNamespace

import pytest

from school_notes2.flows import learning, journal
from school_notes2.state import phase, safefs
from school_notes2.wiki import decisions, drafts, frontmatter, guard, markers
from tests.wiki.conftest import repo, write
from tests.wiki.test_guard import snapshot, run
from tests.wiki.test_learning import DECISION


@pytest.mark.parametrize("crash", ["before", "after"])
def test_generation_crash_resume_preserves_decisions_and_draft_clock(repo, tmp_path, monkeypatch, crash):
    rel = "wiki/proba/elso.md"
    text = frontmatter.set_keys((repo / rel).read_text(), {"status": "draft", "decisions": [DECISION]})
    write(repo, rel, text)
    base = snapshot(repo)
    task = phase.create(tmp_path / "tasks", "tester", "notes", mode="cron", phase="prepared", run_id="learning")
    ctx = SimpleNamespace(notes_path=repo)
    real_write = safefs.write_text
    calls = 0

    def interrupted(root, path, data, **kw):
        nonlocal calls
        calls += 1
        if crash == "after" or calls != 2:
            real_write(root, path, data, **kw)
        if calls == 2:
            raise RuntimeError("power lost")
    monkeypatch.setattr(safefs, "write_text", interrupted)
    with pytest.raises(RuntimeError, match="power lost"):
        learning.refresh(ctx, task, today=date(2026, 9, 1))
    task = phase.load(task.dir)
    changes = [(p, "modified" if p in base else "added") for p, data in snapshot(repo).items()
               if base.get(p) != data]
    assert not run(repo, base, changes, tool_parts=task.get("tool_parts", {}),
                   tool_files=task.get("tool_writes", {}))
    monkeypatch.setattr(safefs, "write_text", real_write)
    learning.refresh(ctx, task, today=date(2026, 9, 2))
    first = snapshot(repo)
    assert frontmatter.split((repo / rel).read_text()).meta[drafts.KEY]["since"] == "2026-09-01"
    assert decisions.snapshot((repo / rel).read_bytes()) == decisions.snapshot(base[rel])
    assert decisions.OVERVIEW in first and b"elso-datum" in first[decisions.OVERVIEW]
    assert b"\xf0\x9f\x93\x8e" in first["wiki/proba/2026-09-10-elso-jegyzet.md"]
    learning.refresh(ctx, phase.load(task.dir), today=date(2026, 9, 3))
    assert snapshot(repo) == first


def test_replacement_crash_accepts_previous_generated_bytes(repo, tmp_path, monkeypatch):
    task = phase.create(tmp_path / "tasks", "tester", "notes", "interactive", "prepared")
    ctx = SimpleNamespace(notes_path=repo)
    base = snapshot(repo)
    learning.refresh(ctx, task, today=date(2026, 9, 1))
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    text = (repo / rel).read_text()
    lessons = frontmatter.split(text).meta["lessons"]
    lessons[0]["materials"] = ["A próba (lap)"]
    write(repo, rel, frontmatter.set_keys(text, {"lessons": lessons}))
    def fail(*args, **kw):
        raise RuntimeError("before replacement")
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", fail)
        with pytest.raises(RuntimeError, match="before replacement"):
            learning.refresh(ctx, task)
    task = phase.load(task.dir)
    assert not run(repo, base, [(rel, "modified")], tool_parts=task.get("tool_parts"),
                   pending_write=task.get("learning_pending"))
    # This allowance is hash-bound; it cannot hide an arbitrary writer edit.
    write(repo, rel, (repo / rel).read_text().replace("📎 Füzet:", "📎 Módosítva:"))
    assert run(repo, base, [(rel, "modified")], tool_parts=task.get("tool_parts"),
               pending_write=task.get("learning_pending"))
    write(repo, rel, frontmatter.set_keys(text, {"lessons": lessons}))
    learning.refresh(ctx, task)
    assert "A próba (lap)" in markers.read((repo / rel).read_text(), "lesson-sources")
    assert task.get("learning_pending") is None


def test_tool_block_insertion_is_not_an_interactive_writer_race():
    from school_notes2.flows.steps import _llm_hash
    from school_notes2.wiki.lesson_log import after_header
    text = "---\ntitle: T\n---\n\n![Banner](a.svg)\n\n# Tananyag\n\nTartalom.\n"
    new = after_header(text, "lesson-sources", "📎 Füzet: dátum nélküli óra\n")
    assert _llm_hash("wiki/a.md", text.encode()) == _llm_hash("wiki/a.md", new.encode())
    assert _llm_hash("wiki/a.md", text.encode()) != _llm_hash("wiki/a.md", (new + "Új.\n").encode())


def test_writer_race_still_detects_whitespace_edits_in_code():
    from school_notes2.flows.steps import _llm_hash
    text = "# Példa\n\n```python\ntext = '''a\n\n\nb'''\n```\n"
    changed = text.replace("a\n\n\nb", "a\n\nb")
    assert _llm_hash("wiki/a.md", text.encode()) != _llm_hash("wiki/a.md", changed.encode())


@pytest.mark.parametrize("whole", [False, True])
def test_abandoned_pending_replacement_restores_recorded_hash(repo, tmp_path, monkeypatch, whole):
    task = phase.create(tmp_path / "tasks", "tester", "notes", "interactive", "prepared")
    ctx = SimpleNamespace(notes_path=repo)
    base = snapshot(repo)
    learning.refresh(ctx, task, today=date(2026, 9, 1))
    rel = decisions.OVERVIEW if whole else "wiki/proba/2026-09-10-elso-jegyzet.md"
    key = "tool_writes" if whole else "tool_parts"
    before = task.get(key)[rel]
    def fail(*args, **kw):
        raise RuntimeError("before replacement")
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_text", fail)
        with pytest.raises(RuntimeError, match="before replacement"):
            new = (repo / rel).read_text().replace("Füzet", "Másik") if not whole else "new overview"
            journal.write(ctx, task, rel, new, whole=whole)
    task = phase.load(task.dir)
    assert task.get(key)[rel] != before
    # The input already matches the last completed refresh: no replacement is needed.
    learning.refresh(ctx, task)
    assert task.get("learning_pending") is None
    assert task.get(key)[rel] == before
    assert not run(repo, base, [(rel, "modified" if rel in base else "added")],
                   tool_parts=task.get("tool_parts"), tool_files=task.get("tool_writes"))
