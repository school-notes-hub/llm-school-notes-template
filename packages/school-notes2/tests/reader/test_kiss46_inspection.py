"""Fix-46: one independent check per run. P5 rechecks every changed author line against the
base; only a learning-blocking finding on a changed line is an item. P3 reads only the
changed pages; the reviewer names the line; the tool only validates it."""


from school_notes2.flows import inspection
from school_notes2.review import files, relations
from school_notes2.state import phase, safefs
from .helpers import finding, install_reader


def items(ctx):
    return relations.inventory(ctx.notes_path)["items"]


def report_notes(ctx, task):
    return safefs.read_text(ctx.notes_path, task.get("inspection_report"))


def recheck(ctx, task):
    task.update(mode="fix")
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    return phase.load(task.dir)


def test_p5_item_only_for_an_error_on_a_changed_line(setup, monkeypatch):
    ctx, task, page = setup
    invoked = install_reader(monkeypatch, page, recheck_findings=[
        finding(page, line=7, id="F-1"),                                  # changed line: item
        finding(page, line=5, id="F-2", problem="Régi cím gondja."),       # unchanged: owner note
        finding(page, line=7, id="F-3", severity="javaslat", problem="Javaslat.")])  # advice: note
    task = recheck(ctx, task)
    assert invoked == ["recheck"]
    found = list(items(ctx).values())
    assert [(i["origin"], i["chain"], i["status"]) for i in found] == [("recheck", 1, "open")]
    notes = report_notes(ctx, task)
    assert "Régi cím gondja." in notes and "Javaslat." in notes


def test_p5_compares_with_the_base_and_skips_no_changed_page(setup, monkeypatch):
    """The coordinator's 45b concern: no change may escape the independent recheck."""
    ctx, task, page = setup
    seen = []
    def fake(repo, view, folder, stage, assigned, configured, **kw):
        seen.append(safefs.read_json(folder / "in", "pages.json")[0]["changed_lines"])
        return {"status": "reviewed", "model": "m/high", "review": {"items": [], "findings": [], "owner_notes": []}}
    from school_notes2.reader import calls
    monkeypatch.setattr(calls, "run", fake)
    recheck(ctx, task)
    assert seen == [[{"line": 7, "text": "A test lefelé gyorsul."}]]


def test_p5_not_ok_reopens_the_fixed_item_and_deep_chains_go_to_the_owner(setup, monkeypatch):
    ctx, task, page = setup
    report = files.write_review(ctx.notes_path, "2026-10-05", {"verdict": "changes", "findings": [
        {"severity": "hiba", "id": "R1", "file": page, "problem": "Hiba.", "relates_to": None, "chain": 3}]},
        "r", "a", "b").relative_to(ctx.notes_path).as_posix()
    files.apply_closure(ctx.notes_path, task.run_id, [{"file": report, "item_id": "R1", "status": "fixed"}],
                        files.open_items(ctx.notes_path, "cron"), automatic=True)
    task.update(inspection_result={"status": "done", "review_closure": [
        {"file": report, "item_id": "R1", "status": "fixed"}]})
    install_reader(monkeypatch, page, recheck_findings=[
        finding(page, id="F-1", item_key=report + "#R1"), finding(page, id="F-2", problem="Új hiba.")])
    recheck(ctx, task)
    found = items(ctx)
    assert found[report + "#R1"]["status"] == "open" and found[report + "#R1"]["recheck"]["verdict"] == "not-ok"
    new = [i for k, i in found.items() if k != report + "#R1"]
    assert [(i["chain"], i["status"]) for i in new] == [(4, "owner")]


def test_p3_reads_only_changed_pages_and_names_lines(setup, monkeypatch):
    ctx, task, page = setup
    other = "wiki/m/lesson.md"
    safefs.write_text(ctx.notes_path, other, "---\ntype: lesson-notes\nlessons:\n  - topics: [topic.md]\n---\n# Óra\n")
    seen = []
    def fake(repo, view, folder, stage, assigned, configured, **kw):
        seen.append([p["file"] for p in assigned["pages"]])
        review = {"pages": [{"file": p["file"], "verdict": "changes", "first_glance": ""} for p in assigned["pages"]],
                  "findings": [finding(page, line=7), {**finding(other, line=1), "id": "F-2", "problem": "Kontextus."}],
                  "owner_notes": []}
        from school_notes2.reader import contracts
        return {"status": "reviewed", "model": "m/high",
                "review": contracts.check(review, stage, assigned, allowed_paths=())}
    from school_notes2.reader import calls
    monkeypatch.setattr(calls, "run", fake)
    inspection.prepare(ctx, task)
    inspection.inspect(ctx, task)
    assert seen == [[page]]  # the unchanged lesson is context only
    found = list(items(ctx).values())
    assert [(i["file"], i["origin"]) for i in found] == [(page, "reader")]
    assert "Kontextus." in report_notes(ctx, phase.load(task.dir))


def test_invalid_new_commission_is_no_figure_never_a_program_error(setup, monkeypatch):
    """Opus #7: P2 never sends the run back or raises; the text work stays."""
    ctx, task, page = setup
    install_reader(monkeypatch, page)
    task.update(inspection_result={"status": "done", "figures": [{"id": "nincs", "page": page, "kind": "figure"}]})
    inspection.prepare(ctx, task)
    assert phase.load(task.dir).get("inspection_figures") == []
