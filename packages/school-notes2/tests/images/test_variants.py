"""Rejected plans resume through the real executor without sockets or migration."""

from decimal import Decimal

import pytest

from image_fakes import PLAN, TOOLS, _image_answer, make_worktree
from school_notes2.images import executor, generate, plans
from school_notes2.images.settings import ImageSettings
from school_notes2.state.files import read_json, write_json


@pytest.fixture
def local_images(tmp_path, monkeypatch):
    def setup(student):
        repo = make_worktree(tmp_path, student)
        settings = ImageSettings(student, repo, TOOLS / "learning_image.py", tmp_path / "state",
                                 tmp_path / "plans", tmp_path / "lock", tmp_path / "key",
                                 Decimal("10"), Decimal("5"))
        api = executor.module(settings.script)
        config = read_json(settings.write_executor_config(tmp_path, plans.target("termeles-banner"), repo))
        api.initialize_state(config)
        calls = []
        def transport(payload, config):
            calls.append(payload)
            return _image_answer(len(calls))
        def call(settings, command, args, target, **kwargs):
            job = args[args.index("--job") + 1]
            if command == "preview-banner":
                return api.preview_banner(config, job)
            repair = tmp_path / "repair.txt"
            if kwargs.get("files"):
                repair.write_text(kwargs["files"]["repair.txt"])
            try:
                return api.run_generate(config, job, repair if kwargs.get("files") else None, transport)
            except ValueError as exc:
                raise executor.ExecutorError(str(exc)) from exc
        monkeypatch.setattr(generate, "call", call)
        return settings, calls
    return setup


def reject(settings, state="rejected"):
    ledger = settings.ledger()
    entry = ledger["jobs"][plans.job_id(settings.learner, "termeles-banner")]
    entry["attempts"][-1]["state"] = state
    write_json(settings.state_dir / "ledger.json", ledger)


def change_plan(settings, number=2):
    write_json(settings.worktree / plans.target("termeles-banner"),
               {**PLAN, "composition": f"Javított elrendezés {number}."})


@pytest.mark.parametrize("student", ["benedek", "barna"])
@pytest.mark.parametrize("state", ["rejected", "lost"])
@pytest.mark.parametrize("repair", [None, "A cím legyen olvasható."])
def test_legacy_job_generates_new_variants_with_shared_limit(local_images, log, student, state, repair):
    settings, calls = local_images(student)
    first = generate.generate(settings, "termeles-banner", log=log)
    assert first["state"] == "generated"
    key = plans.job_id(student, "termeles-banner")
    assert "variants" not in settings.ledger()["jobs"][key]
    legacy = settings.ledger()
    legacy["jobs"][key]["attempts"][0].pop("fingerprint")
    write_json(settings.state_dir / "ledger.json", legacy)
    for n in (2, 3):
        reject(settings, state)
        change_plan(settings, n)
        result = generate.generate(settings, "termeles-banner", repair, log=log)
        assert result["state"] == "generated" and result["number"] == n
        assert result["attempts_left"] == 3 - n
        assert (settings.worktree / result["preview"]).is_file()
    reject(settings, state)
    change_plan(settings, 4)
    before = (settings.state_dir / "ledger.json").read_bytes()
    assert generate.generate(settings, "termeles-banner", repair, log=log)["state"] == "exhausted"
    assert (settings.state_dir / "ledger.json").read_bytes() == before
    assert len(calls) == 3
    entry = settings.ledger()["jobs"][key]
    assert [(v["id"], v["previous"]) for v in entry["variants"]] == [
        (key + "~2", key), (key + "~3", key + "~2")]
    assert [v["first_attempt"] for v in entry["variants"]] == [2, 3]


@pytest.mark.parametrize("student", ["benedek", "barna"])
@pytest.mark.parametrize("state", ["generated", "accepted", "unknown"])
@pytest.mark.parametrize("repair", [None, "Javítás."])
def test_changed_unreviewed_or_accepted_plan_is_refused(local_images, log, student, state, repair):
    settings, calls = local_images(student)
    generate.generate(settings, "termeles-banner", log=log)
    reject(settings, state)
    job_path = plans.job_path(settings, "termeles-banner")
    before = job_path.read_bytes()
    ledger_before = (settings.state_dir / "ledger.json").read_bytes()
    change_plan(settings)
    result = generate.generate(settings, "termeles-banner", repair, log=log)
    assert result["state"] == "error" and "ítéletre váró" in result["message"]
    assert len(calls) == 1
    assert job_path.read_bytes() == before
    assert (settings.state_dir / "ledger.json").read_bytes() == ledger_before


@pytest.mark.parametrize("student", ["benedek", "barna"])
def test_variant_preview_crash_resumes_without_spending_again(local_images, log, monkeypatch, student):
    settings, calls = local_images(student)
    generate.generate(settings, "termeles-banner", log=log)
    reject(settings)
    change_plan(settings)
    with monkeypatch.context() as patch:
        def crash(*args):
            raise RuntimeError("preview interrupted")
        patch.setattr(generate, "_preview", crash)
        with pytest.raises(RuntimeError, match="preview interrupted"):
            generate.generate(settings, "termeles-banner", "Javítás.", log=log)
    result = generate.generate(settings, "termeles-banner", log=log)
    assert result["state"] == "generated" and result["number"] == 2
    assert len(calls) == 2
    entry = settings.ledger()["jobs"][plans.job_id(student, "termeles-banner")]
    assert len(entry["variants"]) == 1 and len(entry["attempts"]) == 2


def test_lost_last_attempt_does_not_reuse_an_older_unreviewed_image(local_images, log):
    settings, calls = local_images("barna")
    generate.generate(settings, "termeles-banner", log=log)
    generate.generate(settings, "termeles-banner", "Javítás.", log=log)
    reject(settings, "lost")
    result = generate.generate(settings, "termeles-banner", log=log)
    assert result["number"] == 3 and len(calls) == 3


def test_logical_alias_preserves_plan_preview_path(local_images, log, monkeypatch):
    settings, calls = local_images("barna")
    original = plans.build_job
    with monkeypatch.context() as patch:
        patch.setattr(plans, "build_job", lambda *a: {**original(*a), "id": "legacy-banner"})
        generate.generate(settings, "termeles-banner", log=log)
    ledger = settings.ledger()
    ledger["jobs"]["legacy-banner"]["attempts"][-1]["state"] = "rejected"
    write_json(settings.state_dir / "ledger.json", ledger)
    change_plan(settings)
    result = generate.generate(settings, "termeles-banner", "Javítás.", log=log)
    assert result["number"] == 2 and len(calls) == 2
    assert result["preview"] == ".school-notes/images/termeles-banner-2-publication.webp"
    assert list(settings.ledger()["jobs"]) == ["legacy-banner"]
