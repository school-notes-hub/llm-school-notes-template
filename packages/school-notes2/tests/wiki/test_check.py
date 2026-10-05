import json

from school_notes2.wiki import check, generate
from school_notes2.wiki.check_result import check_result


def messages(items):
    return [i["message"] for i in items if i["severity"] == "error"]


def test_clean_repo_passes(repo):
    generate.write_indexes(repo)
    pages = [p.relative_to(repo).as_posix() for p in (repo / "wiki").rglob("*.md")]
    assert messages(check.check_files(repo, pages)) == []


def test_link_rules(repo):
    rel = "wiki/proba/masodik.md"
    (repo / rel).write_text("---\ntype: topic\ntitle: M\ndescription: d\nchapter: halado\norder: 10\n---\n"
                            "[a](/etc/passwd) [b](../../../kint.md) ![c](../../sources/proba/csomag/01.jpg)\n"
                            "[d](../assets/) [e](nincs.md) [ok](https://example.com) `[f](g.md)`\n")
    found = messages(check.check_files(repo, [rel]))
    assert len(found) == 5
    assert any("absolute" in m for m in found) and any("leaves" in m for m in found)
    assert any("reference image" in m for m in found) and any("directory" in m for m in found)
    assert any("does not exist" in m for m in found)


def test_conflict_markers_secrets_and_formulas(repo):
    rel = "wiki/proba/masodik.md"
    text = (repo / rel).read_text()
    (repo / rel).write_text(text + "<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n"
                            "kulcs: sk-or-v1-0123456789abcdef0123\n$$ a\n")
    found = messages(check.check_files(repo, [rel]))
    assert sum("conflict" in m for m in found) == 2
    assert any("secret" in m for m in found) and any("$$" in m for m in found)


def test_chapter_order_and_lessons(repo):
    rel = "wiki/proba/masodik.md"
    (repo / rel).write_text("---\ntype: topic\ntitle: M\ndescription: d\nchapter: nincs\n---\n")
    note = "wiki/proba/2026-09-10-elso-jegyzet.md"
    (repo / note).write_text("---\ntype: lesson-notes\ntitle: J\ndescription: d\nlessons:\n"
                             "  - {date: '2026-9-3', title: X, topics: [nincs.md]}\n---\n")
    found = messages(check.check_files(repo, [rel, note]))
    assert any("not in the subject index" in m for m in found)
    assert any("`order`" in m for m in found)
    assert any("YYYY-MM-DD" in m for m in found) and any("topic page" in m for m in found)


def test_check_preserves_author_bytes_and_has_no_size_or_typography_warning(repo):
    """#5: the 40 KB and the Hungarian typography warnings are gone."""
    rel = "wiki/proba/masodik.md"
    text = (repo / rel).read_text().replace("\n", "\r\n").rstrip() + "\r\n" + "x" * 41000
    (repo / rel).write_bytes(text.encode())
    items = check.check_files(repo, [rel])
    data = (repo / rel).read_bytes()
    assert data == text.encode()
    assert not any("40 KB" in i["message"] or "typographic" in i["message"] for i in items)
    (repo / rel).write_text((repo / rel).read_text() + "\n„Idézet” – gondolatjel.\n")
    assert not any("typographic" in i["message"] for i in check.check_files(repo, [rel]))


def test_render_json_must_match(repo):
    (repo / "wiki/assets/fig").mkdir()
    (repo / "wiki/assets/fig/abra.py").write_text("print(1)")
    (repo / "wiki/assets/fig/out.svg").write_text("<svg/>")
    (repo / "wiki/assets/fig/render.json").write_text(json.dumps(
        {"source": "wiki/assets/fig/abra.py", "source_sha256": "0" * 64,
         "outputs": {"out.svg": {"sha256": "0" * 64}}}))
    found = messages(check.check_files(repo, []))
    assert len(found) == 2


FETCH = {"packages": [{"subject": "fizika", "new_subject": True}],
         "pages": [{"seq": 1, "duplicate_of": None}, {"seq": 2, "duplicate_of": "sources/x.jpg"},
                   {"seq": 3, "duplicate_of": None}]}


def test_result_checks(repo):
    (repo / "docs/review").mkdir(parents=True)
    (repo / "docs/review/2026-10-01-review.md").write_text("x")
    result = {"status": "done",
              "notes": [{"file": "wiki/proba/2026-09-10-elso-jegyzet.md", "pages": [1, 9]}],
              "new_subjects": [{"subject": "proba", "emoji": "x", "color": "#000000"}],
              "review_closure": [{"file": "docs/review/2026-10-01-review.md", "item_id": "R1", "status": "fixed"},
                                 {"file": "docs/review/nincs.md", "item_id": "R1", "status": "fixed"}],
              "checks": [{"page": "wiki/proba/elso.md", "image": 7, "locator": "x", "observed": "y",
                          "decision": "confirmed"},
                         {"page": "wiki/proba/elso.md", "image": "wiki/assets/abra.svg", "locator": "x",
                          "observed": "y", "decision": "confirmed"}]}
    found = messages(check_result(repo, result, FETCH, {("docs/review/2026-10-01-review.md", "R1")}))
    # An invalid closure is a warning (#17): the item stays open; it is not counted here.
    assert len(found) == 4
    assert any("[3]" in m for m in found) and any("[9]" in m for m in found)
    assert any("not new" in m for m in found)
    warnings = check_result(repo, result, FETCH, {("docs/review/2026-10-01-review.md", "R1")})
    assert any("nincs.md" in i["message"] and i["severity"] == "warning" for i in warnings)
    assert any("page number 7" in m for m in found)


def test_missing_cited_source_is_only_a_warning(repo):
    from school_notes2.wiki import check
    (repo / "wiki/proba/regi.md").write_text(
        "---\ntype: topic\ntitle: Régi\ndescription: R.\nchapter: alapok\norder: 30\n---\n\n"
        "Forrás: [fotó](../../sources/2026-09-01-archiv/01.jpg)\n", encoding="utf-8")
    items = check.check_files(repo, ["wiki/proba/regi.md"])
    cited = [i for i in items if "not in this repository" in i["message"]]
    assert cited and cited[0]["severity"] == "warning"
    assert not [i for i in check.errors(items) if "sources" in i["message"]]
