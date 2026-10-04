import subprocess
from pathlib import Path

import pytest

from school_notes2.git import conflicts, discard, finish, repos, run, workbranch
from school_notes2.git.run import Git, Remote
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner, Transient
from tests.conftest import make_origin

BLOCK_A = "<!-- school-notes:generated x -->"
BLOCK_B = "<!-- /school-notes:generated -->"


@pytest.fixture(autouse=True)
def allow_local_origin(monkeypatch):
    # Production forbids the file protocol; the tests use a local bare "origin".
    fixed = tuple(c for c in run.FIXED_C if not c.startswith("protocol.file"))
    monkeypatch.setattr(run, "FIXED_C", fixed + ("protocol.file.allow=always",))


def empty_blocks(text: str) -> str:
    out, inside = [], False
    for line in text.split("\n"):
        if line.startswith(BLOCK_A[:30]):
            inside = True
            out.append(line)
        elif line == BLOCK_B:
            inside = False
            out.append(line)
        elif not inside:
            out.append(line)
    return "\n".join(out)


class Env:
    def __init__(self, tmp_path, log):
        files = {"wiki/a.md": "line 1\nline 2\nline 3\n",
                 "wiki/x/index.md": f"# X\n{BLOCK_A}\nold\n{BLOCK_B}\nhand\n",
                 "publication/public.json": '{"v": 1}\n'}
        self.origin = make_origin(tmp_path, files)
        self.bare = Git(tmp_path / "bare.git", "Tool", "tool@example.com", log)
        repos.ensure_bare(self.bare, str(self.origin), repos.NOTES_REFSPECS)
        repos.fetch(self.bare, 60)
        self.path = tmp_path / "work" / "notes"
        repos.ensure_worktree(self.bare, self.path, "refs/remotes/origin/main")
        self.wt = repos.worktree_git(self.bare, self.path)
        self.root = tmp_path / "srv"
        self.tmp = tmp_path
        self.published = []

    def start_run(self, mode="cron"):
        task = phase.create(self.root, "benedek", "notes", mode, "prepared")
        base = repos.rev(self.wt, "refs/remotes/origin/main")
        workbranch.start(self.wt, task.run_id, base, interactive=mode == "interactive")
        workbranch.reset_workdir(self.path)
        task.update(base=base)
        task.set_phase("finishing")
        return task

    def hooks(self, regenerate=lambda: None):
        return finish.Hooks(regenerate=regenerate, build=lambda c: {"commit": c},
                            publish=self.published.append,
                            message=lambda: "notes(benedek): test\n\nRun-Id: {rid}\n",
                            snapshot=lambda: {}, empty_blocks=empty_blocks)

    def other_push(self, rel, text, message="laptop"):
        clone = self.tmp / f"laptop-{len(list(self.tmp.glob('laptop-*')))}"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True)
        (clone / rel).parent.mkdir(parents=True, exist_ok=True)
        (clone / rel).write_text(text)
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin",
               "GIT_AUTHOR_NAME": "L", "GIT_AUTHOR_EMAIL": "l@x", "GIT_COMMITTER_NAME": "L",
               "GIT_COMMITTER_EMAIL": "l@x"}
        subprocess.run(["git", "-C", str(clone), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(clone), "commit", "-qm", message], check=True, env=env)
        subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True, env=env)

    def origin_log(self):
        out = subprocess.run(["git", f"--git-dir={self.origin}", "log", "--format=%s%n%b", "main"],
                             capture_output=True, text=True, check=True).stdout
        return out


def fixed_message(task):
    return lambda: f"notes(benedek): test\n\nRun-Id: {task.run_id}\n"


@pytest.fixture
def env(tmp_path, log):
    return Env(tmp_path, log)


T = finish.Timeouts(retry_delays=(0, 0, 0))


