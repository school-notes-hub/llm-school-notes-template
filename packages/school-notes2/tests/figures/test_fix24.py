"""Legacy generated headers remain accepted; replacements remove v1 evidence."""

import hashlib

import pytest

from school_notes2.figures import context, machine, migrate_pending, pending
from school_notes2.state import safefs
from school_notes2.wiki import banners, frontmatter, rights


@pytest.mark.parametrize("learner", ["one", "two"])
@pytest.mark.parametrize("compression_format", ["list", "images"])
@pytest.mark.parametrize("proof", ["public", "compression", "both"])
def test_v1_webp_is_not_regenerated(repo, monkeypatch, learner, proof, compression_format):
    page, asset = f"wiki/{learner}/topic.md", f"wiki/assets/{learner}.webp"
    data = b"v1 webp"
    digest = hashlib.sha256(data).hexdigest()
    safefs.write_bytes(repo, asset, data)
    safefs.write_text(repo, page, f"---\ntype: topic\ntitle: Topic\n---\n![Header](../assets/{learner}.webp)\n\nText.\n")
    if proof in ("public", "both"):
        safefs.write_json(repo, "publication/public.json", {"assets": [
            {"path": asset, "rights": "generated", "sha256": digest}]})
    if proof in ("compression", "both"):
        safefs.write_json(repo, "docs/evidence/image-generation/v1.json", {
            "rights": "generated", "outputs": ["original-png-hash"]})
        receipt = [{"original": "wiki/assets/old.png", "original_sha256": "original-png-hash",
                    "published": asset, "published_sha256": digest}]
        if compression_format == "images":
            receipt[0]["source_sha256"] = receipt[0].pop("original_sha256")
            receipt = {"images": receipt}
        safefs.write_json(repo, "docs/evidence/v1-banner-compression.json", receipt)
        assert rights.media(repo)(asset)[0] == "generated"
    assert banners.generated_header(repo, page, frontmatter.split(safefs.read_text(repo, page)).body)
    assert not machine.generation_errors(repo, {"kind": "banner"}, {"asset": asset})
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {})
    preview = migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object(), dry_run=True)
    assert preview["commissions"] == []
    safefs.write_bytes(repo, asset, b"changed bytes")
    assert not banners.generated_header(repo, page, frontmatter.split(safefs.read_text(repo, page)).body)


def test_compression_requires_generated_original_and_exact_target(repo):
    safefs.write_bytes(repo, "wiki/assets/header.webp", b"image")
    record = {"original_sha256": "unknown", "published": "wiki/assets/header.webp",
              "published_sha256": hashlib.sha256(b"image").hexdigest()}
    safefs.write_json(repo, "docs/evidence/v1-banner-compression.json", [record])
    assert rights.media(repo)(record["published"]) is None
    safefs.write_json(repo, "docs/evidence/image-generation/v1.json", {"rights": "generated", "outputs": ["unknown"]})
    record["published"] = "wiki/assets/other.webp"
    safefs.write_json(repo, "docs/evidence/v1-banner-compression.json", [record])
    assert rights.media(repo)("wiki/assets/header.webp") is None


@pytest.mark.parametrize("comment", ["<!-- image-description: old -->", "<!-- image-description\nold\n-->"])
def test_replacement_removes_only_own_description(comment):
    text = f"![Old](../assets/old.svg)\n{comment}\n\nText.\n\n![Other](../assets/other.svg)\n<!-- image-description: keep -->\n"
    result = context.without_replaced(text, "wiki/m/topic.md", "wiki/assets/old.svg")
    assert "old" not in result
    assert "<!-- image-description: keep -->" in result
    assert "Text." in result


def test_missing_pending_page_is_listed_and_untouched(repo, make_figure, monkeypatch):
    brief, _ = make_figure(kind="banner")
    entry = pending.record(repo, brief, "old", [], attempted=True)
    safefs.unlink(repo, brief["page"])
    monkeypatch.setattr(migrate_pending, "historical", lambda *a: {})
    result = migrate_pending.migrate(repo, state_dir=repo.parent / "state", repo=object())
    assert result["skipped"] == [{"id": brief["id"], "page": brief["page"]}]
    assert pending.load(repo) == [entry]
