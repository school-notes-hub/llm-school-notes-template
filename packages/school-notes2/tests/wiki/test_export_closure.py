"""Hash-bound rights and the exact common source note, with synthetic learners."""

import json

import pytest

from school_notes2.state import safefs
from school_notes2.wiki import public, frontmatter


def test_replaced_path_does_not_inherit_rights(repo):
    (repo / "wiki/assets/abra.svg").write_text("<svg>changed</svg>")
    with pytest.raises(public.PublicError):
        public.build(repo, public.render_rights(repo))


@pytest.mark.parametrize("digest", [None, "0" * 64, "current"])
def test_render_requires_matching_output_hash(repo, digest):
    asset = "wiki/assets/new/image.png"
    safefs.write_bytes(repo, asset, b"image")
    record = {} if digest is None else {"sha256": public.sha256(repo, asset) if digest == "current" else digest}
    safefs.write_json(repo, "wiki/assets/new/render.json", {"outputs": {"image.png": record}})
    assert bool(public.render_rights(repo)(asset)) == (digest == "current")


@pytest.mark.parametrize("digest", [None, "0" * 64, "current"])
def test_generated_requires_matching_published_hash(repo, digest):
    asset = "wiki/assets/generated.webp"
    safefs.write_bytes(repo, asset, b"image")
    (repo / "docs/evidence/media/generated").mkdir(parents=True)
    if digest:
        safefs.write_json(repo, "docs/evidence/media/generated/review-1.json", {
            "decision": "accepted", "sha256": "f" * 64,
            "publication": {"sha256": public.sha256(repo, asset) if digest == "current" else digest}})
    assert bool(public.media_receipt_rights(repo)(asset)) == (digest == "current")


@pytest.mark.parametrize("name,line", [("Minta", "Minta."), ("Próba", 'Próba - a wiki címe: "Próba jegyzetei".')])
def test_source_note_uses_authorized_profile_first_name(repo, name, line):
    safefs.write_text(repo, "PROFILE.md", f"* **Student**: {line}\n")
    rel = "wiki/proba/elso.md"
    safefs.write_text(repo, rel, frontmatter.set_keys(safefs.read_text(repo, rel), {"decisions": [{
        "id": "private-decision-canary", "claim": "PRIVATE_CLAIM_CANARY", "answer": "PRIVATE_ANSWER_CANARY",
        "by": "family", "on": "2026-10-04"}]}) + "\n<!-- q: private-question-canary -->\n<!-- figure-request: private-request-canary -->\n")
    value = public.build(repo, public.render_rights(repo))
    assert "CANARY" not in json.dumps(value) and "canary" not in json.dumps(value)
    assert "<!--" not in json.dumps(value)
    assert value["sourceNote"] == (f"A jegyzet {name} órai jegyzetei és a tanári anyagok alapján készült; "
                                  "mesterséges intelligencia egészítette ki és javította, és ahol a tankönyv "
                                  "rendelkezésre áll, azzal összevetette.")
    assert "decisions" not in json.dumps(value)


def test_source_copy_not_grandfathered_by_path_and_hash(repo):
    digest = public.sha256(repo, "wiki/assets/abra.svg")
    safefs.write_text(repo, "wiki/source.md", f"---\ncontent_sha256: {digest}\n---\n# Source\n")
    with pytest.raises(public.PublicError, match="source photo"):
        public.build(repo, public.render_rights(repo))


@pytest.mark.parametrize("digest", ["current", "0" * 64, None])
def test_legacy_licensed_rights_require_unchanged_bytes(repo, digest):
    known = public.read_existing(repo)
    asset = known["assets"][0]
    asset.update(rights="licensed", rightsEvidence="docs/evidence/legacy-cc.md")
    asset["sha256"] = public.sha256(repo, asset["path"]) if digest == "current" else digest
    if digest == "current":
        result = public.build(repo, lambda _: None, known)
        assert result["assets"][0]["rights"] == "licensed"
        assert result["assets"][0]["rightsEvidence"] == "docs/evidence/legacy-cc.md"
    else:
        with pytest.raises(public.PublicError):
            public.build(repo, lambda _: None, known)
