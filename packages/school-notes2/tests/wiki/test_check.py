import json

from school_notes2.wiki import check, generate


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


def test_missing_cited_source_is_only_a_warning(repo):
    from school_notes2.wiki import check
    (repo / "wiki/proba/regi.md").write_text(
        "---\ntype: topic\ntitle: Régi\ndescription: R.\nchapter: alapok\norder: 30\n---\n\n"
        "Forrás: [fotó](../../sources/2026-09-01-archiv/01.jpg)\n", encoding="utf-8")
    items = check.check_files(repo, ["wiki/proba/regi.md"])
    cited = [i for i in items if "not in this repository" in i["message"]]
    assert cited and cited[0]["severity"] == "warning"
    assert not [i for i in check.errors(items) if "sources" in i["message"]]


def test_a_web_footnote_is_title_one_url_and_a_retrieval_date():
    """Plan 5: the public view keeps a footnote with a web URL whole, so its form is fixed."""
    good = ["[^a]: Hidrogén - PubChem. https://pubchem.ncbi.nlm.nih.gov/element/1 (ellenőrizve: 2026-09-30).",
            "[^b]: [NHS: Burns and scalds](https://www.nhs.uk/conditions/burns-and-scalds/) (ellenőrizve: 2026-09-29).",
            "[^c]: Füzet, 3. oldal: a tanár magyarázata."]                       # no URL: not judged here
    bad = {"[^d]: [Web](https://example.org/x), 2026-09-30; [háttér](../../references/t/b/index.md).": "more than one link",
           "[^e]: Cikk. https://example.org/a https://example.org/b (2026-09-30).": "more than one link",
           "[^f]: Cikk. https://example.org/a, lásd p0002 (2026-09-30).": "page or photo id",
           "[^g]: Cikk és 01.jpg. https://example.org/a (2026-09-30).": "a file name",
           "[^h]: Cikk. https://example.org/a": "no retrieval date",
           "[^i]: https://example.org/a (2026-09-30).": "no title",
           "[^j]: Cikk, sources/fizika/x. https://example.org/a (2026-09-30).": "sources/ or references/ path"}
    for line in good:
        assert check.check_web_footnotes("wiki/x/a.md", f"# A\n\nSzöveg.[^a]\n\n{line}\n") == []
    for line, problem in bad.items():
        [found] = check.check_web_footnotes("wiki/x/a.md", f"# A\n\n{line}\n")
        assert problem in found["message"] and found["severity"] == "error" and found["line"] == 3, line


def test_a_web_footnote_has_nothing_but_title_url_and_date():
    """0.3.2: the rule's form exactly – free text after the title has carried private details
    ("PDF 15. oldal") onto the public site. Each extra is named, with the expected form."""
    good = ["[^a]: Hidrogén - PubChem. https://pubchem.ncbi.nlm.nih.gov/element/1 (ellenőrizve: 2026-09-30).",
            "[^a]: [NHS: Burns and scalds](https://www.nhs.uk/conditions/burns-and-scalds/) (ellenőrizve: 2026-09-29).",
            "[^a]: [Code of Hammurabi (L. W. King fordítása)](https://avalon.law.yale.edu/x) (ellenőrizve: 2026-10-07).",
            "[^a]: [St. Vrain Valley Schools: Student Safety Rules](https://www.svvsd.org/x/) (ellenőrizve: 2026-09-29).",
            "[^a]: 2012. évi I. törvény a munka törvénykönyvéről. https://net.jogtar.hu/x (ellenőrizve: 2026-10-06).",
            "[^a]: [A Theory of Human Motivation (1943)](https://psychclassics.yorku.ca/x.htm) (ellenőrizve: 2026-10-07).",
            "[^a]: [Rendőrség: Mi a 112-es segélyhívószám?](https://www.police.hu/hu/112) (ellenőrizve: 2026-09-29)."]
    bad = {"[^b]: [NHS: Burns](https://www.nhs.uk/b/). Ellenőrizve: 2026-09-29.": "after the link not exactly",
           "[^b]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30). PDF 15. oldal.": "text after the retrieval date: 'PDF 15. oldal.'",
           "[^b]: NAV: [Diákmunka](https://nav.gov.hu/x) (ellenőrizve: 2026-09-30).": "text before the link: 'NAV:'",
           "[^b]: [Mt.](https://net.jogtar.hu/x), 21. § (4) (ellenőrizve: 2026-10-06).": "text between the link and the date: ', 21. § (4)'",
           "[^b]: Cikk, https://example.org/a (ellenőrizve: 2026-09-30).": "the title does not end with '. ' before the URL",
           "[^b]: Cikk. <https://example.org/a> (ellenőrizve: 2026-09-30).": "the URL in angle brackets",
           "[^b]: Cikk. https://example.org/a, letöltve 2026-10-06.": "after the URL not exactly",
           "[^b]: Cikk. https://example.org/a (lekérve: 2026-10-06).": "after the URL not exactly",
           "[^b]: Cikk. http://example.org/a (ellenőrizve: 2026-09-30).": "not an https URL",
           "[^b]: Cikk. https://example.org/a (ellenőrizve: 2026-02-30).": "is not a real date",
           "[^b]: Buddhist Art. The Metropolitan Museum. https://example.org/a (ellenőrizve: 2026-09-30).": "a second sentence in the title: 'The Metropolitan Museum'",
           "[^b]: Cikk; lásd a végét. https://example.org/a (ellenőrizve: 2026-09-30).": "a second sentence",
           "[^b]: OTSZ, 54/2014. BM rendelet, 9. §. https://njt.hu/x (ellenőrizve: 2026-09-30).": "a page or paragraph number",
           "[^b]: Tankönyv, 15. oldal. https://example.org/a (ellenőrizve: 2026-09-30).": "a page or paragraph number",
           "[^b]: Engineering Statics, 8.2. Sign Conventions. https://example.org/a (ellenőrizve: 2026-09-30).": "a section number",
           "[^b]: 2024/1681/EU, melléklet. https://eur-lex.europa.eu/x (ellenőrizve: 2026-09-30).": "a section name",
           "[^b]: [Cikk](https://example.org/a \"cím\") (ellenőrizve: 2026-09-30).": "a link with angle brackets or a link title"}
    for line in good:
        assert check.check_web_footnotes("wiki/x/a.md", f"# A\n\nSzöveg.[^a]\n\n{line}\n") == [], line
    for line, problem in bad.items():
        [found] = check.check_web_footnotes("wiki/x/a.md", f"# A\n\n{line}\n")
        assert problem in found["message"] and found["line"] == 3, (line, found["message"])
        assert found["message"].startswith("[^b]: ") and "expected exactly `[^id]: Title. https://" in found["message"]
    cont = "# A\n\n[^b]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30).\n\n    Lásd a 3. bekezdést.\n"
    assert "a continuation paragraph" in check.check_web_footnotes("wiki/x/a.md", cont)[0]["message"]


