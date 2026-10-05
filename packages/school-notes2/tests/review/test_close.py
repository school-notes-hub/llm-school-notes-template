import pytest

from school_notes2.review import close, nightly
from school_notes2.state import phase
from school_notes2.state.errors import NeedsOwner, Transient
from school_notes2.wiki import frontmatter as fm

from .conftest import sh
from tests.conftest import assert_suppressed

IDENT = close.Identity("benedek", "opus-5.5/high", "2.0.0", "2026-10-04", "2026-10-04T03:20:00+02:00")
REVIEW = {"verdict": "changes",
          "findings": [{"id": "R1", "file": "wiki/a.md", "line": 1, "problem": "Elírás.", "relates_to": None}],
          "figures": [{"file": "wiki/assets/f.svg", "page": "wiki/a.md", "verdict": "jó",
                       "observed": "Két nyíl."}]}


def legacy_prepare(root, student, repo, wt, *, fetch_timeout, rasterize, **obsolete):
    task = nightly.prepare(root, student, repo, wt, fetch_timeout=fetch_timeout, rasterize=rasterize)
    if obsolete.get("max_diff_kb") == 1:
        task.update(T=task.get("commits")[0])  # Previously saved D60-cut task.
    task.update(topic_review=False)
    nightly.resume_prepared(task, repo, wt, rasterize)
    return task


def reviewed(tmp_path, repos, **kw):
    args = dict(max_images=30, max_diff_kb=300, fetch_timeout=60, rasterize=lambda s, o: [])
    args.update(kw)
    task = legacy_prepare(tmp_path / "srv", "benedek", repos.repo, repos.wt, **args)
    nightly.record_review(task, REVIEW)
    return task


def file_at(repos, ref, path):
    return sh("git", "--git-dir", str(repos.origin), "show", f"{ref}:{path}")


