import pytest

from school_notes2.figures import context, insert, pending
from school_notes2.state import safefs


def receipt(repo, brief, candidate, verdict="accept"):
    return {"status": "reviewed", "model": "independent-model/high", "review": {
        "figures": [{"id": brief["id"], "key": context.verdict_key(repo, brief, candidate),
                     "verdict": verdict, "observed": "Two opposite arrows.", "defects": [],
                     "text_mismatch": [], "relates_to": None}], "owner_notes": []}}


@pytest.mark.parametrize("kind", ["figure", "banner"])
def test_accept_inserts_once_and_records_reviewer(repo, make_figure, kind):
    brief, candidate = make_figure(kind=kind)
    judged = receipt(repo, brief, candidate)
    pending.record(repo, brief, "run-1", [])
    insert.insert(repo, brief, judged, at="2026-10-04")
    text = safefs.read_text(repo, brief["page"])
    assert "<!-- figure: forces -->" not in text
    assert "![Two opposing arrows]" in text
    assert "observed: Two opposite arrows." in text
    evidence = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
    assert evidence["verifier"] == "independent-model/high"
    assert not pending.load(repo)
    assert not insert.invalidated(repo)
    before = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}
    insert.insert(repo, brief, judged, at="2026-10-04")
    assert before == {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}


@pytest.mark.parametrize("verdict", ["repair", "reject"])
def test_unaccepted_is_not_inserted(repo, make_figure, verdict):
    brief, candidate = make_figure()
    with pytest.raises(ValueError, match="accept"):
        insert.insert(repo, brief, receipt(repo, brief, candidate, verdict), at="date")
    assert "<!-- figure: forces -->" in safefs.read_text(repo, brief["page"])


@pytest.mark.parametrize("change", ["image", "alt", "caption", "section"])
def test_teaching_key_rejects_each_changed_component(repo, make_figure, change):
    brief, candidate = make_figure()
    judged = receipt(repo, brief, candidate)
    if change == "image":
        safefs.write_bytes(repo, candidate["asset"], b"changed")
    elif change == "section":
        safefs.write_text(repo, brief["page"], safefs.read_text(repo, brief["page"]).replace("Two forces act.", "One force acts."))
    else:
        candidate[change] += " changed"
        safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    with pytest.raises(ValueError, match="stale"):
        insert.insert(repo, brief, judged, at="date")


@pytest.mark.parametrize("change", ["title", "description", "image"])
def test_banner_key_rejects_each_changed_component(repo, make_figure, change):
    brief, candidate = make_figure(kind="banner")
    judged = receipt(repo, brief, candidate)
    if change == "image":
        safefs.write_bytes(repo, candidate["asset"], b"changed")
    else:
        text = safefs.read_text(repo, brief["page"])
        safefs.write_text(repo, brief["page"], text.replace(change + ": ", change + ": changed "))
    with pytest.raises(ValueError, match="stale"):
        insert.insert(repo, brief, judged, at="date")


@pytest.mark.parametrize("change", ["alt", "caption", "image", "section"])
def test_final_rebase_validation_uses_actual_page(repo, make_figure, change):
    brief, candidate = make_figure()
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    if change == "image":
        safefs.write_bytes(repo, candidate["asset"], b"different")
    else:
        old = {"alt": candidate["alt"], "caption": candidate["caption"], "section": "Two forces act."}[change]
        safefs.write_text(repo, brief["page"], safefs.read_text(repo, brief["page"]).replace(old, old + " changed"))
    assert len(insert.invalidated(repo)) == 1


def test_replacement_retains_old_file_and_only_removes_its_link(repo, make_figure):
    brief, candidate = make_figure()
    old = "wiki/assets/physics/old.png"
    safefs.write_bytes(repo, old, b"old bytes")
    brief.update(replaces=old, decision_reason={"code": "c", "text": "reviewer correction"})
    text = safefs.read_text(repo, brief["page"])
    text = text.replace("Two forces act.", "Two forces act.\n\n![old](../assets/physics/old.png)\n\n<!-- image-description\nobserved: old\n-->")
    safefs.write_text(repo, brief["page"], text)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    result = safefs.read_text(repo, brief["page"])
    assert "observed: old" not in result and "![old]" not in result
    assert safefs.read_bytes(repo, old) == b"old bytes"
    assert not insert.invalidated(repo)


def test_insertion_resume_after_evidence_before_page(repo, make_figure, monkeypatch):
    brief, candidate = make_figure()
    judged = receipt(repo, brief, candidate)
    original = safefs.write_text
    def crash(root, rel, text, *args, **kwargs):
        if rel == brief["page"]:
            raise KeyboardInterrupt
        return original(root, rel, text, *args, **kwargs)
    monkeypatch.setattr(safefs, "write_text", crash)
    with pytest.raises(KeyboardInterrupt):
        insert.insert(repo, brief, judged, at="date")
    monkeypatch.setattr(safefs, "write_text", original)
    insert.insert(repo, brief, judged, at="date")
    assert not insert.invalidated(repo)


def test_shared_figure_verdict_expires_when_another_use_changes(repo, make_figure):
    brief, candidate = make_figure()
    page = "wiki/physics/other.md"
    safefs.write_text(repo, page, "# Other\n\nA different use.\n\n![force](../assets/physics/forces.png)\n")
    judged = receipt(repo, brief, candidate)
    safefs.write_text(repo, page, safefs.read_text(repo, page).replace("A different use.", "Changed context."))
    with pytest.raises(ValueError, match="stale"):
        insert.insert(repo, brief, judged, at="date")


def test_replacing_previously_tool_inserted_figure_removes_its_whole_block(repo, make_figure):
    old, old_candidate = make_figure("old")
    insert.insert(repo, old, receipt(repo, old, old_candidate), at="date")
    brief, candidate = make_figure("new", replaces=old_candidate["asset"],
                                   decision_reason={"code": "c", "text": "correction"})
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    text = safefs.read_text(repo, brief["page"])
    assert "generated figure-old" not in text
    assert "generated figure-new" in text
    assert safefs.is_file(repo, old_candidate["asset"])


def test_marker_example_in_code_is_not_replaced(repo, make_figure):
    brief, candidate = make_figure()
    text = safefs.read_text(repo, brief["page"])
    text = text.replace("Two forces act.", "Two forces act.\n\n```md\n<!-- figure: forces -->\n```")
    safefs.write_text(repo, brief["page"], text)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    result = safefs.read_text(repo, brief["page"])
    assert "```md\n<!-- figure: forces -->\n```" in result
    assert "generated figure-forces" in result
    assert not insert.invalidated(repo)


def test_removed_banner_has_no_valid_verdict(repo, make_figure):
    from school_notes2.wiki import markers
    brief, candidate = make_figure(kind="banner")
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    text = markers.BLOCK.sub("", safefs.read_text(repo, brief["page"]))
    safefs.write_text(repo, brief["page"], text)
    assert len(insert.invalidated(repo)) == 1
