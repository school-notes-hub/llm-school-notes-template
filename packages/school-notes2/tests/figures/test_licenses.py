"""The request -> owner permission -> independent inspection -> credited insertion path."""

import pytest

from school_notes2.figures import commissions, context, insert, licenses, requests
from tests.figures.conftest import add_request
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
    records = add_request(repo, request, "a" * 64)
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


def test_license_records_scanned_once_per_call_and_never_stale(repo, make_figure, monkeypatch):
    safefs.write_text(repo, "wiki/index.md", "# Kezdőlap\n")
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    candidate = commissions.candidate(repo, brief)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    safefs.write_bytes(repo, "wiki/assets/other.png", b"other")
    text = safefs.read_text(repo, brief["page"])
    safefs.write_text(repo, brief["page"], text + "\n![Other](../assets/other.png)\n")
    calls = []
    original = licenses.records
    def scan(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(licenses, "records", scan)
    def invoke():
        return public.build(repo, lambda _: ("generated", "test"))
    invoke()
    assert len(calls) == 1
    grant(repo, scope="none")
    with pytest.raises(public.PublicError):
        invoke()
    assert len(calls) == 2


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


@pytest.mark.parametrize("change", ["withdraw", "credit", "missing-source"])
def test_changed_permission_is_owner_work_before_public_build(repo, make_figure, change):
    brief, value, request = requested(repo, make_figure)
    grant(repo)
    candidate = commissions.candidate(repo, brief)
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    if change == "withdraw":
        grant(repo, scope="none")
    elif change == "credit":
        grant(repo, credit="Changed credit")
    else:
        safefs.unlink(repo, request["source"])
    known = {candidate["asset"]: {"sha256": public.sha256(repo, candidate["asset"]), "rights": "authored"}}
    assert public.asset_entry(repo, candidate["asset"], known, lambda _: ("generated", "fake")) is None
