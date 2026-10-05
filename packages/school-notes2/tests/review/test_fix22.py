"""Tool markers do not widen nightly scope; judged closures are not assigned twice."""

from school_notes2.figures import rejected
from school_notes2.review import night_figures, topic_input, topics
from school_notes2.state import safefs
from .test_topics import prepare, FIX
from .conftest import sh


def test_nightly_retry_marker_is_a_tool_change(tmp_path, repos):
    page, asset = "wiki/m/a.md", "wiki/assets/a.png"
    text = "---\ntype: topic\ntitle: A\n---\n![A](../assets/a.png)\n\nOld.\n"
    repos.commit({page: text, asset: b"image"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    base = repos.repo.out("rev-parse", "refs/remotes/origin/main").strip()
    brief = {"id": "f", "page": page, "kind": "banner", "anchor": "A", "purpose": "A",
             "must_show": [], "avoid_misreading": "A", "taught_conventions": [], "text_complete_without_figure": True}
    spec = night_figures.discover(repos.laptop, {"topic": page, "pages": [page]})[0]
    entry = rejected.request(spec, brief, {"observed": "Bad", "defects": [], "text_mismatch": []},
                             night_figures.fingerprint(repos.laptop, spec))
    written = rejected.apply(repos.laptop, [entry])
    repos.commit({p: safefs.read_text(repos.laptop, p) for p in written}, "Nightly report")
    head = repos.repo.out("rev-parse", "refs/remotes/origin/main").strip()
    assert topics.author_changes(repos.repo, base, head) == []
    current = safefs.read_text(repos.laptop, page)
    repos.commit({page: current.replace("Old.", "New.")}, FIX)
    task = prepare(tmp_path, repos)
    assert task.get("units") == []


def test_nightly_input_omits_already_rechecked_closure(tmp_path, repos, monkeypatch):
    page = "wiki/a.md"
    repos.commit({page: "Old.\n"})
    sh("git", "push", "-q", "origin", "HEAD:claude-reviewed", cwd=repos.laptop)
    repos.commit({page: "New.\n"})
    task = prepare(tmp_path, repos)
    unit = task.get("units")[0]
    key = "docs/review/test.md#R1"
    known = {"pages": {}, "items": {key: {"file": page, "status": "fixed", "recheck": {"verdict": "ok"}}}}
    monkeypatch.setattr(topic_input.relations, "inventory", lambda _: known)
    monkeypatch.setattr(topic_input.relations, "reviewer_inventory", lambda _: {"pages": {}})
    monkeypatch.setattr(topic_input.topics, "closure_changes", lambda *a: {key: known["items"][key]})
    assigned = topic_input.prepare(repos.repo, repos.wt_path, task, unit, task.dir / "input")
    assert assigned["items"] == [] and assigned["assigned"]["items"] == []


def test_migrator_cli_uses_configured_learner(tmp_path, repos, monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    from school_notes2 import config
    from school_notes2.figures import migrate_pending
    from school_notes2.flows import context
    page = "wiki/m/topic.md"
    repos.commit({page: "---\ntype: topic\n---\n![A](../assets/a.svg)\n", "wiki/assets/a.svg": "<svg/>"})
    repos.repo.run("fetch", "origin")
    repos.wt.run("reset", "--hard", "refs/remotes/origin/main")
    state = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    seen = []
    monkeypatch.setattr(config, "load", lambda path: seen.append(path) or "config")
    ctx = SimpleNamespace(name="learner", notes_path=repos.wt_path, worktree=lambda _: repos.wt,
        cfg=SimpleNamespace(state_dir=state), task_root=lambda: tmp_path,
        image_settings=lambda: SimpleNamespace(learner="learner", max_attempts=3, ledger=lambda: {"jobs": {}}))
    def make(cfg, learner):
        assert (cfg, learner) == ("config", "learner")
        return ctx
    monkeypatch.setattr(context, "make", make)
    assert migrate_pending.main(["--config", str(config_path), "learner", "--dry-run"]) == 0
    assert seen == [config_path] and not state.exists()
    assert len(json.loads(capsys.readouterr().out)["commissions"]) == 1
    assert "<!-- image: banner-" not in safefs.read_text(repos.wt_path, page)
