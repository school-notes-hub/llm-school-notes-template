import time

from school_notes2.review import files, relations, topic_result
from school_notes2.state import safefs
from school_notes2.wiki import frontmatter


def report(repo, count=300):
    rel = "docs/review/large.md"
    safefs.write_text(repo, rel, frontmatter.set_keys("# Review\n", {
        "items": {f"R{i}": "fixed" for i in range(count)},
        "item_details": {f"R{i}": {"file": "wiki/m/a.md", "round": 1, "chain": 0} for i in range(count)}}))
    return rel


def test_inventory_300_items_under_one_second_and_one_parse(tmp_path, monkeypatch):
    rel = report(tmp_path)
    files._parsed_report.cache_clear()
    original, calls = frontmatter.split, []
    def split(text):
        calls.append(1)
        return original(text)
    monkeypatch.setattr(frontmatter, "split", split)
    start = time.perf_counter()
    found = relations.inventory(tmp_path)
    elapsed = time.perf_counter() - start
    assert len(found["items"]) == 300
    assert len(calls) == 1
    assert elapsed < 1, elapsed
    calls.clear()
    files.open_items(tmp_path, "cron")
    assert not calls


def test_batch_closure_parses_once_and_replay_is_identical(tmp_path, monkeypatch):
    rel = report(tmp_path)
    files._parsed_report.cache_clear()
    original, calls = frontmatter.split, []
    def split(text):
        calls.append(1)
        return original(text)
    monkeypatch.setattr(frontmatter, "split", split)
    answers = [({"status": "fixed"}, {"key": f"{rel}#R{i}", "verdict": "ok", "answer": "Javítva."}) for i in range(300)]
    assert topic_result.apply_items(tmp_path, answers) == ([rel], [])
    assert len(calls) == 1
    before = safefs.read_bytes(tmp_path, rel)
    assert topic_result.apply_items(tmp_path, answers) == ([], [])
    assert safefs.read_bytes(tmp_path, rel) == before


def test_measured_steps_log_duration_even_on_failure(tmp_path, log, monkeypatch):
    import json
    from types import SimpleNamespace
    import pytest
    from school_notes2.flows import review_phases, night_topics
    from school_notes2.review import close
    def broken(*a, **kw):
        raise ValueError("injected")
    monkeypatch.setattr(review_phases, "_finalize", broken)
    monkeypatch.setattr(review_phases, "_final_keys", broken)
    monkeypatch.setattr(close, "_close_report", broken)
    monkeypatch.setattr(night_topics.topic_input, "prepare", broken)
    ctx = SimpleNamespace(log=log)
    task = SimpleNamespace(dir=tmp_path)
    for action in (lambda: review_phases.finalize(ctx, task), lambda: review_phases.final_keys(ctx, task),
                   lambda: close.close(task, ctx, None, None),
                   lambda: night_topics._topic(ctx, task, {"topic": "wiki/a.md"}, None, None, None, None)):
        with pytest.raises(ValueError, match="injected"):
            action()
    events = [json.loads(line) for line in log.main.read_text().splitlines()]
    assert {e["action"] for e in events} == {"review.finalize", "review.final_keys", "review.close", "review.topic_input"}
    assert all(e["duration_s"] >= 0 and e["outcome"] == "error" for e in events)


def test_cached_report_never_reuses_mutations_or_same_size_stale_content(tmp_path):
    rel = report(tmp_path, 1)
    text = safefs.read_text(tmp_path, rel)
    first = files.read_report(tmp_path, tmp_path / rel)
    first.meta["items"]["R0"] = "owner"
    assert files.read_report(tmp_path, tmp_path / rel).meta["items"]["R0"] == "fixed"
    safefs.write_text(tmp_path, rel, text.replace("fixed", "owner"))
    assert relations.inventory(tmp_path)["items"][rel + "#R0"]["status"] == "owner"
