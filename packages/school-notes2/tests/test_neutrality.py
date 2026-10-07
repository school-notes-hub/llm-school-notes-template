"""The shared template serves any learner (owner, 2026-10-04): no learner's name, page or
material, no fixed reader age and no learner branching in the shared files and the tool.

One pass, deterministic output: a failure lists every finding in path, line, token order;
nothing is fixed here. The learner-derived tokens come from the local learner checkouts
(`SN_LEARNER_REPOS`, or the sibling `school-notes-*-active` directories); without any
checkout that part is skipped. The other checks (fixed learner count, branching, reader
age) always run.
"""

import ast
import json
import os
import re
import unicodedata
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[3]
PACKAGE = TEMPLATE / "packages/school-notes2"
ALLOW = Path(__file__).with_name("neutrality-allow.txt")
# History is not rewritten (G-21); tests use names only as keys (G-18).
EXCLUDED = ("CHANGELOG.md",)
SKIPPED_PARTS = ("tests", "__pycache__", "node_modules")


def _norm(text: str) -> str:
    """Lowercase without accents: `Szűkösség` and `szukosseg` match."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def scope() -> list[str]:
    """Shared files, the packages' sources and READMEs, and the shared card file."""
    files = set(json.loads((TEMPLATE / "shared-files.json").read_text())["files"])
    for pattern in ("packages/*/src/**/*", "packages/*/README.md"):
        files |= {p.relative_to(TEMPLATE).as_posix() for p in TEMPLATE.glob(pattern) if p.is_file()}
    files.add("subject-cards.json")
    return sorted(f for f in files
                  if not f.startswith(EXCLUDED) and f not in EXCLUDED
                  and not set(f.split("/")) & set(SKIPPED_PARTS) and ".egg-info/" not in f)


