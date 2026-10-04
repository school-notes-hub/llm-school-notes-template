import json

from school_notes2.wiki import check, frontmatter, machine, markers

SHA = "a" * 64
FETCH = {"pages": [
    {"seq": 1, "package": "Óra 1", "file": "1.jpg", "page": None,
     "path": "sources/proba/ora-1/1.jpg", "sha256": "1" * 64, "original_sha256": SHA, "duplicate_of": None},
    {"seq": 2, "package": "Óra 1", "file": "f.pdf", "page": 2,
     "path": "sources/proba/ora-1/p0002.jpg", "sha256": "2" * 64, "original_sha256": SHA, "duplicate_of": None},
]}


def test_lesson_values_from_pages():
    v = machine.lesson_values("wiki/proba/2026-10-01-x-jegyzet.md", [2, 1], FETCH, 9, "codex", "T")
    assert v["type"] == "lesson-notes" and v["grade"] == 9
    assert v["source_file"] == "proba/ora-1/"
    assert v["content_sha256"] == {"1.jpg": "1" * 64, "p0002.jpg": "2" * 64}
    assert v["original_sha256"]["p0002.jpg"] == SHA + "#p2"
    assert v["sources"] == [{"id": "ora-1", "resource": "../../sources/proba/ora-1/1.jpg", "title": "Óra 1"}]
    assert v["drive_folder"] == "Óra 1" and v["generated"] == {"by": "codex", "at": "T"}


def test_write_lesson_notes_keeps_llm_keys_and_other_sources(repo):
    rel = "wiki/proba/2026-09-10-elso-jegyzet.md"
    text = (repo / rel).read_text().replace("lessons:", "sources:\n  - {id: tk, resource: x, title: Tankönyv}\nlessons:")
    (repo / rel).write_text(text)
    assert machine.write_lesson_notes(repo, [{"file": rel, "pages": [1, 2]}], FETCH, 9, "codex", "T") == [rel]
    meta = frontmatter.split((repo / rel).read_text()).meta
    assert [s["id"] for s in meta["sources"]] == ["ora-1", "tk"]
    assert meta["lessons"][0]["title"] == "Bevezetés"
    assert machine.write_lesson_notes(repo, [{"file": rel, "pages": [1, 2]}], FETCH, 9, "codex", "T") == []


def test_stamp_generated_skips_indexes_and_log(repo):
    paths = ["wiki/proba/elso.md", "wiki/proba/index.md", "wiki/log.md", "docs/x.md"]
    assert machine.stamp_generated(repo, paths, "claude", "T") == ["wiki/proba/elso.md"]


def test_add_subjects_never_overwrites(repo):
    new = [{"subject": "proba", "emoji": "x", "color": "#000000"},
           {"subject": "fizika", "emoji": "⚛️", "color": "#336699"}]
    assert machine.add_subjects(repo, new, {"fizika": "Fizika"})
    data = json.loads((repo / "tools/subjects.json").read_text())
    assert data["subjects"]["proba"]["emoji"] == "🧪"
    assert data["subjects"]["fizika"] == {"name": "Fizika", "emoji": "⚛️", "dark": "#336699",
                                          "light": "#d6e0eb"}


def test_skeleton_is_a_valid_empty_index(repo):
    rel = machine.create_subject(repo, "fizika", "Fizika", "fizika-banner")
    text = (repo / rel).read_text()
    assert markers.names(text) == ["chapters", "lessons", "review", "notes"]
    assert "<!-- image: fizika-banner -->" in text
    assert check.check_index_meta(rel, frontmatter.split(text).meta) == []
    assert machine.create_subject(repo, "fizika", "Fizika", "x") is None


def test_existing_subject_settings_get_only_missing_display_fields(repo):
    path = repo / "tools/subjects.json"
    data = json.loads(path.read_text())
    data["subjects"]["statika"] = {"name": "Statika", "dark": "#336699"}
    path.write_text(json.dumps(data))
    new = [{"subject": "statika", "emoji": "📐", "color": "#000000"}]
    assert machine.add_subjects(repo, new, {"statika": "más név"})
    entry = json.loads(path.read_text())["subjects"]["statika"]
    assert entry == {"name": "Statika", "emoji": "📐", "dark": "#336699", "light": "#d6e0eb"}
    before = path.read_bytes()
    assert not machine.add_subjects(repo, new, {})
    assert path.read_bytes() == before
