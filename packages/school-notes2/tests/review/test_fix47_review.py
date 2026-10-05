"""Fix-47 (védelmek-review 5, 7, 8, 13): tool lines are never items in P5 or the nightly
triage; the diff parser follows Git's hunk counts; the reviewer's `/work/` prefix is cut."""

from types import SimpleNamespace

from school_notes2.flows import recheck
from school_notes2.review import nightly
from school_notes2.state import phase, safefs
from school_notes2.wiki import markers

PAGE = "wiki/a.md"


def test_added_lines_follow_the_hunk_counts_and_quoted_paths():
    patch = ("diff --git a/wiki/a.md b/wiki/a.md\n--- a/wiki/a.md\n+++ b/wiki/a.md\n"
             "@@ -1,2 +1,4 @@\n # Cím\n+++ ez egy hozzáadott sor\n+-- és ez is\n Régi.\n"
             'diff --git "a/wiki/sz\\"o.md" "b/wiki/sz\\"o.md"\n--- "a/wiki/sz\\"o.md"\n+++ "b/wiki/sz\\"o.md"\n'
             "@@ -0,0 +1 @@\n+Új.\n")
    assert nightly.added_lines(patch) == {"wiki/a.md": {2, 3}, 'wiki/sz"o.md': {1}}


def test_triage_keeps_tool_lines_and_machine_keys_out_and_cuts_the_work_prefix(tmp_path):
    text = ("---\ntype: lesson-notes\ngenerated: {by: m}\n---\n# Óra\n\n"
            + markers.wrap("lesson-sources", "📎 Füzet: 2026. 09. 01.\n") + "\nSzerzői sor.\n")
    safefs.write_text(tmp_path, PAGE, text)
    lines = text.splitlines()
    patch = f"+++ b/{PAGE}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + line + "\n" for line in lines)
    finding = {"severity": "hiba", "quote": "q", "problem": "P", "relates_to": None}
    at = lambda s: lines.index(s) + 1  # noqa: E731
    review = {"owner_notes": [], "items": [], "findings": [
        {**finding, "id": "R1", "file": "/work/" + PAGE, "line": at("Szerzői sor.")},
        {**finding, "id": "R2", "file": PAGE, "line": at("📎 Füzet: 2026. 09. 01.")},
        {**finding, "id": "R3", "file": PAGE, "line": at("generated: {by: m}")}]}
    items, notes = nightly.triage(review, patch, tmp_path)
    assert [(f["id"], f["file"]) for f in items] == [("R1", PAGE)] and len(notes) == 2


def test_recheck_finding_on_a_tool_line_is_an_owner_note(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    text = "# Téma\n\n" + markers.wrap("pending", "⏳ Ezt az oldalt még ellenőrizzük.\n") + "\nÚj sor.\n"
    safefs.write_text(repo, PAGE, text)
    task = phase.create(tmp_path / "t", "b", "notes", "cron", "inspecting")
    ctx = SimpleNamespace(notes_path=repo)
    written = []
    monkeypatch.setattr(recheck, "report_path", lambda ctx, task, write=None: "docs/review/x.md")
    monkeypatch.setattr(recheck.report, "append", lambda repo, path, findings, notes, label, write=None:
                        written.append((findings, notes, label)) or path)
    monkeypatch.setattr("school_notes2.flows.journal.settle", lambda *a: None)
    monkeypatch.setattr(recheck.steps, "record_tool_files", lambda *a: None)
    finding = {"id": "F-1", "file": PAGE, "quote": "q", "category": "c", "problem": "P", "suggestion": "",
               "relates_to": None, "severity": "hiba", "item_key": None}
    lines = text.splitlines()
    saved = {"receipts": {}, "recheck": [{"page": PAGE, "status": "reviewed", "old": "", "items": [], "review": {
        "items": [], "owner_notes": [], "findings": [
            {**finding, "line": lines.index("⏳ Ezt az oldalt még ellenőrizzük.") + 1},
            {**finding, "id": "F-2", "line": lines.index("Új sor.") + 1}]}}]}
    recheck.apply(ctx, task, saved)
    (findings, notes, label), = written
    assert [f["id"] for f in findings] == ["F-2"] and len(notes) == 1
    assert label == "p5-1"  # never the 2.5.x `recheck-1` label of an older supplement
