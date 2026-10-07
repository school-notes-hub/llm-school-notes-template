"""sn 0.3.3 (fix round of 0.3.2, decision F1): the web footnote's structure is strict; in the
title only a number with a locator and a private-context word are machine errors, read on the
rendered text. Each test fails on 9b85754."""

import pytest

from school_notes2.wiki import check, web_footnote

D = " (ellenőrizve: 2026-10-07)."


def found(line):
    return check.check_web_footnotes("wiki/x/a.md", f"# A\n\nSzöveg.[^a]\n\n{line}\n")


@pytest.mark.parametrize("title", [
    "IV. Béla magyar király", "II. Rákóczi Ferenc", "U.S. Geological Survey", "Szakasz (geometria)",
    "Periódusos táblázat", "Conic section", "XIV. Lajos francia király", "2012. évi I. törvény a munka törvénykönyvéről",
    "Vidya Dehejia: Buddhism and Buddhist Art. The Metropolitan Museum of Art, 2007", "Mohácsi csata (1526)",
    "Az 1. világháború", "Kr. e. 3. évezred", "St. Vrain Valley Schools: Student Safety Rules", "Napóra",
    "Munkafüzet-kiadók", "Kórház", "SI Brochure, 9. kiadás", "Fotoszintézis (C4)", "Engineering Statics, Sign Conventions"])
def test_a_plain_title_passes_in_both_forms(title):
    assert found(f"[^a]: {title}. https://hu.wikipedia.org/wiki/X{D}") == [], title
    assert found(f"[^a]: [{title}](https://hu.wikipedia.org/wiki/X){D}") == [], title


def test_a_publisher_or_author_prefix_before_the_link_is_allowed():
    assert found(f"[^a]: Magyar Wikipédia: [Kandela](https://hu.wikipedia.org/wiki/Kandela){D}") == []
    assert found(f"[^a]: A. H. Maslow: [A Theory of Human Motivation (1943)](https://x.org/m.htm){D}") == []


def test_balanced_parentheses_in_a_url_parse_like_the_renderer():
    assert found(f"[^a]: [Kandela](https://example.org/wiki/Kandela_(mértékegység)){D}") == []
    assert found(f"[^a]: Szakasz (geometria). https://hu.wikipedia.org/wiki/Szakasz_(geometria){D}") == []


@pytest.mark.parametrize("title, what", [
    ("Kandela – a tanári diasor 15. diáján", "private context"), ("Kandela, a füzet 3. lapján", "number"),
    ("Kandela (a 4. feladat ábráján)", "number"), ("Kandela (tankönyv 15. old)", "number"),
    ("Kandela, tk. 15", "private context"), ("Kandela, 15. kép", "number"), ("Kandela, 15. ábra", "number"),
    ("Kandela, ahogy Kovács tanárnő mondta az órán", "private context"), ("Tűzvédelem, 9. §", "number"),
    ("9/2023. ÉKM rendelet 1. mellékletében", "number"), ("2026/331/EU, 1. táblázat", "number"),
    ("Kandela (6)", "number"), ("Kandela, VII. fejezet", "number"), ("Kandela, 3. szakasz", "number"),
    ("Kandela, 2. bekezdés", "number"), ("Kandela, 15-16. oldal", "number"), ("Kandela, p0015", "number"),
    ("A füzetem képe", "private context"), ("Óra után", "private context"), ("Jegyzetek a leckéhez", "private context")])
def test_a_locator_or_a_private_word_in_the_title_is_an_error(title, what):
    for line in (f"[^b]: {title}. https://example.org/a{D}", f"[^b]: [{title}](https://example.org/a){D}"):
        [item] = check.check_web_footnotes("wiki/x/a.md", f"# A\n\n{line}\n")
        assert what in item["message"] and item["line"] == 3 and "expected exactly" in item["message"], line


def test_the_title_is_checked_as_rendered():
    """A1: emphasis or markup may not hide a locator or a private word."""
    for title in ("Cikk. **A tanárom beteg**", "Cikk: 15. **oldal**", "Cikk, 15. <b>oldal</b>", "Cikk, 15. ol\\dal",
                  "Cikk, _füzet_"):
        assert found(f"[^a]: [{title}](https://example.org/a){D}"), title
    assert web_footnote.rendered("**A** _tanárom_ `x` &amp; <i>y</i>") == "A tanárom x & y"


@pytest.mark.parametrize("line, what", [
    ("[^b]: Cikk. https://example.org/a (ellenőrizve: 2026-09-30). PDF 15. oldal.", "text after the retrieval date"),
    ("[^b]: [Mt.](https://net.jogtar.hu/x), 21. § (4) (ellenőrizve: 2026-10-06).", "text between the link and the date"),
    ("[^b]: Cikk. https://example.org/a, letöltve 2026-10-06.", "not exactly ' (ellenőrizve"),
    ("[^b]: Cikk. https://example.org/a (korábbi ellenőrzés: 2026-09-30).", "not exactly ' (ellenőrizve"),
    ("[^b]: Cikk, https://example.org/a (ellenőrizve: 2026-09-30).", "the title does not end with '. '"),
    ("[^b]: Cikk. <https://example.org/a> (ellenőrizve: 2026-09-30).", "the URL in angle brackets"),
    ("[^b]: Cikk. http://example.org/a (ellenőrizve: 2026-09-30).", "not an https URL"),
    ("[^b]: Cikk. https://example.org/a (ellenőrizve: 2026-02-30).", "is not a real date"),
    ("[^b]: [Cikk](https://example.org/a \"cím\") (ellenőrizve: 2026-09-30).", "a link title"),
    ("[^b]: [NHS: Burns](https://www.nhs.uk/b/). Ellenőrizve: 2026-09-29.", "not exactly ' (ellenőrizve")])
def test_the_structure_stays_strict(line, what):
    [item] = check.check_web_footnotes("wiki/x/a.md", f"# A\n\n{line}\n")
    assert what in item["message"] and item["message"].startswith("[^b]: "), item["message"]


def test_a_continuation_paragraph_is_extra():
    text = f"# A\n\n[^b]: Cikk. https://example.org/a{D}\n\n    Lásd a harmadik részt.\n"
    assert "a continuation paragraph" in check.check_web_footnotes("wiki/x/a.md", text)[0]["message"]
