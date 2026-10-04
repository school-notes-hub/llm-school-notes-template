"""The request -> owner permission -> independent inspection -> credited insertion path."""

import pytest

from school_notes2.figures import commissions, context, insert, licenses, requests
from school_notes2.reader import notices
from school_notes2.state import safefs
from school_notes2.wiki import public
from test_insert import receipt


def requested(repo, make_figure, origin="teacher-own"):
    source = "sources/physics/material/figure.png"
    brief, value = make_figure(source_image={"path": source, "crop": [0, 0, 1000, 500]})
    safefs.write_bytes(repo, source, safefs.read_bytes(repo, value["asset"]))
    text = safefs.read_text(repo, brief["page"]).replace("<!-- figure:", "<!-- figure-request:")
    safefs.write_text(repo, brief["page"], text)
    request = {"id": brief["id"], "page": brief["page"], "source": source, "crop": "0,0,1000,500",
               "purpose": "Erők iránya", "origin": origin}
    pages = [{"path": source, "original_sha256": "a" * 64}]
    records = requests.collect(repo, [request], pages)
    safefs.write_json(repo, requests.PATH, records)
    return brief, value, records[0]


def grant(repo, **changes):
    value = {"sha256": "a" * 64, "granted_by": "Rights holder", "scope": "public-with-credit",
             "credit": "Credit: Public author", "own_work_confirmed": True, "on": "2026-10-04", **changes}
    safefs.write_json(repo, licenses.PATH, [value])
    return value


@pytest.mark.parametrize("origin", ["teacher-own", "third-party", "unknown"])
@pytest.mark.parametrize("scope,own", [("public-with-credit", True), ("public-with-credit", False), ("private", True), ("none", True)])
def test_only_public_confirmed_own_work_bypasses_owner_request(repo, make_figure, origin, scope, own):
    brief, value, request = requested(repo, make_figure, origin)
    grant(repo, scope=scope, own_work_confirmed=own)
    permitted = origin == "teacher-own" and scope == "public-with-credit" and own
    assert bool(licenses.permission(repo, request)) == permitted
    if permitted:
        assert "Credit: Public author" in commissions.candidate(repo, brief)["caption"]
    else:
        with pytest.raises(ValueError, match="public permission"):
            commissions.candidate(repo, brief)
        notices.refresh(repo, [brief["page"]])
        assert "⏳ Ehhez a részhez ábra készül." in safefs.read_text(repo, brief["page"])


def test_request_specific_owner_grant_and_independent_verdict_are_both_required(repo, make_figure):
    brief, value, request = requested(repo, make_figure, "third-party")
    grant(repo, request_id=brief["id"])
    candidate = commissions.candidate(repo, brief)
    assert licenses.rights(repo, candidate["asset"]) is None
    with pytest.raises(ValueError, match="independent"):
        insert.insert(repo, brief, {}, at="date")
    approved = receipt(repo, brief, candidate)
    before = context.verdict_key(repo, brief, candidate)
    insert.insert(repo, brief, approved, at="date")
    assert context.verdict_key(repo, brief, candidate) == before
    assert licenses.rights(repo, candidate["asset"])[0] == "licensed"
    assert "Credit: Public author" in safefs.read_text(repo, brief["page"])
    assert requests.active(repo) == []
    first = {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, "docs")}
    insert.insert(repo, brief, approved, at="date")
    assert first == {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo, "docs")}
    known = {candidate["asset"]: {"sha256": public.sha256(repo, candidate["asset"]), "rights": "licensed"}}
    grant(repo, request_id=brief["id"], scope="none")
    assert public.asset_entry(repo, candidate["asset"], known, lambda _: ("authored", "fake")) is None


def test_changed_source_or_asset_invalidates_permission(repo, make_figure):
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    candidate = commissions.candidate(repo, brief)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    safefs.write_bytes(repo, value["asset"], b"replacement")
    assert licenses.rights(repo, value["asset"]) is None
    safefs.write_bytes(repo, request["source"], b"changed source")
    assert licenses.permission(repo, request) is None


def test_material_hash_comes_from_original_document_not_extracted_image(repo):
    safefs.write_text(repo, "sources/pkg/document.md", "extracted")
    safefs.write_bytes(repo, "sources/pkg/figures/a.png", b"image")
    assert requests.original_hash(repo, "sources/pkg/figures/a.png", [
        {"path": "sources/pkg/document.md", "original_sha256": "b" * 64}]) == "b" * 64
    assert requests.original_hash(repo, "sources/pkg/figures/a.png") is None


