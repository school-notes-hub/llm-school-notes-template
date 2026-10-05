"""Shared fakes for the independent reader and recheck calls."""

from school_notes2.reader import calls


def install_reader(monkeypatch, page, *, findings=None, recheck_findings=None):
    invoked = []
    def fake(repo, view, folder, stage, assigned, configured, **kw):
        invoked.append(stage)
        if stage == "reader-1":
            review = pass1(page, findings)
        else:
            review = {"items": [{"severity": "hiba", "key": i["key"], "verdict": "ok" if i["status"] == "fixed" else "keep",
                                   "answer": "Indok"} for i in assigned["items"]],
                      "findings": list(recheck_findings or []), "owner_notes": []}
        return {"status": "reviewed", "model": "model/high", "review": review}
    monkeypatch.setattr(calls, "run", fake)
    return invoked


def finding(page, line=7, **extra):
    return {"severity": "hiba", "id": "F-1", "file": page, "line": line, "quote": "A test lefelé gyorsul.",
            "category": "olvasói lyuk", "problem": "Hiányzik az ok.", "suggestion": "Magyarázd el.",
            "relates_to": None, **extra}


def pass1(page, findings=None):
    return {"pages": [{"file": page, "verdict": "changes" if findings else "ok", "first_glance": "Téma"}],
            "findings": findings or [], "owner_notes": []}