def test_the_done_report_names_page_line_and_what_is_extra(repo):
    from school_notes2.local import done
    (repo / "wiki/proba/elso.md").write_text((repo / "wiki/proba/elso.md").read_text() + "\nSzöveg.[^w]\n\n"
                                             "[^w]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30). PDF 15. oldal.\n")
    line = (repo / "wiki/proba/elso.md").read_text().split("\n").index(
        "[^w]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30). PDF 15. oldal.") + 1
    lines = []
    done.report(repo, lines.append)
    assert f"  wiki/proba/elso.md:{line} [^w]: text after the retrieval date: 'PDF 15. oldal.' – expected exactly" \
        in "\n".join(lines)


def test_the_done_check_counts_a_bad_web_footnote(repo):
    (repo / "wiki/proba/elso.md").write_text((repo / "wiki/proba/elso.md").read_text()
                                             + "\nSzöveg.[^w]\n\n[^w]: Cikk. https://example.org/a\n")
    assert any("[^w]" in i["message"] for i in check.errors(check.check_files(repo, ["wiki/proba/elso.md"], fix=False)))


def test_a_web_footnote_is_read_with_its_continuation_and_its_reference_links():
    """A1: the renderer keeps a footnote's indented continuation paragraphs and resolves
    reference-style links; the check reads the same structure."""
    cont = ("# A\n\nSzöveg.[^w]\n\n[^w]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30).\n\n"
            "    A füzet scan-42.jpg képe.\n")
    [found] = check.check_web_footnotes("wiki/x/a.md", cont)
    assert "a file name" in found["message"] and found["line"] == 5
    ref = ("# A\n\nSzöveg.[^w]\n\n[^w]: [Web][web] és scan-42.jpg (ellenőrizve: 2026-09-30).\n\n"
           "[web]: https://example.org/a\n")
    [found] = check.check_web_footnotes("wiki/x/a.md", ref)
    assert "a file name" in found["message"]
    two = "# A\n\n[^w]: [Web][web], [más](https://example.org/b) (2026-09-30).\n\n[web]: https://example.org/a\n"
    assert "more than one link" in check.check_web_footnotes("wiki/x/a.md", two)[0]["message"]


def test_private_names_in_the_public_view_are_errors_but_not_in_dropped_parts():
    """A2/O11: the output gate's visible-text patterns on the page's public view; a private
    footnote (no web link), an HTML comment, a link target and a web URL are not shown."""
    page = ("---\ntitle: A\n---\n# A\n\nLásd sources/fizika/x.jpg.\n")
    [found] = check.check_public_view("wiki/x/a.md", page)
    assert found["severity"] == "error" and found["line"] == 6 and "sources/" in found["message"]
    assert check.check_public_view("wiki/x/a.md", "# A\n\nA füzet p0002 oldala.\n")[0]["line"] == 3
    hidden = ("---\ntitle: A\nsource_file: fizika/p0001.jpg\n---\n# A\n\nSzöveg.[^f] [kép](../../sources/x/p0001.jpg)\n\n"
              "<!-- sources/x p0003 -->\n\n[^f]: Füzet, sources/x/p0001.jpg.\n\n"
              "Lásd https://example.org/sources/p0001 is.\n")
    assert check.check_public_view("wiki/x/a.md", hidden) == []
    assert check.check_public_view("wiki/log.md", "Lásd sources/x.\n") == []          # not published
