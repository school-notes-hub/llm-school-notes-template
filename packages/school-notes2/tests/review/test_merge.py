import pytest

from school_notes2.review import files
from school_notes2.review.merge import merge
from school_notes2.wiki import frontmatter


@pytest.mark.parametrize("upstream", ["fixed", "question", "settled", "owner"])
@pytest.mark.parametrize("own_status", [None, "open"])
def test_merge_refuses_upstream_change_in_own_before_map(tmp_path, upstream, own_status):
    path = files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": "R3", "file": "wiki/a.md", "problem": "Javítandó."}]}, "r", "a", "b")
    rel = path.relative_to(tmp_path).as_posix()
    listed = files.open_items(tmp_path, "cron")
    base = path.read_bytes()
    closure = [{"file": rel, "item_id": "R3", "status": own_status}] if own_status else []
    files.apply_closure(tmp_path, "own", closure, listed)
    own = path.read_bytes()
    origin = frontmatter.set_keys(base.decode(), {"items": {"R3": upstream}}).encode()
    # Without this refusal, a later CheckFailed/rerun restores R3 to open.
    assert merge([base, origin, own]) is None
    assert path.read_bytes() == own


def test_unrelated_upstream_change_survives_merge_and_repeated_closure(tmp_path):
    path = files.write_review(tmp_path, "2026-10-04", {"verdict": "changes", "findings": [
        {"id": key, "file": "wiki/a.md", "problem": "Javítandó."} for key in ("R1", "R3")
    ]}, "r", "a", "b")
    rel = path.relative_to(tmp_path).as_posix()
    base = path.read_bytes()
    listed = [{"file": rel, "item_id": "R3"}]
    files.apply_closure(tmp_path, "own", [], listed)
    origin = frontmatter.set_keys(base.decode(), {"items": {"R1": "fixed", "R3": "open"}}).encode()
    merged = merge([base, origin, path.read_bytes()])
    assert merged is not None
    path.write_bytes(merged)
    files.apply_closure(tmp_path, "own", [], listed)
    assert path.read_bytes() == merged
    assert frontmatter.split(path.read_text()).meta["items"] == {"R1": "fixed", "R3": "open"}
