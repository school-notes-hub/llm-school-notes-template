"""Rights failures return to the writer before independent inspection."""

import pytest

from school_notes2.figures import commissions, insert, machine, requests
from school_notes2.state import safefs
from school_notes2.wiki import public
from school_notes2.wiki.check_result import check_result
from test_insert import receipt
from test_licenses import grant, requested


@pytest.mark.parametrize("kind", ["png-py", "svg-py", "svg-other", "svg-work", "no-source"])
def test_unproven_candidate_is_a_writer_error(repo, make_figure, kind):
    brief, candidate = make_figure()
    safefs.unlink(repo, "wiki/assets/physics/render.json")
    if kind.startswith("svg"):
        candidate["asset"] = "wiki/assets/physics/forces.svg"
        safefs.write_text(repo, candidate["asset"], '<svg xmlns="http://www.w3.org/2000/svg"/>')
    if kind != "no-source":
        candidate["source"] = (".school-notes/figures/forces/source.svg" if kind == "svg-work" else
                               "wiki/assets/physics/other.svg" if kind == "svg-other" else
                               "wiki/assets/physics/source.py")
        safefs.write_text(repo, candidate["source"], '<svg width="100"/>' if kind == "svg-other" else
                          safefs.read_text(repo, candidate["asset"]) if kind == "svg-work" else "# Drawing source\n")
    safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    assert any("no rights path" in error for error in machine.report(repo, brief, candidate)["errors"])
    assignment = {k: brief[k] for k in ("id", "kind", "page")}
    errors = commissions.check(repo, [assignment])
    assert any("no rights path" in error["message"] and error["severity"] == "error" for error in errors)
    # Acceptance cannot turn the same unrelated source into authored evidence.
    insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
    record = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
    assert "rights" not in record
    assert public.media_receipt_rights(repo)(candidate["asset"]) is None


@pytest.mark.parametrize("route", ["render", "generated", "host", "svg", "svg-copy", "licensed", "new-license"])
def test_check_result_accepts_each_proven_rights_route(repo, make_figure, route):
    result = {"status": "done"}
    if route in ("licensed", "new-license"):
        brief, candidate, request = requested(repo, make_figure)
        grant(repo)
        if route == "new-license":
            safefs.unlink(repo, requests.PATH)
            result["figure_requests"] = [request]
            grant(repo, sha256=request["content_sha256"], request_id=request["id"])
    else:
        brief, candidate = make_figure()
    if route != "render":
        safefs.unlink(repo, "wiki/assets/physics/render.json")
    generated = None
    if route in ("generated", "host"):
        digest = public.sha256(repo, candidate["asset"])
        if route == "generated":
            safefs.write_json(repo, "docs/evidence/image-generation/ledger.json",
                              {"rights": "generated", "outputs": [digest]})
        else:
            generated = lambda rel: ("generated", "host image ledger") if public.sha256(repo, rel) == digest else None
    if route.startswith("svg"):
        candidate["asset"] = candidate["source"] = "wiki/assets/physics/forces.svg"
        safefs.write_text(repo, candidate["asset"], '<svg xmlns="http://www.w3.org/2000/svg"/>')
        if route == "svg-copy":
            candidate["source"] = "wiki/assets/physics/source.svg"
            safefs.write_bytes(repo, candidate["source"], safefs.read_bytes(repo, candidate["asset"]))
        safefs.write_json(repo, ".school-notes/figures/forces/figure.json", candidate)
    result["figures"] = [{k: brief[k] for k in ("id", "kind", "page")}]
    fetch = {"mode": "interactive", "packages": [], "pages": []}
    assert check_result(repo, result, fetch, set(), generated=generated) == []
    if route.startswith("svg"):
        insert.insert(repo, brief, receipt(repo, brief, candidate), at="date")
        record = safefs.read_json(repo, "docs/evidence/media/forces/figure.json")
        assert record["rights"] == "authored"


def test_generation_hash_must_match_before_review(repo, make_figure):
    brief, candidate = make_figure()
    safefs.unlink(repo, "wiki/assets/physics/render.json")
    safefs.write_json(repo, "docs/evidence/image-generation/ledger.json",
                      {"rights": "generated", "outputs": ["0" * 64]})
    assert any("no rights path" in error for error in commissions.preflight(repo, brief))
