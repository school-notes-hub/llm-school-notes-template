"""Hash-bound rights and the exact common source note, with synthetic learners."""

import json

import pytest

from school_notes2.state import safefs
from school_notes2.wiki import public, footnotes


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
    value = public.build(repo, public.render_rights(repo))
    assert value["sourceNote"] == (f"A jegyzet {name} órai jegyzetei és a tanári anyagok alapján készült; "
                                  "mesterséges intelligencia egészítette ki és javította, és ahol a tankönyv "
                                  "rendelkezésre áll, azzal összevetette.")
    assert "decisions" not in json.dumps(value)


def test_source_copy_not_grandfathered_by_path_and_hash(repo):
    digest = public.sha256(repo, "wiki/assets/abra.svg")
    safefs.write_text(repo, "wiki/source.md", f"---\ncontent_sha256: {digest}\n---\n# Source\n")
    with pytest.raises(public.PublicError, match="source photo"):
        public.build(repo, public.render_rights(repo))


@pytest.mark.parametrize("link", ["[Web](https://example.test)", "[Web][site]\n\n[site]: https://example.test", '<a href="https://example.test">Web</a>'])
def test_mixed_web_footnote_warns_without_blocking(link):
    text = "Állítás.[^a]\n\n[^a]: A 3. dián ez áll.\n    " + link + "\n"
    findings = footnotes.scan("wiki/a.md", text)
    assert len(findings) == 1 and findings[0]["severity"] == "warning"
    assert footnotes.scan("wiki/a.md", text, text) == []
    assert footnotes.scan("wiki/a.md", text, text, full=True) == findings
    assert footnotes.scan("wiki/a.md", text.replace("A 3. dián ez áll.", "")) == []


def test_separate_private_footnote_and_code_do_not_warn():
    text = "[^a]: A 3. dián ez áll.\n\n[^b]: [Web](https://example.test)\n"
    assert footnotes.scan("wiki/a.md", text) == []
    assert footnotes.scan("wiki/a.md", "```md\n[^x]: A füzetben https://example.test\n```\n") == []


def test_footnote_reference_url_change_is_rechecked():
    before = "[^a]: 3. dia. [Web][ref]\n\n[ref]: relative.md\n"
    after = before.replace("relative.md", "https://example.test")
    assert len(footnotes.scan("wiki/a.md", after, before)) == 1
    assert footnotes.scan("wiki/a.md", "<!--\n" + after + "\n-->\n") == []
