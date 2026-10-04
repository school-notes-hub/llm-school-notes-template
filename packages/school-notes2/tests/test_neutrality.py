"""The shared template serves any learner (owner, 2026-10-04): no learner's name, page or
material, no fixed reader age and no learner branching in the shared files and the tool.

One pass, deterministic output: a failure lists every finding in path, line, token order;
nothing is fixed here. The learner-derived tokens come from the local learner checkouts
(`SN_LEARNER_REPOS`, or the sibling `school-notes-*-active` directories); without any
checkout that part is skipped. The other checks always run.
"""

import json
import os
import re
import unicodedata
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[3]
PACKAGE = TEMPLATE / "packages/school-notes2"
PROMPTS = PACKAGE / "src/school_notes2/llm/prompts"
ALLOW = Path(__file__).with_name("neutrality-allow.txt")
PRINCIPLE_START = "A cél a termék lehető legjobbra fejlesztése: segítsen egy 14–17 éves gyereknek tanulni"
# History and v1 review notes are not rewritten (G-21); tests use names only as keys (G-18).
EXCLUDED = ("CHANGELOG.md", "packages/school-notes/review/")
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


def tokens(repos: list[Path]) -> dict[str, str]:
    """token -> origin: each learner's name (from the directory name) and the stems of the
    topic pages (`wiki/<subject>/<stem>.md`; no index, summary or dated lesson log)."""
    found = {}
    for repo in repos:
        name = re.fullmatch(r"school-notes-([a-z0-9-]+?)-active", repo.name)
        if name:
            found[name.group(1)] = f"{repo.name}: learner name"
        for page in sorted(repo.glob("wiki/*/*.md")):
            stem = page.stem
            if stem == "index" or stem.startswith("osszefoglalo-") or re.match(r"\d{4}-\d{2}-\d{2}-", stem):
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
    stale = sorted(f"{p} {t}" for p, t in exceptions - used if t in found)
    assert stale == [], "allow-list entries that no longer match:\n" + "\n".join(stale)


def test_no_learner_branching_in_code_or_tests():
    branch = re.compile(r"\b(?:learner|student|ctx\.name|learner_name|student_name)\s*[!=]=\s*[\"']")
    hits = []
    for root in (PACKAGE / "src", PACKAGE / "tests"):
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            hits += [f"{path.relative_to(TEMPLATE)}:{_line(text, m.start())}"
                     for m in branch.finditer(text)]
    assert hits == []


def test_no_fixed_reader_age_in_prompts_and_rules():
    """The yardstick is the learner's grade (prompts) or PROFILE *Audience* (rules); only the
    owner's verbatim principle keeps its age range."""
    age = re.compile(r"\b1\d(?:\s*[–-]\s*1\d)?[\s-]*(?:éves|years?[\s-]old)", re.I)
    hits = []
    texts = [(p.relative_to(TEMPLATE).as_posix(), p.read_text(encoding="utf-8"))
             for p in sorted(PROMPTS.glob("*.txt"))]
    texts += [(rel, _text(rel)) for rel in scope()
              if rel.endswith(".md") and (rel.startswith(("instructions/", ".agents/"))
                                          or rel in ("AGENTS.md", "PROFILE.md"))]
    for rel, text in texts:
        if text is None:
            continue
        lines = text.splitlines()
        if rel.startswith("packages/") and lines and lines[0].startswith(PRINCIPLE_START):
            lines = lines[1:]
            text = "\n".join([""] + lines)          # keep line numbers
        hits += [f"{rel}:{_line(text, m.start())}: {m.group(0)}" for m in age.finditer(text)]
    assert hits == []


def test_template_profile_has_no_concrete_date():
    text = (TEMPLATE / "PROFILE.md").read_text(encoding="utf-8")
    assert [m.group(0) for m in re.finditer(r"\b20\d\d-\d\d-\d\d\b", text)] == []


def test_shared_card_file_is_part_of_the_shared_set():
    files = json.loads((TEMPLATE / "shared-files.json").read_text())["files"]
    assert "subject-cards.json" in files and "examples/subject-card.json" not in files