def test_simple_run_is_committed_pushed_and_cleaned(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("line 1\nchanged\nline 3\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert f"Run-Id: {task.run_id}" in env.origin_log()
    assert env.published and env.published[0]["commit"]
    assert not repos.has_ref(env.wt, f"refs/heads/notes/{task.run_id}")


def test_no_change_run_makes_no_commit(env):
    before = env.origin_log()
    task = env.start_run()
    assert finish.run(task, env.wt, env.hooks(), T, {}) == "done"
    assert env.origin_log() == before and task.get("no_change")


def test_concurrent_laptop_push_is_rebased_linearly(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("line 1\nline 2\nline 3\nmine\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    pushed = []

    def build(commit):
        if not pushed:              # someone pushes between our fetch and our push (T9)
            pushed.append(1)
            env.other_push("wiki/b.md", "from laptop\n")
        return {"commit": commit}

    hooks.build = build
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    log = env.origin_log()
    assert log.index(f"Run-Id: {task.run_id}") < log.index("laptop")
    merges = subprocess.run(["git", f"--git-dir={env.origin}", "rev-list", "--merges", "main"],
                            capture_output=True, text=True).stdout
    assert merges == ""


def test_lost_reply_after_push_does_not_commit_twice(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("pushed already\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.wt.run("push", "origin", "HEAD:refs/heads/main")       # the reply was lost (T10a)
    task.set_phase("pushing")
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert env.origin_log().count(f"Run-Id: {task.run_id}") == 1


def test_content_conflict_stops_then_owner_resolution_finishes(env):
    task = env.start_run(mode="interactive")
    (env.path / "wiki/a.md").write_text("line 1\nours\nline 3\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.other_push("wiki/a.md", "line 1\ntheirs\nline 3\n")
    with pytest.raises(NeedsOwner):
        finish.run(task, env.wt, hooks, T, {})
    assert task.get("rebase") == "conflict" and task.get("conflict_files") == ["wiki/a.md"]
    text = (env.path / "wiki/a.md").read_text()
    assert "<<<<<<< origin/main (kívülről)" in text and f">>>>>>> futás {task.run_id}" in text
    (env.path / "wiki/a.md").write_text("line 1\nmerged\nline 3\n")
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    show = subprocess.run(["git", f"--git-dir={env.origin}", "show", "main:wiki/a.md"],
                          capture_output=True, text=True).stdout
    assert show == "line 1\nmerged\nline 3\n"


def test_markers_left_in_place_keep_the_run_stopped(env):
    task = env.start_run(mode="interactive")
    (env.path / "wiki/a.md").write_text("line 1\nours\nline 3\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.other_push("wiki/a.md", "line 1\ntheirs\nline 3\n")
    with pytest.raises(NeedsOwner):
        finish.run(task, env.wt, hooks, T, {})
    with pytest.raises(NeedsOwner, match="conflict markers"):
        finish.run(task, env.wt, hooks, T, {})


def test_generated_only_conflicts_resolve_without_owner(env):
    task = env.start_run()
    index = env.path / "wiki/x/index.md"
    index.write_text(f"# X\n{BLOCK_A}\nmine\n{BLOCK_B}\nhand\n")
    (env.path / "publication/public.json").write_text('{"v": 2}\n')
    regenerated = []

    def regenerate():
        regenerated.append(1)
        index.write_text(f"# X\n{BLOCK_A}\nregenerated\n{BLOCK_B}\nhand\n")

    hooks = env.hooks(regenerate)
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.other_push("wiki/x/index.md", f"# X\n{BLOCK_A}\ntheirs\n{BLOCK_B}\nhand\n")
    env.other_push("publication/public.json", '{"v": 3}\n')
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert regenerated
    show = subprocess.run(["git", f"--git-dir={env.origin}", "show", "main:wiki/x/index.md"],
                          capture_output=True, text=True).stdout
    assert "regenerated" in show


def test_edit_during_interactive_finish_stops_before_commit(env):
    task = env.start_run(mode="interactive")
    (env.path / "wiki/a.md").write_text("x\n")
    hooks = env.hooks()
    hooks.snapshot = lambda: {"wiki/a.md": "changed"}
    with pytest.raises(finish.EditedDuringFinish):
        finish.run(task, env.wt, hooks, T, {"wiki/a.md": "before"})
    assert repos.rev(env.wt, "HEAD") == task.get("base")


def test_push_permission_error_needs_owner(env, monkeypatch):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("x\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    hook = env.origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch hook declined' >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(NeedsOwner):
        finish.run(task, env.wt, hooks, T, {})


def test_discard_bundles_unpushed_work(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("to be discarded\n")
    bundle = discard.discard(env.wt, task.run_id, env.tmp / "archive")
    assert bundle and bundle.exists()
    assert (env.path / "wiki/a.md").read_text() == "line 1\nline 2\nline 3\n"
    assert not repos.has_ref(env.wt, f"refs/heads/notes/{task.run_id}")


def test_changes_json_lists_edits_and_new_files(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("x\n")
    (env.path / "wiki/new.md").write_text("n\n")
    (env.path / ".school-notes" / "fetch.json").write_text("{}")
    changed = workbranch.changed_files(env.wt, task.get("base"))
    assert changed == [{"path": "wiki/a.md", "status": "modified"},
                       {"path": "wiki/new.md", "status": "added"}]


def test_rewritten_remote_history_needs_owner(env):
    seed = env.tmp / "rewrite"
    subprocess.run(["git", "clone", "-q", str(env.origin), str(seed)], check=True)
    e = {"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin", "GIT_AUTHOR_NAME": "R",
         "GIT_AUTHOR_EMAIL": "r@x", "GIT_COMMITTER_NAME": "R", "GIT_COMMITTER_EMAIL": "r@x"}
    subprocess.run(["git", "-C", str(seed), "commit", "-q", "--amend", "-m", "rewritten"],
                   check=True, env=e)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "--force", "origin", "main"],
                   check=True, env=e)
    with pytest.raises(NeedsOwner, match="rewritten"):
        repos.fetch(env.bare, 60)


def test_dot_git_swap_is_detected(env):
    recorded = (env.path / ".git").read_bytes()
    assert repos.dot_git_ok(env.path, recorded)
    (env.path / ".git").write_text("gitdir: /tmp/evil\n")
    assert not repos.dot_git_ok(env.path, recorded)


def test_user_hooks_and_gitconfig_have_no_effect(env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text('[url "file:///nonexistent/"]\n\tinsteadOf = /\n'
                                     "[core]\n\tautocrlf = true\n")
    monkeypatch.setenv("HOME", str(home))
    hook = env.wt.git_dir.parent.parent / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\ntouch /tmp/sn-hook-ran\nexit 1\n")
    hook.chmod(0o755)
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("crlf?\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert not Path("/tmp/sn-hook-ran").exists()


def test_crash_inside_a_rebase_never_looks_pushed(env):
    """R1-B1: a rebase killed before its state was recorded is aborted, not taken as pushed."""
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("line 1\nours\nline 3\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.other_push("wiki/a.md", "line 1\ntheirs\nline 3\n")
    repos.fetch(env.wt, 60)
    env.wt.run("rebase", "refs/remotes/origin/main", check=False)   # killed mid-way
    assert (env.wt.git_dir / "rebase-merge").exists()
    with pytest.raises(NeedsOwner, match="content conflict"):
        finish.run(task, env.wt, hooks, T, {})
    assert task.phase == "committed"
    assert f"Run-Id: {task.run_id}" not in env.origin_log()


def test_own_change_already_upstream_finishes_without_push(env):
    task = env.start_run()
    (env.path / "wiki/a.md").write_text("same everywhere\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    finish.g1_commit(task, env.wt, hooks, {})
    env.other_push("wiki/a.md", "same everywhere\n")
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert f"Run-Id: {task.run_id}" not in env.origin_log()


def test_unknown_phase_is_refused(env):
    task = env.start_run()
    task.set_phase("downloading")
    with pytest.raises(RuntimeError, match="cannot continue"):
        finish.run(task, env.wt, env.hooks(), T, {})


def test_discard_keeps_uncommitted_edits_on_a_detached_head(env):
    """R1-M1: no branch (interrupted fetch), dirty worktree → still bundled first."""
    task = env.start_run()
    env.wt.run("switch", "--detach", "HEAD")
    env.wt.run("branch", "-D", f"notes/{task.run_id}")
    (env.path / "wiki/a.md").write_text("owner's unsaved work\n")
    bundle = discard.discard(env.wt, task.run_id, env.tmp / "archive")
    assert bundle and bundle.exists()
    listed = subprocess.run(["git", "bundle", "list-heads", str(bundle)], capture_output=True,
                            text=True).stdout
    assert f"notes/{task.run_id}" in listed


def test_review_reply_and_other_item_closure_rebase_without_owner(env):
    from school_notes2.review import files, relations
    from school_notes2.wiki import frontmatter
    report = files.write_review(env.path, "2026-10-03", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/a.md", "problem": "Vitatott."},
        {"id": "R2", "file": "wiki/a.md", "problem": "Javítandó."}]}, "r", "a", "b")
    rel = report.relative_to(env.path).as_posix()
    files.apply_closure(env.path, "old", [{"file": rel, "item_id": "R1", "status": "disagree", "note": "Indok."}], [])
    base = report.read_text()
    env.other_push(rel, base)
    report.unlink()  # The upstream copy becomes tracked when the work branch starts.
    repos.fetch(env.bare, 60)
    task = env.start_run()
    files.apply_closure(env.path, task.run_id, [{"file": rel, "item_id": "R2", "status": "fixed"}], [])
    # The nightly reply changes the same frontmatter and appends to the same body.
    separate = env.tmp / "reply"
    (separate / rel).parent.mkdir(parents=True)
    (separate / rel).write_text(base)
    relations.reply(separate, f"{rel}#R1", "keep", "Válasz.")
    env.other_push(rel, (separate / rel).read_text())
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    text = (env.path / rel).read_text()
    assert frontmatter.split(text).meta["items"] == {"R1": "open", "R2": "fixed"}
    assert relations.details(text, "R1")["round"] == 2
    assert text.count("## Válasz (R1)") == 1
    assert text.count(f"## Végrehajtva ({task.run_id})") == 1


def test_review_merge_does_not_hide_conflicting_status_or_prose():
    from school_notes2.review.merge import merge
    from school_notes2.wiki import frontmatter
    base = frontmatter.set_keys("# Review\n\nTárgy.\n", {"reviewer": "r", "items": {"R1": "open"}, "status": "open"})
    fixed = frontmatter.set_keys(base, {"items": {"R1": "fixed"}})
    disagree = frontmatter.set_keys(base, {"items": {"R1": "disagree"}})
    assert merge([base.encode(), b"---\nitems: [\n---\n", fixed.encode()]) is None
    assert merge([s.encode() for s in (base, fixed, disagree)]) is None
    assert merge([s.encode() for s in (base, fixed.replace("Tárgy.", "Átírva."), disagree)]) is None


def test_review_before_map_conflict_reaches_owner_during_rebase(env):
    from school_notes2.review import files
    report = files.write_review(env.path, "2026-10-03", {"verdict": "changes", "findings": [
        {"id": key, "file": "wiki/a.md", "problem": "Javítandó."} for key in ("R1", "R3")
    ]}, "r", "a", "b")
    rel = report.relative_to(env.path).as_posix()
    base = report.read_text()
    env.other_push(rel, base)
    report.unlink()
    repos.fetch(env.bare, 60)
    task = env.start_run()
    files.apply_closure(env.path, task.run_id,
                        [{"file": rel, "item_id": "R1", "status": "fixed"}],
                        [{"file": rel, "item_id": "R3"}])
    upstream = env.tmp / "upstream"
    (upstream / rel).parent.mkdir(parents=True)
    (upstream / rel).write_text(base)
    files.apply_closure(upstream, "owner", [{"file": rel, "item_id": "R3", "status": "fixed"}], [])
    env.other_push(rel, (upstream / rel).read_text())
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    with pytest.raises(NeedsOwner):
        finish.run(task, env.wt, hooks, T, {})
    assert task.get("conflict_files") == [rel]
    assert conflicts.has_markers(report.read_text())
    assert not env.published


@pytest.mark.parametrize("crash", [False, True])
def test_no_push_stops_after_commit_and_only_explicit_release_continues(env, monkeypatch, crash):
    task = env.start_run()
    task.update(no_push=True)
    (env.path / "wiki/a.md").write_text("trial\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    real = finish.g1_commit
    def interrupted(*args):
        real(*args)
        raise RuntimeError("committed before reply")
    if crash:
        monkeypatch.setattr(finish, "g1_commit", interrupted)
        with pytest.raises(RuntimeError):
            finish.run(task, env.wt, hooks, T, {})
        monkeypatch.setattr(finish, "g1_commit", real)
    task = phase.load(task.dir)
    with monkeypatch.context() as patch:
        def no_remote(*args, **kwargs):
            pytest.fail("trial must not fetch, build, push or publish")
        patch.setattr(finish, "_publish_round", no_remote)
        assert finish.run(task, env.wt, hooks, T, {}) == "committed"
    assert f"Run-Id: {task.run_id}" not in env.origin_log()
    assert repos.has_ref(env.wt, f"refs/heads/notes/{task.run_id}")
    commit = task.get("commit")
    task.update(no_push=False)
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert task.get("commit") == commit
    assert env.origin_log().count(f"Run-Id: {task.run_id}") == 1


def test_t154_final_keys_on_rebased_commit_before_build(env):
    from school_notes2.reader import units, verdicts
    from school_notes2.state import safefs
    task = env.start_run()
    page = "wiki/a.md"
    (env.path / page).write_text("changed first\nline 2\nline 3\n")
    verdicts.record(env.path, [{"file": page, "verdict": "ok"}],
                    {page: units.page_key(env.path, page)}, "model", "date")
    env.other_push(page, "line 1\nline 2\nchanged last\n")
    hooks = env.hooks()
    hooks.message = fixed_message(task)
    checked = []
    def final_keys():
        committed = env.wt.out("show", "HEAD:" + page)
        assert "changed first" in committed and "changed last" in committed
        checked.append(verdicts.invalidate(env.path))
    def build(commit):
        assert safefs.read_json(env.path, verdicts.PATH) == []
        assert env.wt.out("show", commit + ":" + verdicts.PATH).strip() == "[]"
        return {"commit": commit}
    hooks.final_keys, hooks.build = final_keys, build
    assert finish.run(task, env.wt, hooks, T, {}) == "done"
    assert len(checked) == 1 and len(checked[0]) == 1
