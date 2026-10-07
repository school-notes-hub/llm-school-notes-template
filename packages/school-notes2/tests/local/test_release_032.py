"""sn 0.3.2: the consumed hand-over is moved to `.school-notes/done/`, and the timing lines of
the JSONL log. Each test fails on 6041fd5."""

import json

from school_notes2.local import close, machine_data
from school_notes2.local.handoff import handoffs
from school_notes2.state import safefs
from tests.local.test_close import ACCEPT, PAGE, edit, handoff, learner_tree, quiet, tree  # noqa: F401

OUT = ".school-notes/out"


def files_under(repo, rel):
    """The hand-over's files (`closed.json`, the tool's mark of a finished pass since 0.3.6, left out)."""
    return {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, rel)
            if not p.endswith("/closed.json")} if safefs.is_dir(repo, rel) else {}


def snapshotted(repo, subject="physics"):
    handoff(repo, subject=subject)
    safefs.write_json(repo, f"{OUT}/{subject}/keys.json", {})
    # since 0.3.6 every pass hands over its log entry (`sn done` reports one without)
    if not safefs.is_file(repo, f"{OUT}/{subject}/adatok.json"):
        safefs.write_json(repo, f"{OUT}/{subject}/adatok.json", {
            "writer": "claude-opus-5-5/high", "log": [{"kind": "Update", "text": f"{subject}: menet."}]})


def test_a_successful_close_moves_each_consumed_hand_over_to_done(repo, fake_local):
    snapshotted(repo)
    snapshotted(repo, "chemistry")
    safefs.write_text(repo, f"{OUT}/physics/iro-jelentes.md", "# Jelentés\n")
    before = {h.subject: (machine_data.pass_id(h), files_under(repo, f"{OUT}/{h.subject}")) for h in handoffs(repo, None)}
    local, lines = fake_local(repo), []
    assert close.run(local, None, out=lines.append) == 0
    assert not safefs.listdir(repo, OUT)
    for subject, (pass_id, old) in before.items():
        assert pass_id == f"helyi-{pass_id.split('-')[1]}-{subject}"           # the evidence records' pass id
        moved = files_under(repo, f".school-notes/done/{pass_id}")
        assert {p.replace(f".school-notes/done/{pass_id}/", f"{OUT}/{subject}/"): b for p, b in moved.items()} == old
        assert f"átadás elrakva: {OUT}/{subject} → .school-notes/done/{pass_id}" in lines
    assert local.records[-1] == ("close", "ok", {"subjects": "all", "failed": [],
                                                 "moved": [before[s][0] for s in sorted(before)]})


def test_a_subject_close_moves_only_the_named_subjects(repo, fake_local):
    handoff(repo)
    handoff(repo, subject="chemistry")
    assert close.run(fake_local(repo), ["chemistry"], out=quiet) == 0
    assert safefs.listdir(repo, OUT) == ["physics"]
    assert [d for d in safefs.listdir(repo, ".school-notes/done") if d.endswith("-chemistry")]


def test_a_replayed_pass_gets_its_own_folder_and_nothing_is_overwritten(repo, fake_local):
    snapshotted(repo)
    [h] = handoffs(repo, None)
    assert close.run(fake_local(repo), None, out=quiet) == 0
    snapshotted(repo)                                   # the same hand-over again: the same pass id
    assert close.run(fake_local(repo), None, out=quiet) == 0
    name = machine_data.pass_id(h)
    assert safefs.listdir(repo, ".school-notes/done") == [name, f"{name}-2"]


def test_a_stop_an_open_result_and_the_dry_runs_leave_the_hand_over(repo, fake_local, make_figure):
    make_figure()
    handoff(repo, [{"id": "forces", "page": PAGE, "route": "figure", "replaces": None}], {"forces": ACCEPT})
    local = fake_local(repo)
    assert close.run(local, None, out=quiet) == close.STOP                 # accept without a snapshot
    assert safefs.listdir(repo, OUT) == ["physics"] and not safefs.exists(repo, ".school-notes/done")
    assert close.run(local, None, snapshot_only=None, take_snapshot=True, out=quiet) == 0
    assert close.run(local, None, check=True, out=quiet) == 0
    assert safefs.listdir(repo, OUT) == ["physics"] and not safefs.exists(repo, ".school-notes/done")
    edit(repo, "Two forces act.", "Two forces act.\n\n[broken](nincs.md)")   # its own page-check error: exit 1
    close.run(local, None, snapshot_only=None, take_snapshot=True, out=quiet)
    assert close.run(local, None, out=quiet) == 1
    assert safefs.listdir(repo, OUT) == ["physics"] and not safefs.exists(repo, ".school-notes/done")


def test_move_never_replaces_and_never_follows_a_link(tmp_path):
    import os

    import pytest
    root = tmp_path / "r"
    (root / "a").mkdir(parents=True)
    (root / "a" / "x").write_text("1")
    (root / "b").mkdir()
    with pytest.raises(FileExistsError):
        safefs.move(root, "a", "b")
    assert (root / "a" / "x").read_text() == "1"
    os.symlink(tmp_path, root / "link")
    with pytest.raises(safefs.UnsafePath):
        safefs.move(root, "a", "link/c")
    safefs.move(root, "a", "d/e")
    assert (root / "d" / "e" / "x").read_text() == "1" and not (root / "a").exists()
    assert json.dumps(sorted(os.listdir(root))) == '["b", "d", "link"]'


def test_sn_check_writes_its_one_line(repo, fake_local, capsys):
    from school_notes2.local import check
    local = fake_local(repo)
    assert check.run(local, [PAGE]) == 0
    assert check.run(local, ["wiki/nincs.md"]) == 1
    edit(repo, "Two forces act.", "Two forces act.\n\n[broken](nincs.md)")
    assert check.run(local, [PAGE]) == 1
    [(c1, o1, f1), (c2, o2, f2), (c3, o3, f3)] = local.records
    assert (c1, o1, c2, o2, c3, o3) == ("check", "ok", "check", "refused", "check", "open")
    assert f1["pages"] == 1 and f1["errors"] == 0 and isinstance(f1["seconds"], float)
    assert f3["errors"] == 1 and "errors" not in f2


def test_the_command_line_and_the_library_steps_share_the_log_file(tmp_path):
    from types import SimpleNamespace

    from school_notes2.local.common import STEPS, Local
    local = Local(SimpleNamespace(log_path=tmp_path / "school-notes.log"), SimpleNamespace(name="barna"), tmp_path)
    assert local.steps.main == local.cfg.log_path and local.steps.steps == STEPS
    local.steps.event("site.live", "ok", target="https://x/publish.json", duration_s=2.0)
    local.record("check", "ok", pages=1)
    assert [json.loads(x)["action"] for x in local.cfg.log_path.read_text().splitlines()] == ["site.live", "sn.check"]
