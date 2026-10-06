from school_notes2.figures import context, insert
from school_notes2.local import check, done
from school_notes2.state import safefs


def tree(repo):
    return {p: safefs.read_bytes(repo, p) for p in safefs.walk_files(repo)}


def accept(repo, brief, candidate):
    return {"status": "reviewed", "model": "m/high", "review": {"figures": [
        {"id": brief["id"], "key": context.verdict_key(repo, brief, candidate), "verdict": "accept",
         "observed": "Two arrows.", "defects": [], "text_mismatch": [], "relates_to": None}],
        "owner_notes": []}}


def test_done_counts_a_figure_place_and_an_invalidated_verdict_and_never_writes(repo, make_figure):
    brief, candidate = make_figure()
    before = tree(repo)
    lines = []
    assert done.report(repo, lines.append) == 1
    assert tree(repo) == before
    assert "ábrahely elfogadott ábra nélkül: 1" in lines and "árva ábrahely: 1" in lines
    insert.insert(repo, brief, accept(repo, brief, candidate), at="2026-10-07")
    found = dict(done.problems(repo))
    assert found["ábrahely elfogadott ábra nélkül"] == [] and found["érvénytelenedett ábraítélet"] == []
    page = safefs.read_text(repo, brief["page"])
    safefs.write_text(repo, brief["page"], page.replace("Two forces act.", "Three forces act."))
    found = dict(done.problems(repo))
    assert found["érvénytelenedett ábraítélet"] == ["wiki/physics/forces.md#forces"]


def test_done_reports_link_errors_that_check_text_misses(repo, make_figure):
    make_figure()
    safefs.write_text(repo, "wiki/physics/other.md", "---\ntitle: Other\ndescription: Other\ntype: topic\n---\n"
                      "# Other\n\nSee [missing](nincs.md).\n")
    errors = dict(done.problems(repo))["lapellenőrzési hiba"]
    assert any(e.startswith("wiki/physics/other.md") for e in errors)


def test_check_is_read_only_and_exit_code_follows_errors(repo, make_figure, fake_local, capsys):
    make_figure()
    safefs.write_text(repo, "wiki/physics/other.md", "---\ntitle: Other\ndescription: Other\ntype: topic\n---\n"
                      "# Other\n\nSee [missing](nincs.md).\n")
    before = tree(repo)
    local = fake_local(repo)
    assert check.run(local, ["wiki/physics/other.md"]) == 1
    assert check.run(local, [str(repo / "wiki/physics/other.md")]) == 1
    assert tree(repo) == before
    assert "hiba:" in capsys.readouterr().out


def test_check_files_is_called_with_fix_false(repo, make_figure, fake_local, monkeypatch):
    seen = {}
    from school_notes2.wiki import check as wiki_check

    def spy(repo, paths, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(wiki_check, "check_files", spy)
    make_figure()
    assert check.run(fake_local(repo), ["wiki/physics/forces.md"]) == 0
    assert seen["fix"] is False
    seen.clear()
    done.problems(repo)
    assert seen["fix"] is False
