"""Identical offline scenario on synthetic trees and opt-in learner bundles."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from school_notes2 import config
from school_notes2.drive.client import DriveClient
from school_notes2.figures import pending
from school_notes2.flows import context, fetch, handlers, prereq, run, setup, writer
from school_notes2.state import phase, safefs
from school_notes2.state.files import write_json
from school_notes2.review import files
from school_notes2.wiki import generate, public
from tests.conftest import make_origin, record_render
from tests.drive.fakedrive import FakeDrive
from tests.e2e.test_run_e2e import TEMPLATE, HERE, _FixedNow, jpeg, learner_files, show


def synthetic(tmp_path):
    tree = tmp_path / "seed-files"
    tree.mkdir()
    contents = learner_files()
    contents["wiki/masik/index.md"] = contents["wiki/proba/index.md"].replace("Próba", "Másik")
    contents["wiki/masik/tema.md"] = contents["wiki/proba/elso.md"].replace("Első", "Másik")
    contents["tools/subjects.json"] = json.dumps({"subjects": {
        "proba": {"name": "Próba", "emoji": "🧪"}, "masik": {"name": "Másik", "emoji": "📖"}}})
    for rel, text in contents.items():
        safefs.write_text(tree, rel, text)
    for page in ("wiki/proba/elso.md", "wiki/masik/tema.md"):
        safefs.write_text(tree, page, safefs.read_text(tree, page) + "\nHibás magyarázat.\n")
    files.write_review(tree, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": f"R{i}", "file": page, "quote": "Hibás magyarázat.", "problem": "Hiányzó lépés.", "category": "nyelvezet"}
        for i, page in enumerate(("wiki/proba/elso.md", "wiki/masik/tema.md"), 1)]}, "probe", "a", "b")
    brief = {"id": "probe-other", "page": "wiki/masik/tema.md", "kind": "figure", "anchor": "Cím",
             "purpose": "Két irány", "must_show": ["Két nyíl"], "avoid_misreading": "Irányok",
             "taught_conventions": [], "text_complete_without_figure": True}
    safefs.write_text(tree, brief["page"], safefs.read_text(tree, brief["page"]) + "\n<!-- figure: probe-other -->\n")
    pending.record(tree, brief, "old", [], attempted=False)
    for subject, page in (("proba", "wiki/proba/elso.md"), ("masik", "wiki/masik/tema.md")):
        banner = {**brief, "id": f"probe-{subject}-banner", "page": page, "kind": "banner"}
        text = safefs.read_text(tree, page).replace("# Cím\n", f"<!-- figure: {banner['id']} -->\n\n# Cím\n")
        safefs.write_text(tree, page, text)
        pending.record(tree, banner, "old", [], attempted=False)
    for subject, topic in (("proba", "elso.md"), ("masik", "tema.md")):
        safefs.write_text(tree, f"wiki/{subject}/regi-orak-jegyzet.md",
            "---\ntype: lesson-notes\ntitle: Korábbi órák\ndescription: Két óra témái.\nlessons:\n"
            f"  - {{date: '2026-10-01', title: Első óra, topics: [{topic}]}}\n"
            f"  - {{date: '2026-10-02', title: Második óra, topics: [{topic}]}}\n---\n\n"
            f"# Mit tanultunk ezeken az órákon\n\n* [Fogalom]({topic}#cím)\n"
            f"* [Magyarázat]({topic}#cím)\n* [Példa]({topic}#cím)\n")
    generate.write_indexes(tree)
    public.write(tree, public.render_rights(tree))
    origin = tmp_path / "origin-src"
    origin.mkdir()
    return make_origin(origin, {p.relative_to(tree).as_posix(): p.read_bytes() for p in tree.rglob("*") if p.is_file()})


def probe_world(tmp_path, monkeypatch, learner, bundle):
    if bundle:
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "clone", "--bare", str(bundle), str(origin)], check=True, capture_output=True)
    else:
        origin = synthetic(tmp_path)
    subjects = json.loads(show(origin, "main:tools/subjects.json"))["subjects"]
    subject = sorted(subjects)[-1]
    drive = FakeDrive()
    root = drive.folder(learner)
    folder = drive.folder(subjects[subject]["name"], drive.folder("Füzet", root))
    ready = drive.folder("Feltöltés_Kész", folder)
    package = drive.folder("Próbaóra", ready)
    for n, color in enumerate(("red", "green", "blue"), 1):
        drive.file(f"{n}.jpg", package, jpeg(color))
    drive.folder("Feldolgozva", folder)
    site_seed = tmp_path / "site-src"
    site_seed.mkdir()
    site = make_origin(site_seed, {"README.md": "site\n"})
    cfg = config.parse({"root": str(tmp_path / "srv"), "secrets_dir": str(tmp_path / "secrets"),
        "email_to": "probe@example.test", "git": {"name": "Probe", "email": "probe@example.test"},
        "release_dir": str(TEMPLATE), "students": {learner: {"repo": str(origin), "repo_key": "/nonexistent",
        "site_repo": str(site), "site_key": "/nonexistent", "drive_root": root, "grade": 9}},
        "roles": {"writer": {"harness": "codex", "model": "fake", "effort": "high", "timeout_s": 60},
                  "reviewer": {"harness": "claude-review", "model": "fake", "effort": "high", "timeout_s": 60}}})
    ctx = context.make(cfg, learner, console=False)
    setup.setup(ctx)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "podman").write_text(f'#!/bin/sh\nexec {sys.executable} {HERE / "probe_podman.py"} "$@"\n')
    (bin_dir / "podman").chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(fetch, "drive_client", lambda ctx: DriveClient(drive))
    monkeypatch.setattr(prereq, "podman", lambda: None)
    monkeypatch.setattr("school_notes2.drive.inventory.datetime", _FixedNow)
    from school_notes2.notify import Mailer
    monkeypatch.setattr(Mailer, "_deliver", lambda *a: True)
    return ctx, origin, drive, package



def generated(counter, fid):
    counter.append(fid)
    return {"state": "error", "message": "Job changed"} if len(counter) == 2 else {"state": "generated"}

def image_stub(ctx, task, assigned, counter):
    """No paid service: the fake writer retries a Job changed response."""
    for entry in assigned:
        brief = entry["commission"]
        answer = handlers.generate(ctx, task, brief["id"], None)
        if answer["state"] == "error":
            ctx.log.event("probe.image", "error", message=answer["message"])
            answer = handlers.generate(ctx, task, brief["id"], None)
        assert answer["state"] == "generated"
        round_n = 2 if "-r2" in task.run_id else 1
        ext = "webp" if brief["kind"] in ("banner", "infographic") else "png"
        asset = f"wiki/assets/probe/{brief['id']}.{ext}"
        buf = io.BytesIO()
        Image.new("RGB", (1600, 900), "blue" if round_n == 2 else "green").save(buf, ext.upper())
        safefs.write_bytes(ctx.notes_path, asset, buf.getvalue())
        record_render(ctx.notes_path, asset)
        candidate = {"state": "candidate", "asset": asset, "alt": "Két nyíl", "caption": "Az irányokat nyilak jelölik.",
                     "form": "diagram", "tool": "probe", "elements": [{"element": "nyíl", "meaning": "irány"}],
                     "visible_text": [], "attempt": round_n, "corrections": []}
        safefs.write_json(ctx.notes_path, f".school-notes/figures/{brief['id']}.json", brief)
        safefs.write_json(ctx.notes_path, f".school-notes/figures/{brief['id']}/figure.json", candidate)
        if ext == "webp":
            from school_notes2.images import plans
            from school_notes2.wiki.pages import sha256
            settings = ctx.image_settings()
            ledger = settings.ledger()
            job = ledger["jobs"].setdefault(plans.job_id(ctx.name, brief["id"]), {"learner": ctx.name, "attempts": []})
            job["attempts"].append({"state": "generated", "number": round_n, "started_at": task.data["created"],
                "cost_usd": "0", "sha256": sha256(ctx.notes_path, asset), "preview_sha256": sha256(ctx.notes_path, asset)})
            write_json(settings.state_dir / "ledger.json", ledger)


def scenario(tmp_path, monkeypatch, learner, mode, bundle=None, *, render=True):
    ctx, origin, drive, package = probe_world(tmp_path, monkeypatch, learner, bundle)
    if mode == "fix":
        drive.items[package]["parents"] = ["not-ready"]
    expected = {i["key"] for i in files.open_items(ctx.notes_path, "cron")}
    figures = {e["commission"]["id"] for e in pending.load(ctx.notes_path) if not e["owner_required"] and e["runs"] < 3}
    calls, images, builds = [], [], []
    monkeypatch.setattr(handlers.image_generate, "generate",
        lambda settings, plan_id, note=None, **kw: generated(images, plan_id))
    if not render:
        from school_notes2.flows import finish
        def build(ctx, task, commit):
            builds.append(commit)
            return {"commit": commit, "output": str(task.dir / "stub-build")}
        monkeypatch.setattr(finish, "_build", build)
    real = writer._call
    def fake(ctx, task, k, *args):
        assigned = fetch.fetch_json(task, k, grade=9, repo=ctx.notes_path)
        calls.append(assigned)
        result = real(ctx, task, k, *args)
        image_stub(ctx, task, assigned.get("pending_figures", []), images)
        return result
    monkeypatch.setattr(writer, "_call", fake)
    rc = run.run(ctx)
    task = phase.all_tasks(ctx.task_root(), learner)[-1]
    assert rc == 0 and task.phase == "done", (task.phase, task.data.get("last_error"))
    assert task.get("correction_round") == 2
    assert expected <= {i["key"] for c in calls for i in c["open_review_items"]}
    assert figures <= set(images)
    assert not (ctx.notes_path / "wiki/probe-unassigned.md").exists()
    assert "Run-Id: " + task.run_id in show(origin, "main")
    if render:
        assert (task.dir / "build/build.json").is_file()
        assert (task.dir / "build/browser-report.json").is_file()
    else:
        assert len(builds) == 1
    receipts = list(task.dir.glob("attempt-1/reader/*/recheck-r2/receipt.json"))
    assert receipts and all(json.loads(p.read_text())["status"] == "reviewed" for p in receipts)
    figure_receipts = list(task.dir.glob("attempt-1/figure-review/recheck-r2-*/accepted.json"))
    if figures:
        assert figure_receipts
        assert all(v["verdict"] == "accept" for p in figure_receipts
                   for v in json.loads(p.read_text())["review"]["figures"])
    events = [json.loads(line) for line in ctx.cfg.log_path.read_text().splitlines()]
    if render:
        assert any(e["action"] == "site.build" and "duration_s" in e for e in events)
    if images:
        assert any(e.get("message") == "Job changed" for e in events)
    if mode == "package":
        assert sum(len(c["pages"]) for c in calls if c["packages"]) == 3


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["package", "fix"])
def test_synthetic_completion(tmp_path, monkeypatch, local_origin, learner, mode):
    scenario(tmp_path, monkeypatch, learner, mode)


@pytest.mark.skipif(not os.environ.get("SN_PROBE"), reason="SN_PROBE bundle directory not provided")
@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["package", "fix"])
def test_real_bundle_completion(tmp_path, monkeypatch, local_origin, learner, mode):
    scenario(tmp_path, monkeypatch, learner, mode, Path(os.environ["SN_PROBE"]) / f"{learner}.bundle")


@pytest.mark.parametrize("learner", ["benedek", "barna"])
@pytest.mark.parametrize("mode", ["package", "fix"])
def test_synthetic_pipeline_local_push(tmp_path, monkeypatch, local_origin, learner, mode):
    # The full scenario above exercises the real renderer/browser. This companion
    # isolates the state machine and local push on hosts that cannot launch Chromium.
    scenario(tmp_path, monkeypatch, learner, mode, render=False)
