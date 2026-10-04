import hashlib
import io
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from school_notes2.config import Harness, Role
from school_notes2.figures import context, inputs, review
from school_notes2.llm import launch
from school_notes2.state import safefs
from school_notes2.state.errors import Transient


def response(assigned, verdict="accept"):
    return {"figures": [{**item, "verdict": verdict, "observed": "Two opposing arrows.",
                         "defects": [], "text_mismatch": [], "relates_to": None}
                        for item in assigned["figures"]], "owner_notes": []}


def make_run(tmp_path):
    return launch.RoleRun(learner="student", run_id="run-1", role_name="reviewer",
                          role=Role("claude-review", "configured-reviewer", "high", 5400),
                          harness=Harness("claude-review", [], [], []), image="local",
                          mounts=launch.Mounts(), output_host=tmp_path / "unused",
                          schema="review", task_dir=tmp_path / "task", grade=11)


def fake_render(kind, data, fid):
    if kind == "png":
        return data
    out = io.BytesIO()
    Image.new("RGB", (1000, 500), "white").save(out, format="PNG")
    return out.getvalue()


def success(run, **kwargs):
    assigned = safefs.read_json(run.mounts.in_dir, "assigned.json")
    value = response(assigned)
    safefs.write_json(run.mounts.out_dir, "review.json", value)
    return SimpleNamespace(output=value)


def test_input_has_full_phone_crop_context_and_no_self_evaluation(repo, make_figure, tmp_path):
    brief, candidate = make_figure()
    brief["source_image"] = {"path": candidate["asset"], "crop": [10, 10, 200, 100]}
    folder = tmp_path / "input"
    inputs.prepare(repo, [brief], folder, fake_render)
    item = safefs.read_json(folder, "input.json")["figures"][0]
    for key, size in [("full", (1000, 500)), ("phone", (390, 195)), ("source_crop", (190, 90))]:
        with Image.open(folder / item[key]) as image:
            assert image.size == size
    assert item["embedding"]["alt"] == candidate["alt"]
    assert item["embedding"]["caption"] == candidate["caption"]
    assert "Two forces act." in item["embedding"]["section"]
    assert item["uses"][0]["questions"] == []
    assert "prompt" not in item and "candidate" not in item and "corrections" not in item


def test_mermaid_is_rendered_not_just_passed_as_text(repo, make_figure, tmp_path):
    brief, candidate = make_figure()
    text = safefs.read_text(repo, brief["page"]) + "```mermaid\ngraph LR\n A --> B\n```\n"
    safefs.write_text(repo, brief["page"], text)
    candidate.pop("asset")
    candidate["mermaid"] = hashlib.sha256(b"graph LR\n A --> B\n").hexdigest()
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    seen = []
    def renderer(kind, data, fid):
        seen.append((kind, data))
        return fake_render(kind, data, fid)
    inputs.prepare(repo, [brief], tmp_path / "input", renderer)
    assert seen == [("mermaid", b"graph LR\n A --> B\n")]
    assert (tmp_path / "input/images/forces.png").is_file()


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra", "key"])
def test_review_completeness_and_hash(repo, make_figure, failure):
    brief, candidate = make_figure()
    assigned = {"figures": [{"id": brief["id"], "key": context.verdict_key(repo, brief, candidate)}]}
    value = response(assigned)
    if failure == "missing":
        value["figures"] = []
    if failure == "duplicate":
        value["figures"] *= 2
    if failure == "extra":
        value["figures"].append({**value["figures"][0], "id": "extra"})
    if failure == "key":
        value["figures"][0]["key"] = "0" * 64
    with pytest.raises(ValueError):
        review.validate_output(value, assigned, repo, [brief])


def test_role_receipt_resume_and_mounts(repo, make_figure, tmp_path, log):
    brief, _ = make_figure()
    run = make_run(tmp_path)
    calls = []
    def invoke(actual, **kwargs):
        calls.append(actual)
        assert actual.mounts.work == repo / "wiki"
        assert actual.mounts.work_readonly and actual.mounts.sessdir is None
        assert actual.role_name == "figure-review" and actual.role.timeout_s == 1800
        assert launch._volume_role(actual.role_name) == "reviewer"
        return success(actual)
    first = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=invoke)
    second = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=invoke)
    assert first == second and len(calls) == 1
    assert first["model"] == "configured-reviewer/high"
    assert safefs.read_json(repo, ".school-notes/figure-review/physics-1.json") == first["review"]


