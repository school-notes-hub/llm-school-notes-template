from school_notes2.wiki import check, frontmatter, machine, markers

def test_skeleton_is_a_valid_empty_index(repo):
    rel = machine.create_subject(repo, "fizika", "Fizika", "fizika-banner")
    text = (repo / rel).read_text()
    assert markers.names(text) == ["chapters", "lessons", "review", "notes"]
    assert "<!-- image: fizika-banner -->" in text
    assert check.check_index_meta(rel, frontmatter.split(text).meta) == []
    assert machine.create_subject(repo, "fizika", "Fizika", "x") is None