def _text(rel: str) -> str | None:
    try:
        return (TEMPLATE / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return None                      # binary previews; a listed missing file is not ours


def learner_repos() -> list[Path]:
    configured = os.environ.get("SN_LEARNER_REPOS")
    if configured:
        return sorted(Path(p) for p in configured.split(os.pathsep) if p)
    return sorted(p for p in TEMPLATE.parent.glob("school-notes-*-active") if p.is_dir())


def learner_names(repos: list[Path]) -> list[str]:
    """From the directory names; `barna` is also a colour: a colour use is a reviewed
    file-token exception, the name itself stays forbidden."""
    return sorted(m.group(1) for repo in repos
                  if (m := re.fullmatch(r"school-notes-([a-z0-9-]+?)-active", repo.name)))


def tokens(repos: list[Path]) -> dict[str, str]:
    """token -> origin: each learner's name and the multi-word stems of the topic pages
    (`wiki/<subject>/<stem>.md`; no index, summary or dated lesson log). A one-word stem
    (`kommunikacio`, `novella`) is a subject-level term, free for shared text (G-22)."""
    found = {name: f"school-notes-{name}-active: learner name" for name in learner_names(repos)}
    for repo in repos:
        for page in sorted(repo.glob("wiki/*/*.md")):
            stem = page.stem
            if (stem == "index" or stem.startswith("osszefoglalo-") or "-" not in stem
                    or re.match(r"\d{4}-\d{2}-\d{2}-", stem)):
                continue
            found.setdefault(stem, f"{repo.name}: wiki/{page.parent.name}/{page.name}")
    return found


def allowed() -> set[tuple[str, str]]:
    pairs = set()
    for line in ALLOW.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            path, token = line.split()
            pairs.add((path, token))
    return pairs


def _pattern(token: str) -> re.Pattern:
    words = r"[-_\s]+".join(re.escape(w) for w in token.split("-"))
    return re.compile(rf"(?<![a-z0-9]){words}(?![a-z0-9])")


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def test_no_learner_name_or_page_in_the_shared_template():
    repos = learner_repos()
    if not repos:
        pytest.skip("no local learner checkout: learner-derived tokens are unavailable")
    found, exceptions, used = tokens(repos), allowed(), set()
    hits = []
    for rel in scope():
        text = _text(rel)
        if text is None:
            continue
        plain = _norm(text)
        for token in sorted(found):
            for match in _pattern(token).finditer(plain):
                if (rel, token) in exceptions:
                    used.add((rel, token))
                    continue
                hits.append(f"{rel}:{_line(plain, match.start())}: {token} ({found[token]})")
    assert hits == [], "learner-specific text in the shared template:\n" + "\n".join(hits)
    # Stale only when the token is still forbidden here and no longer occurs; a one-word subject
    # exception that became unnecessary is left to code review (one checkout must not turn this red).
    stale = sorted(f"{p} {t}" for p, t in exceptions - used if t in found)
    assert stale == [], "allow-list entries that no longer match:\n" + "\n".join(stale)


# Shared text serves any number of learners (G-23): "all/every configured learner(s)".
FIXED_COUNT = re.compile(r"(?<![a-z0-9])(?:(?:both|two)[-\s]+learners?|(?:mindket|ket)\s+tanulo)")


def fixed_count_hits(rel: str, text: str) -> list[tuple[str, str]]:
    """(location, allow-list key) of each fixed learner count; the key joins the words
    with `-` (`ket-tanulo`)."""
    plain = _norm(text)
    return [(f"{rel}:{_line(plain, m.start())}: {m.group(0)}", "-".join(m.group(0).split()))
            for m in FIXED_COUNT.finditer(plain)]


def test_fixed_count_pattern():
    text = "Both learners.\nCheck two  learner repos; mindkét tanuló; a két tanulói repó; all learners"
    assert [key for _, key in fixed_count_hits("x", text)] == [
        "both-learners", "two-learner", "mindket-tanulo", "ket-tanulo"]
    assert fixed_count_hits("x", "every configured learner; két tanár; network learners") == []


def test_no_fixed_learner_count_in_the_shared_files_and_the_tool():
    exceptions, used, hits = allowed(), set(), []
    for rel in scope():
        text = _text(rel)
        for where, key in fixed_count_hits(rel, text) if text is not None else []:
            if (rel, key) in exceptions:
                used.add((rel, key))
            else:
                hits.append(where)
    assert hits == [], "fixed learner count in shared text:\n" + "\n".join(hits)
    stale = sorted(f"{p} {t}" for p, t in exceptions - used if FIXED_COUNT.fullmatch(t.replace("-", " ")))
    assert stale == [], "allow-list entries that no longer match:\n" + "\n".join(stale)


LEARNER_NAMES = {"learner", "student", "learner_name", "student_name"}


def _is_learner(node: ast.AST) -> bool:
    """`learner`, `ctx.student`, `task.data["student"]`, `ctx.student.name`, `ctx.name` …"""
    if isinstance(node, ast.Name):
        return node.id in LEARNER_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in LEARNER_NAMES or node.attr == "name" and (
            _is_learner(node.value) or isinstance(node.value, ast.Name) and node.value.id == "ctx")
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value in LEARNER_NAMES
    return False


def _is_name_literal(node: ast.AST) -> bool:
    """A non-empty text, or a literal collection holding one; the empty value is a neutral
    check (`learner == ""`)."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value.strip() != ""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_name_literal(e) for e in node.elts)
    return False


def learner_branches(source: str, *, asserts_allowed: bool = False) -> list[int]:
    """Lines comparing a learner against a literal name, in either operand order, or a
    `match` on the learner with a literal-name case. A test's `assert` may use a name as a
    key (G-18): with `asserts_allowed` comparisons inside an assert statement pass."""
    tree = ast.parse(source)
    allowed = {id(n) for a in ast.walk(tree) if asserts_allowed and isinstance(a, ast.Assert)
               for n in ast.walk(a)}
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and id(node) not in allowed:
            operands = [node.left, *node.comparators]
            if any(_is_learner(x) and _is_name_literal(y) or _is_learner(y) and _is_name_literal(x)
                   for x, y in zip(operands, operands[1:])):
                lines.add(node.lineno)
        elif isinstance(node, ast.Match) and _is_learner(node.subject):
            lines |= {c.pattern.lineno for c in node.cases for p in ast.walk(c.pattern)
                      if isinstance(p, ast.MatchValue) and _is_name_literal(p.value)}
    return sorted(lines)


@pytest.mark.parametrize("source, found", [
    ('if learner == "":\n    pass\n', []),
    ('if ctx.student.name == "benedek":\n    pass\n', [1]),
    ('if "benedek" == learner:\n    pass\n', [1]),
    ('x = 1 if task.data["student"] != "barna" else 2\n', [1]),
    ('if learner in ("proba", "egy"):\n    pass\n', [1]),
    ('match learner:\n    case "benedek":\n        pass\n    case _:\n        pass\n', [2]),
    ('if learner == other and student is not None:\n    pass\n', []),
])
def test_branching_guard_cases(source, found):
    assert learner_branches(source) == found


def test_a_test_assertion_may_use_a_name_as_a_key():
    source = 'assert job["learner"] == "benedek"\nif job["learner"] == "benedek":\n    pass\n'
    assert learner_branches(source, asserts_allowed=True) == [2]
    assert learner_branches(source) == [1, 2]


def test_no_learner_branching_in_code_or_tests():
    hits = []
    for root in (PACKAGE / "src", PACKAGE / "tests"):
        for path in sorted(root.rglob("*.py")):
            lines = learner_branches(path.read_text(encoding="utf-8"),
                                     asserts_allowed=root.name == "tests")
            hits += [f"{path.relative_to(TEMPLATE)}:{line}" for line in lines]
    assert hits == []


def test_no_fixed_reader_age_in_the_rules():
    """The yardstick is PROFILE *Audience*, never a fixed age."""
    age = re.compile(r"\b1\d(?:\s*[–-]\s*1\d)?[\s-]*(?:éves|years?[\s-]old)", re.I)
    hits = []
    texts = [(rel, _text(rel)) for rel in scope()
              if rel.endswith(".md") and (rel.startswith(("instructions/", ".agents/"))
                                          or rel in ("AGENTS.md", "PROFILE.md"))]
    for rel, text in texts:
        if text is None:
            continue
        hits += [f"{rel}:{_line(text, m.start())}: {m.group(0)}" for m in age.finditer(text)]
    assert hits == []


def test_template_profile_has_no_concrete_date():
    text = (TEMPLATE / "PROFILE.md").read_text(encoding="utf-8")
    assert [m.group(0) for m in re.finditer(r"\b20\d\d-\d\d-\d\d\b", text)] == []


def test_shared_card_file_is_part_of_the_shared_set():
    files = json.loads((TEMPLATE / "shared-files.json").read_text())["files"]
    assert "subject-cards.json" in files and "examples/subject-card.json" not in files
