import json

import pytest

from school_notes2.wiki import generate, public


def test_build_lists_every_page_in_b7_order(repo):
    generate.write_indexes(repo)
    value = public.build(repo, public.render_rights(repo))
    assert [p["path"] for p in value["pages"]] == [
        "wiki/index.md", "wiki/proba/index.md", "wiki/proba/osszefoglalo-alapok.md",
        "wiki/proba/elso.md", "wiki/proba/masodik.md", "wiki/proba/2026-09-10-elso-jegyzet.md",
        "wiki/proba/2026-09-20-dolgozat.md", "wiki/a-projektrol.md"]
    assert value["pages"][0]["navigationLabel"] == "🏠 Kezdőlap"
    assert value["pages"][1]["navigationLabel"] == "🧪 Próba"
    assert value["pages"][-1]["navigation"] == "info"
    assert value["citationOnlyLinks"] == ["sources/proba/csomag/01.jpg"]
    assert "publicationApproved" not in value and "omitSections" not in json.dumps(value)


def test_collections_group_under_the_summary(repo):
    cols = public.build(repo, public.render_rights(repo))["collections"]
    assert [c["id"] for c in cols] == ["proba-osszefoglalo-alapok", "proba-elso", "proba-masodik", "proba"]
    assert "group" not in cols[0] and cols[1]["group"] == "proba-osszefoglalo-alapok"
    assert "group" not in cols[2]
    assert cols[3] == {"id": "proba", "title": "Próba — tanulási jegyzet",
                       "pages": ["wiki/proba/osszefoglalo-alapok.md", "wiki/proba/elso.md",
                                 "wiki/proba/masodik.md"]}


def test_assets_keep_rights_and_classify_new_ones(repo):
    value = public.build(repo, public.render_rights(repo))
    assert value["assets"] == [{"path": "wiki/assets/abra.svg", "sha256": value["assets"][0]["sha256"],
                                "rights": "authored"}]
    (repo / "wiki/proba/masodik.md").write_text(
        "---\ntype: topic\ntitle: Második\ndescription: x\nchapter: halado\norder: 10\n---\n"
        "![új](../assets/uj/kep.png)\n", encoding="utf-8")
    (repo / "wiki/assets/uj").mkdir()
    (repo / "wiki/assets/uj/kep.png").write_bytes(b"png")
    with pytest.raises(public.PublicError) as err:
        public.build(repo, public.render_rights(repo))
    assert err.value.paths == ["wiki/assets/uj/kep.png"]
    (repo / "wiki/assets/uj/render.json").write_text(json.dumps({"outputs": {"kep.png": {"sha256": public.sha256(repo, "wiki/assets/uj/kep.png")}}}))
    entry = [a for a in public.build(repo, public.render_rights(repo))["assets"]
             if a["path"].endswith("kep.png")][0]
    assert entry["rights"] == "authored" and entry["rightsEvidence"] == "wiki/assets/uj/render.json"


def test_write_is_byte_stable(repo):
    assert public.write(repo, public.render_rights(repo)) is True
    assert public.write(repo, public.render_rights(repo)) is False


def test_build_keeps_the_source_note_after_the_fixed_fields(repo):
    existing = public.read_existing(repo)
    existing["sourceNote"] = "A jegyzet Minta füzetbe írt jegyzetei alapján készült."
    value = public.build(repo, public.render_rights(repo), existing)
    assert value["sourceNote"] == existing["sourceNote"]
    keys = list(value)
    assert keys.index("sourceNote") < keys.index("pages")