def test_orphan_duplicate_and_reused_request_ids_are_rejected(repo, make_figure):
    brief, value, request = requested(repo, make_figure)
    with pytest.raises(ValueError, match="reused"):
        requests.collect(repo, [{**request, "purpose": "different"}])
    text = safefs.read_text(repo, brief["page"])
    safefs.write_text(repo, brief["page"], text + "\n<!-- figure-request: forces -->\n")
    with pytest.raises(ValueError, match="exactly one"):
        requests.collect(repo, [])


@pytest.mark.parametrize("crash", ["before", "after"])
def test_licensed_insertion_crash_resumes_without_premature_page_change(repo, make_figure, monkeypatch, crash):
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    candidate = commissions.candidate(repo, brief)
    approved = receipt(repo, brief, candidate)
    real = safefs.write_json
    def interrupted(root, path, data, **kw):
        if path.endswith("/figure.json"):
            if crash == "after":
                real(root, path, data, **kw)
            raise RuntimeError("power loss")
        return real(root, path, data, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(safefs, "write_json", interrupted)
        with pytest.raises(RuntimeError, match="power loss"):
            insert.insert(repo, brief, approved, at="date")
    assert "<!-- figure-request: forces -->" in safefs.read_text(repo, brief["page"])
    insert.insert(repo, brief, approved, at="date")
    assert licenses.rights(repo, candidate["asset"])[0] == "licensed"


@pytest.mark.parametrize("changes", [{"on": "2026-02-30"}, {"scope": "public"}, {"request_id": []}, {"credit": ""}])
def test_invalid_owner_record_is_rejected(repo, changes):
    grant(repo, **changes)
    with pytest.raises(ValueError):
        licenses.load(repo)


def test_request_order_does_not_depend_on_result_field_order(repo, make_figure):
    brief, value, request = requested(repo, make_figure)
    first = requests.collect(repo, [request])
    reordered = dict(reversed(list(request.items())))
    assert public.dumps(requests.collect(repo, [reordered])) == public.dumps(first)


def test_reviewer_sees_permission_and_credit_before_acceptance(repo, make_figure, tmp_path):
    from school_notes2.figures import inputs
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    folder = tmp_path / "review"
    inputs.prepare(repo, [brief], folder, lambda kind, data, fid: data)
    item = safefs.read_json(folder, "input.json")["figures"][0]
    assert item["licensed"]["scope"] == "public-with-credit"
    assert item["licensed"]["credit"] in item["embedding"]["caption"]
    assert "granted_by" not in item["licensed"]
    assert safefs.is_file(folder, item["source_crop"])


def test_hashless_legacy_request_needs_specific_content_bound_permission(repo, make_figure):
    brief, value, request = requested(repo, make_figure)
    request["original_sha256"] = None
    safefs.write_json(repo, requests.PATH, [request])
    grant(repo, sha256=request["content_sha256"])
    assert licenses.permission(repo, request) is None
    grant(repo, sha256="b" * 64, request_id=request["id"])
    assert licenses.permission(repo, request) is None
    grant(repo, sha256=request["content_sha256"], request_id=request["id"])
    assert licenses.permission(repo, request)
    safefs.unlink(repo, request["source"])
    assert licenses.permission(repo, request) is None


@pytest.mark.parametrize("fence", ["```md", "~~~md"])
def test_request_examples_do_not_become_active_or_pending(repo, make_figure, fence):
    brief, value, request = requested(repo, make_figure)
    text = safefs.read_text(repo, brief["page"])
    marker = f"<!-- figure-request: {request['id']} -->"
    safefs.write_text(repo, brief["page"], text.replace(marker, f"{fence}\n{marker}\n{fence[:3]}"))
    assert requests.active(repo) == []
    assert requests.collect(repo, []) == [request]
    notices.refresh(repo, [brief["page"]])
    assert notices.FIGURE not in safefs.read_text(repo, brief["page"])


@pytest.mark.parametrize("change", ["withdraw", "credit", "missing-source"])
def test_changed_permission_is_owner_work_before_public_build(repo, make_figure, change):
    from school_notes2.state.errors import NeedsOwner
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    candidate = commissions.candidate(repo, brief)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    licenses.preflight(repo)
    if change == "withdraw":
        grant(repo, scope="none")
    elif change == "credit":
        grant(repo, credit="Changed credit")
    else:
        safefs.unlink(repo, request["source"])
    with pytest.raises(NeedsOwner, match="permission changed or withdrawn"):
        licenses.preflight(repo)
    known = {candidate["asset"]: {"sha256": public.sha256(repo, candidate["asset"]), "rights": "authored"}}
    assert public.asset_entry(repo, candidate["asset"], known, lambda _: ("generated", "fake")) is None
