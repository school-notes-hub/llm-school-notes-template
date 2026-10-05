"""T2: the path guard."""

import hashlib
import os

from school_notes2.wiki import generate, guard, markers
from school_notes2.wiki.guard import Change, GuardInput


def base_reader(snapshot):
    return lambda path: snapshot.get(path)


def snapshot(repo):
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in repo.rglob("*") if p.is_file()}


def run(repo, base, changes, **kw):
    return guard.run(GuardInput(repo, [Change(*c) for c in changes], base_reader(base), **kw))


def test_allowed_wiki_edit_and_log(repo):
    base = snapshot(repo)
    (repo / "wiki/proba/elso.md").write_text((repo / "wiki/proba/elso.md").read_text() + "\nÚj.\n")
    (repo / "wiki/log.md").write_text("# Napló\n\n## 2026-10-03\n")
    assert run(repo, base, [("wiki/proba/elso.md", "modified"), ("wiki/log.md", "modified")]) == []


def test_forbidden_paths_and_references_only_interactive(repo):
    base = snapshot(repo)
    for rel in ("docs/x.md", "tools/x.py", "sources/proba/csomag/02.jpg", "references/proba/k.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x")
    changes = [(r, "added") for r in ("docs/x.md", "tools/x.py", "sources/proba/csomag/02.jpg",
                                      "references/proba/k.md")]
    assert {v.path for v in run(repo, base, changes)} == {c[0] for c in changes}
    found = run(repo, base, changes, interactive=True)
    assert "references/proba/k.md" not in {v.path for v in found}
    assert all(not v.owner for v in found)


def test_machine_field_and_generated_block_edits(repo):
    base = snapshot(repo)
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    (repo / rel).write_text((repo / rel).read_text().replace("type: lesson-notes", "type: lesson-notes\ngrade: 10"))
    idx = "wiki/proba/index.md"
    (repo / idx).write_text(markers.replace((repo / idx).read_text(), "notes", "kézzel\n"))
    found = run(repo, base, [(rel, "modified"), (idx, "modified")])
    assert {v.path for v in found} == {rel, idx}


def test_tool_writes_are_accepted_on_rerun(repo):
    base = snapshot(repo)
    generate.write_indexes(repo)
    idx = "wiki/proba/index.md"
    text = (repo / idx).read_text()
    parts = {idx: guard.parts_hash(text)}
    assert run(repo, base, [(idx, "modified")], tool_parts=parts) == []
    (repo / idx).write_text(text + "\nkézi sor\n")      # the writer edits the hand-written part
    assert run(repo, base, [(idx, "modified")], tool_parts=parts) == []


def test_tool_file_tampering_needs_owner(repo):
    base = snapshot(repo)
    rel = "sources/proba/uj/01.jpg"
    (repo / rel).parent.mkdir(parents=True)
    (repo / rel).write_bytes(b"jpeg")
    files = {rel: hashlib.sha256(b"jpeg").hexdigest()}
    assert run(repo, base, [(rel, "added")], tool_files=files) == []
    (repo / rel).write_bytes(b"other")
    [v] = run(repo, base, [(rel, "added")], tool_files=files)
    assert v.owner


def test_delete_and_symlink_and_git_file(repo):
    base = snapshot(repo)
    (repo / "wiki/proba/masodik.md").unlink()
    os.symlink("/etc/passwd", repo / "wiki/proba/evil.md")
    (repo / ".git").write_text("gitdir: /elsewhere\n")
    found = run(repo, base, [("wiki/proba/masodik.md", "deleted"), ("wiki/proba/evil.md", "added")],
                git_file=b"gitdir: /srv/x\n")
    by_path = {v.path: v for v in found}
    assert "wiki/proba/masodik.md" not in by_path  # #13: deleting a page is the writer's choice
    assert by_path["wiki/proba/evil.md"].owner and by_path[".git"].owner


def test_conflict_files_may_be_edited(repo):
    base = snapshot(repo)
    (repo / "tools/subjects.json").write_text("{}")
    changes = [("tools/subjects.json", "modified")]
    assert run(repo, base, changes)
    assert run(repo, base, changes, conflict_files=frozenset({"tools/subjects.json"})) == []


def test_cards_are_never_edited_in_a_learner_repo(repo):
    """The shared card file and the learner's subject settings stay closed, interactive too:
    cards live only in the template (plan 4.3)."""
    import json
    from tests.sources.test_cards import CARD
    (repo / "subject-cards.json").write_text('{"cards": {}}\n')
    base = snapshot(repo)
    (repo / "subject-cards.json").write_text(json.dumps({"cards": {"proba": CARD}}))
    rel = "tools/subjects.json"
    data = json.loads((repo / rel).read_text())
    data["subjects"]["proba"]["card"] = CARD
    data["subjects"]["uj"] = {"name": "Új tárgy", "card": CARD}
    (repo / rel).write_text(json.dumps(data))
    changes = [("subject-cards.json", "modified"), (rel, "modified")]
    for interactive in (False, True):
        assert {v.path for v in run(repo, base, changes, interactive=interactive)} == \
            {"subject-cards.json", rel}
