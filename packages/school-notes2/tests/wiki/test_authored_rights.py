"""Independent figure acceptance grants rights only to the reviewed output bytes."""

import pytest

from school_notes2.state import safefs
from school_notes2.wiki import public


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("source", ["asset", "editable"])
def test_accepted_authored_figure_without_render(repo, explicit, source):
    asset, record = authored(repo, source=source)
    if explicit:
        record["rights"] = "authored"
    safefs.write_json(repo, "docs/evidence/media/own/figure.json", record)
    result = public.build(repo, public.media_receipt_rights(repo))
    entry = next(a for a in result["assets"] if a["path"] == asset)
    assert entry["rights"] == "authored"
    assert entry["sha256"] == record["output_sha256"]
    assert entry["rightsEvidence"] == "docs/evidence/media/own/figure.json"
    assert public.dumps(result) == public.dumps(public.build(repo, public.media_receipt_rights(repo)))


def authored(repo, source="asset"):
    asset = "wiki/assets/own.svg"
    safefs.write_text(repo, asset, '<svg xmlns="http://www.w3.org/2000/svg"/>')
    editable = asset if source == "asset" else "wiki/assets/own.py"
    if editable != asset:
        safefs.write_text(repo, editable, "# editable drawing source\n")
    safefs.write_text(repo, "wiki/own.md", "# Saját ábra\n\n![Ábra](assets/own.svg)\n")
    record = {"candidate": {"state": "candidate", "asset": asset, "source": editable},
              "verdict": {"verdict": "accept"}, "output_sha256": public.sha256(repo, asset)}
    return asset, record


@pytest.mark.parametrize("problem", ["repair", "reject", "no-verdict", "wrong-hash", "no-hash",
                                    "no-source", "missing-source", "private-source", "work-source",
                                    "licensed", "license-request", "license", "failed"])
def test_unproven_figure_grants_no_authored_rights(repo, problem):
    asset, record = authored(repo)
    if problem in ("repair", "reject"):
        record["verdict"]["verdict"] = problem
    elif problem == "no-verdict":
        record.pop("verdict")
    elif problem == "wrong-hash":
        record["output_sha256"] = "0" * 64
    elif problem == "no-hash":
        record.pop("output_sha256")
    elif problem == "no-source":
        record["candidate"].pop("source")
    elif problem.endswith("source"):
        record["candidate"]["source"] = {"missing-source": "wiki/assets/missing.svg",
            "private-source": "sources/own.svg", "work-source": ".school-notes/figures/own/source.py"}[problem]
    elif problem == "licensed":
        record["rights"] = "licensed"
    elif problem in ("license-request", "license"):
        record[problem.replace("-", "_")] = {"id": "licensed"}
    else:
        record["candidate"]["state"] = "failed"
    safefs.write_json(repo, "docs/evidence/media/own/figure.json", record)
    assert public.media_receipt_rights(repo)(asset) is None


@pytest.mark.parametrize("origin", ["figure", "ledger", "review"])
def test_generated_receipt_keeps_precedence_over_local_source(repo, origin):
    asset, record = authored(repo)
    safefs.write_json(repo, "docs/evidence/media/own/figure.json", record)
    if origin == "figure":
        record["rights"] = "generated"
        path, value = "docs/evidence/media/own/figure.json", record
    elif origin == "ledger":
        path = "docs/evidence/image-generation/ledger.json"
        value = {"rights": "generated", "outputs": [record["output_sha256"]]}
    else:
        path = "docs/evidence/media/own/review-1.json"
        value = {"decision": "accepted", "sha256": record["output_sha256"]}
    safefs.write_json(repo, path, value)
    assert public.media_receipt_rights(repo)(asset) == ("generated", path)
