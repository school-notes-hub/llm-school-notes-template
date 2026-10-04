from school_notes2.flows.writer import merge


def test_merge_unions_pages_and_keeps_last_closure():
    r1 = {"status": "done", "notes": [{"file": "wiki/m/2026-10-01-a-jegyzet.md", "pages": [1, 2]}],
          "review_closure": [{"file": "docs/review/x.md", "item_id": "R1", "status": "open"}]}
    r2 = {"status": "question", "questions": [{"text": "?"}],
          "notes": [{"file": "wiki/m/2026-10-01-a-jegyzet.md", "pages": [31, 2]}],
          "review_closure": [{"file": "docs/review/x.md", "item_id": "R1", "status": "fixed"}],
          "checks": [{"page": "wiki/m/a.md", "image": 31, "locator": "1", "observed": "o",
                      "decision": "confirmed"}]}
    merged = merge([r1, r2])
    assert merged["status"] == "question"
    assert merged["notes"] == [{"file": "wiki/m/2026-10-01-a-jegyzet.md", "pages": [1, 2, 31]}]
    assert merged["review_closure"][0]["status"] == "fixed"
    assert len(merged["checks"]) == 1


def test_owner_notes_survive_range_merge():
    from school_notes2.schemas import validate
    results = [{"status": "done", "owner_notes": ["Kihagyott lépés és indoka."]},
               {"status": "done", "owner_notes": ["Jobb javaslat."]}]
    for result in results:
        validate("result", result)
    merged = merge(results)
    validate("result", merged)
    assert merged["owner_notes"] == ["Kihagyott lépés és indoka.", "Jobb javaslat."]
