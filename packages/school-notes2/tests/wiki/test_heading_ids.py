"""Fix-49/1: a link target repeating a heading's id is found by the check, with the renderer's
own slug rule (study-site lib/markdown.mjs: github-slugger over hast-util-to-text)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from school_notes2.wiki import check, heading_ids

STUDY_SITE = Path(__file__).resolve().parents[3] / "study-site"


def ids(body, public=False):
    return [value for _, _, value in heading_ids.heading_ids("---\ntitle: T\n---\n" + body, public=public)]


@pytest.mark.parametrize("body, private, public", [
    # Expected values were produced by the renderer itself (renderMarkdown, both views).
    ("# T\n\n## A ![kép](x.png) B\n", ["t", "a--b"], None),
    ("# T\n\n## A  \t B\n", ["t", "a-b"], None),
    ("# T\n\n## 9. évfolyam: Gráfok\n", ["t", "9-évfolyam-gráfok"], ["t", "gráfok"]),
    ("# T\n\n## Gráfok[^1]\n\ntext[^2]\n\n[^1]: lásd\n[^2]: https://x.hu\n", ["t", "gráfok1"], ["t", "gráfok"]),
    ("# T\n\ntext[^2]\n\n## Gráfok[^1]\n\n[^1]: <https://x.hu>\n[^2]: nincs\n", ["t", "gráfok2"], ["t", "gráfok1"]),
    ("# T\n\n## A $a_{n}$ és `no_push` _dőlt_ __x__ a_b\n", ["t", "a-a_n-és-no_push-dőlt-x-a_b"], None),
    ("# T\n\n## Kép<br>sor &amp; &nbsp;x\n", ["t", "képsor--x"], None),
    ("# T\n\n## *A*  B\n", ["t", "a-b"], None),
    ("# T\n\n## <a id=\"q\"></a> Cím\n", ["t", "-cím"], None),
    ("# T\n\n## [Link  szöveg](a.md)   után ##\n", ["t", "link-szöveg-után"], None),
    ("# T\n\n## `kód  x`\n", ["t", "kód-x"], None),
    ("# T\n\n## A\\_b \\* c\n", ["t", "a_b--c"], None),
    ("# X\n\n## X\n", ["x", "x-1"], None),
    ("# T\n\n## Gráfok\n\n## Gráfok\n\n## Gráfok-1\n", ["t", "gráfok", "gráfok-1", "gráfok-1-1"], None),
    ("# T\n\n## 🙂 Emoji – nagykötőjel „idézet”\n", ["t", "-emoji--nagykötőjel-idézet"], None),
    ("# T\n\n```\n## nem címsor\n```\n<!--\n## ez sem\n-->\n    ## kód\n## 1. óra (2026-09-03) - Leszámlálási feladatok\n",
     ["t", "1-óra-2026-09-03---leszámlálási-feladatok"], None),
])
def test_heading_ids_match_the_renderer(body, private, public):
    assert ids(body) == private
    assert ids(body, public=True) == (public or private)


def test_jump_targets_are_the_ids_the_renderer_keeps():
    text = ('<a id="x"> </a>\n<a id="Y"></a>\n<a id="user-content-z"></a>\n<a name="q" id="w"></a>\n'
            '<a href="#x" id="v"></a> `<a id="kod"></a>` <a id=\'egy-1\'></a>\n')
    assert [value for _, value in heading_ids.jump_targets(text)] == ["user-content-z", "w", "egy-1"]


PAGE = """---
type: lesson-notes
title: Leszámlálás és gráfok
description: d
---

# Leszámlálás és gráfok

<a id="gráfok"></a>

## Gráfok

<a id="hazi"></a>
<a id="hazi"></a>

## Házi feladat

<a id="fa"></a>
"""


def test_check_reports_a_repeated_id_with_its_line():
    found = check.check_ids("wiki/m/a.md", PAGE)
    assert [(i["line"], i["severity"]) for i in found] == [(9, "error"), (14, "error")]
    assert '<a id="gráfok"></a> repeats the id of the heading \'Gráfok\' (line 11)' in found[0]["message"]
    assert "remove this anchor" in found[0]["message"]
    assert 'the link target <a id="hazi"> (line 13)' in found[1]["message"]
    assert check.check_ids("wiki/m/a.md", PAGE.replace('<a id="gráfok"></a>', '<a id="grafok-regi"></a>')
                           .replace('<a id="hazi"></a>\n<a id="hazi"></a>', '<a id="hazi"></a>')) == []


def test_mcp_and_finish_check_see_it(repo):
    rel = "wiki/proba/masodik.md"
    (repo / rel).write_text((repo / rel).read_text() + '\n<a id="második-cím"></a>\n\n## Második cím\n')
    found = [i for i in check.check_files(repo, [rel]) if "repeats the id" in i["message"]]
    assert len(found) == 1 and found[0]["severity"] == "error" and "kind" not in found[0]


@pytest.mark.skipif(shutil.which("node") is None or not (STUDY_SITE / "node_modules/github-slugger").is_dir(),
                    reason="the renderer's node_modules are not installed")
def test_removed_characters_equal_github_slugger():
    script = """
import { regex } from './node_modules/github-slugger/regex.js';
const ranges = [];
for (let cp = 0; cp <= 0x10FFFF; cp++) {
  if (cp >= 0xD800 && cp <= 0xDFFF) continue;
  if (String.fromCodePoint(cp).replace(regex, '') !== '') continue;
  const last = ranges[ranges.length - 1];
  if (last && last[1] === cp - 1) last[1] = cp; else ranges.push([cp, cp]);
}
console.log(JSON.stringify(ranges));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=STUDY_SITE,
                         capture_output=True, text=True, check=True, timeout=120).stdout
    assert [tuple(r) for r in json.loads(out)] == list(heading_ids.REMOVED)
    version = json.loads((STUDY_SITE / "node_modules/github-slugger/package.json").read_text())["version"]
    assert version == "2.0.0"