def test_crash_after_output_reuses_valid_output(repo, make_figure, tmp_path, log):
    brief, _ = make_figure()
    run = make_run(tmp_path)
    def crash(actual, **kwargs):
        success(actual)
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=crash)
    result = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log,
                              invoke=lambda *a, **kw: pytest.fail("must reuse output"))
    assert result["status"] == "reviewed"


def test_crash_after_receipt_replays_repo_writes(repo, make_figure, tmp_path, log, monkeypatch):
    brief, _ = make_figure()
    run = make_run(tmp_path)
    original = review._save
    def crash(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(review, "_save", crash)
    with pytest.raises(KeyboardInterrupt):
        review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=success)
    monkeypatch.setattr(review, "_save", original)
    result = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log,
                              invoke=lambda *a, **kw: pytest.fail("must reuse receipt"))
    assert result["status"] == "reviewed"


@pytest.mark.parametrize("kind,expected", [("format", 2), ("crash", 2), ("timeout", 1)])
def test_retry_is_bounded_and_stays_bounded_after_resume(repo, make_figure, tmp_path, log, kind, expected):
    brief, _ = make_figure()
    run = make_run(tmp_path)
    calls = []
    def fail(actual, **kwargs):
        calls.append(actual)
        if kind == "crash":
            raise Transient("container crashed")
        if kind == "timeout":
            raise launch.TimedOut("timeout")
        return SimpleNamespace(output={"figures": [], "owner_notes": []})
    for _ in range(2):
        result = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=fail)
        assert result["status"] == "pending"
    assert len(calls) == expected


def test_format_retry_contains_error_and_can_succeed(repo, make_figure, tmp_path, log):
    brief, _ = make_figure()
    run = make_run(tmp_path)
    calls = []
    def invoke(actual, **kwargs):
        calls.append(actual)
        if len(calls) == 1:
            return SimpleNamespace(output={"figures": [], "owner_notes": []})
        assert "exactly one" in safefs.read_json(actual.mounts.in_dir, "format-error.json")["error"]
        return success(actual)
    result = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=invoke)
    assert result["status"] == "reviewed" and len(calls) == 2


def test_figure_prompt_contract():
    text = launch.prompt("figure-review", grade=11)
    assert text.startswith("A cél a termék lehető legjobbra fejlesztése:")
    assert "Számold újra a számokat és irányokat a forrásból" in text
    assert "A gépi jelentés (betűméret, számegyezés, minta) nem jelöli ki, mit nézz:" in text
    assert "egy műfajt tanító oldalon a példaként elemzett mű egyik motívuma" in text
    assert "A 11. évfolyamos tanulónak az ábrából" in text
    assert "8. Nem másolat-e?" in text
    assert "/out/review.json" in text
    assert "A válasz végén írd ki" in launch.prompt("figure-review", "stdout", grade=11)


def test_all_shared_figure_uses_are_review_input(repo, make_figure, tmp_path):
    brief, candidate = make_figure()
    safefs.write_text(repo, "wiki/physics/other.md", "---\ntitle: Other\n---\n# Other\n\n"
                      "The other body's force.\n\n![other alt](../assets/physics/forces.png)\n")
    folder = tmp_path / "input"
    inputs.prepare(repo, [brief], folder, fake_render)
    uses = safefs.read_json(folder, "input.json")["figures"][0]["uses"]
    assert len(uses) == 2
    assert uses[1]["alts"] == ["other alt"]
    assert "other body's force" in uses[1]["text"]


def test_resume_after_insertion_does_not_render_or_call_again(repo, make_figure, tmp_path, log):
    from school_notes2.figures.insert import insert
    brief, _ = make_figure()
    run = make_run(tmp_path)
    result = review.run_batch(repo, [brief], "physics-1", run, render=fake_render, log=log, invoke=success)
    insert(repo, brief, result, at="date")
    def forbidden(*args, **kwargs):
        pytest.fail("accepted review must be reused")
    assert review.run_batch(repo, [brief], "physics-1", run, render=forbidden, log=log, invoke=forbidden) == result
