from types import SimpleNamespace

import pytest

from school_notes2.config import Harness, Limits, Role, Timeouts
from school_notes2.flows import steps
from school_notes2.state import phase, safefs


@pytest.fixture
def setup(tmp_path, log, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    page = "wiki/m/topic.md"
    safefs.write_text(repo, page, "---\ntitle: Téma\ntype: topic\n---\n# Téma\n\nA test lefelé gyorsul.\n")
    safefs.write_json(repo, "tools/subjects.json", {"subjects": {"m": {}}})
    safefs.write_text(repo, "wiki/index.md", "---\ntitle: Kezdőlap\n---\n# Kezdőlap\n")
    before = {page: "---\ntitle: Téma\ntype: topic\n---\n# Téma\n\nRégi mondat.\n"}
    def git(*args, **kw):
        rel = args[1].split(":", 1)[1]
        return SimpleNamespace(returncode=0 if rel in before else 1, stdout=before.get(rel, "").encode())
    wt = SimpleNamespace(run=git)
    role = Role("claude-review", "configured-model", "high", 999)
    harness = Harness("claude-review", ["fake"], [], [], output="file")
    cfg = SimpleNamespace(role=lambda _: (role, harness), limits=Limits(), state_dir=tmp_path / "state",
                          provider_domains=("test.invalid",), browser=tmp_path / "browser", timeouts=Timeouts())
    ctx = SimpleNamespace(notes_path=repo, name="tester", cfg=cfg, log=log, student=SimpleNamespace(grade=9),
                          worktree=lambda _: wt, image_tag=lambda: "image", release=lambda: tmp_path)
    task = phase.create(tmp_path / "state", "tester", "notes", "cron", "figures", "20261004-unit")
    task.update(base="base", inspection_result={"status": "done"}, attempt=1, max_agents=3,
                ranges=[[0, 0]], packages=[], pages=[])
    monkeypatch.setattr(steps, "llm_snapshot", lambda *a: {page: "changed"})
    monkeypatch.setattr(steps, "generate_all", lambda *a: None)
    return ctx, task, page