def test_quiet_night_marker_includes_report(tmp_path, repos):
    head = repos.commit({"wiki/a.md": "szöveg\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == r and repos.remote("main") == r and repos.remote("claude-reviewed") == r
    assert sh("git", "--git-dir", str(repos.origin), "rev-parse", f"{r}^") == head
    report = file_at(repos, r, "docs/review/2026-10-04-review.md")
    assert fm.split(report + "\n").meta["items"] == {"R1": "open"}
    assert "review-index" in file_at(repos, r, "docs/review/index.md")
    assert "Két nyíl." in file_at(repos, r, "docs/evidence/pages/a.md")
    msg = sh("git", "--git-dir", str(repos.origin), "log", "-1", "--format=%B", r)
    assert f"Run-Id: {task.run_id}" in msg and "Kind: review" in msg
    assert phase.load(task.dir).phase == "done"


def test_commit_arriving_during_review_sets_marker_to_t(tmp_path, repos):
    t = repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    later = repos.commit({"wiki/b.md": "laptop\n"})
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == t and repos.remote("claude-reviewed") == t
    assert sh("git", "--git-dir", str(repos.origin), "rev-parse", f"{r}^") == later


def test_limit_cut_sets_marker_to_t(tmp_path, repos):
    t = repos.commit({"wiki/a.md": "x" * 3000 + "\n", "wiki/assets/f.svg": "<svg/>"})
    repos.commit({"wiki/b.md": "y" * 3000 + "\n"})
    task = reviewed(tmp_path, repos, max_diff_kb=1)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert m == t != r


def test_atomic_push_moves_neither_ref(tmp_path, repos):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    main_before, marker_before = repos.remote("main"), repos.remote("claude-reviewed")
    hook = repos.origin / "hooks" / "update"
    hook.write_text('#!/bin/sh\n[ "$1" = refs/heads/claude-reviewed ] && exit 1\nexit 0\n')
    hook.chmod(0o755)
    with pytest.raises(NeedsOwner):
        close.close(task, repos.repo, repos.wt, IDENT)
    assert repos.remote("main") == main_before
    assert repos.remote("claude-reviewed") == marker_before


def test_race_rebuilds_on_fresh_main(tmp_path, repos, monkeypatch):
    t = repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    real, calls = close._push, []

    def racing(repo, r, m, timeout):
        calls.append(r)
        if len(calls) == 1:
            repos.commit({"wiki/c.md": "közben\n"})
        real(repo, r, m, timeout)

    monkeypatch.setattr(close, "_push", racing)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert len(calls) == 2 and m == t and repos.remote("main") == r
    assert sh("git", "--git-dir", str(repos.origin), "ls-tree", "--name-only", r,
              "docs/review/").count("2026-10-04-review") == 1


def test_lost_reply_is_decided_by_ls_remote(tmp_path, repos, monkeypatch):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    real = close._push

    def lost(repo, r, m, timeout):
        real(repo, r, m, timeout)
        raise Transient("connection reset after send")

    monkeypatch.setattr(close, "_push", lost)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    assert repos.remote("main") == r and phase.load(task.dir).phase == "done"


def test_resume_in_pushing_phase_needs_no_new_commit(tmp_path, repos, monkeypatch):
    repos.commit({"wiki/a.md": "x\n", "wiki/assets/f.svg": "<svg/>"})
    task = reviewed(tmp_path, repos)
    r, m = close.close(task, repos.repo, repos.wt, IDENT)
    task.data["phase"] = "pushing"
    task.save()
    monkeypatch.setattr(close, "_commit", lambda *a: pytest.fail("no new commit expected"))
    assert close.close(task, repos.repo, repos.wt, IDENT) == (r, m)


def test_discard_timeout_steps_marker_past_commit(tmp_path, repos):
    stuck = repos.commit({"wiki/a.md": "nagy\n"})
    repos.commit({"wiki/b.md": "utána\n"})
    task = phase.create(tmp_path / "srv", "benedek", "review", "cron", "closing")
    r, m = close.discard_timeout(task, repos.repo, repos.wt, IDENT, stuck)
    assert m == stuck and repos.remote("claude-reviewed") == stuck and repos.remote("main") == r
    assert "Nem átnézve" in file_at(repos, r, "docs/review/2026-10-04-review.md")


def disputed_report(repos):
    from school_notes2.review import files
    report = files.write_review(repos.laptop, "2026-10-03", {"verdict": "changes", "findings": [
        {"id": "R1", "file": "wiki/a.md", "problem": "Vita.", "relates_to": None},
        {"id": "R2", "file": "wiki/a.md", "problem": "Nyitott.", "relates_to": None}]}, "r", "a", "b")
    rel = report.relative_to(repos.laptop).as_posix()
    files.apply_closure(repos.laptop, "writer", [{"file": rel, "item_id": "R1", "status": "disagree", "note": "Indok."}], [])
    repos.commit({"wiki/a.md": "Tananyag.\n"})
    return rel


@pytest.mark.parametrize("verdict", ["accept", "keep"])
def test_close_valid_and_invalid_responses_keeps_good_findings(tmp_path, repos, verdict):
    from school_notes2.review import relations
    from school_notes2.state.files import read_json
    rel = disputed_report(repos)
    task = reviewed(tmp_path, repos)
    responses = [{"key": key, "verdict": verdict, "answer": "Válasz."} for key in
                 (f"{rel}#R1", f"{rel}#R2", "docs/review/missing.md#R1")]
    nightly.record_review(task, {**REVIEW, "responses": responses}, repos.wt_path)
    assert len(task.get("dropped_responses")) == 2
    assert len(read_json(task.dir / "review.json")["responses"]) == 1
    r, _ = close.close(task, repos.repo, repos.wt, IDENT)
    text = file_at(repos, r, rel) + "\n"
    assert relations.details(text, "R1")["round"] == (2 if verdict == "keep" else 1)
    assert fm.split(text).meta["items"]["R1"] == ("open" if verdict == "keep" else "disagree")
    assert "Elírás." in file_at(repos, r, "docs/review/2026-10-04-review.md")
    assert task.phase == "done"


def test_close_revalidates_response_after_upstream_answer(tmp_path, repos):
    from school_notes2.review import relations
    rel = disputed_report(repos)
    task = reviewed(tmp_path, repos)
    nightly.record_review(task, {**REVIEW, "responses": [
        {"key": f"{rel}#R1", "verdict": "keep", "answer": "Későbbi válasz."}]}, repos.wt_path)
    relations.reply(repos.laptop, f"{rel}#R1", "accept", "Korábbi válasz.")
    repos.commit({"wiki/a.md": "Tananyag.\nÚj mondat.\n"})
    r, _ = close.close(task, repos.repo, repos.wt, IDENT)
    assert len(task.get("dropped_responses_at_close")) == 1
    assert "Korábbi válasz." in file_at(repos, r, rel)
    assert "Későbbi válasz." not in file_at(repos, r, rel)
    assert "review.dropped_responses" in repos.repo.log.main.read_text()
    assert task.phase == "done"


def test_close_decision_owner_notification_survives_crash(tmp_path, repos, monkeypatch):
    from types import SimpleNamespace
    from school_notes2.flows import nightly as flow
    from school_notes2.flows import run
    text = fm.set_keys("Tananyag.\n", {"decisions": [{"id": "nev", "claim": "Név", "answer": "Válasz",
                                                     "by": "owner", "on": "2026-10-04"}]})
    repos.commit({"wiki/a.md": text})
    task = reviewed(tmp_path, repos)
    review = {"verdict": "changes", "findings": [{"id": "R1", "file": "wiki/a.md", "problem": "Új adat.",
                                                "relates_to": "nev", "new_evidence": "Bizonyíték."}]}
    nightly.record_review(task, review, repos.wt_path)
    real_finish = close._finish
    monkeypatch.setattr(close, "_finish", lambda *a: (_ for _ in ()).throw(RuntimeError("power loss after push")))
    with pytest.raises(RuntimeError):
        close.close(task, repos.repo, repos.wt, IDENT)
    resumed = phase.load(task.dir)
    assert resumed.phase == "pushing" and len(resumed.get("notify_owner_items")) == 1
    monkeypatch.setattr(close, "_finish", real_finish)
    close.close(resumed, repos.repo, repos.wt, IDENT)
    from school_notes2.notify import Mailer
    delivered = []
    monkeypatch.setattr(Mailer, "_deliver", lambda self, message: delivered.append(message) or True)
    ctx = SimpleNamespace(name="benedek", cfg=SimpleNamespace(state_dir=tmp_path), mailer=Mailer(
        tmp_path / "rc", "owner@example.com", tmp_path / "notify.json", repos.repo.log))
    # Simulate a crash after send_once; its stable key prevents a second delivery.
    real_owner = run.owner_items
    def interrupted(*args):
        real_owner(*args)
        raise RuntimeError("power loss after email")
    with monkeypatch.context() as m:
        m.setattr(run, "owner_items", interrupted)
        with pytest.raises(RuntimeError):
            flow._notify_owners(ctx, resumed)
    flow._notify_owners(ctx, phase.load(task.dir))
    flow._notify_owners(ctx, phase.load(task.dir))
    assert not delivered
    assert_suppressed(repos.repo.log)
    assert phase.load(task.dir).get("owners_notified")


def test_resume_rebuilds_legacy_relation_input_at_pinned_commit(tmp_path, repos):
    from school_notes2.state.files import read_json, write_json
    rel = disputed_report(repos)
    task = reviewed(tmp_path, repos)
    path = task.dir / "in" / "relations.json"
    grouped = read_json(path)
    assert f"{rel}#R1" in grouped["pages"]["wiki/a.md"]["items"]
    write_json(path, {"pages": {}, "items": {}})  # Previous input shape.
    repos.commit({"wiki/a.md": "Newer upstream must not change the pinned review.\n"})
    nightly.resume_prepared(task, repos.repo, repos.wt, lambda *a: [])
    assert read_json(path) == grouped
    assert (repos.wt_path / "wiki/a.md").read_text() == "Tananyag.\n"
