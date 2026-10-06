from school_notes2.local import gen
from school_notes2.local.common import today


def test_generate_settles_first_then_calls_the_ledger_path(repo, fake_local, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(gen.generate, "settle_unknown", lambda s, log: calls.append("settle") or [])
    monkeypatch.setattr(gen.generate, "generate",
                        lambda s, fid, note, log: calls.append(("gen", fid, note)) or {"state": "generated", "number": 1})
    note = tmp_path / "note.txt"
    note.write_text(" fix the label \n")
    local = fake_local(repo)
    assert gen.run(local, "fig-1", note) == 0
    assert calls == ["settle", ("gen", "fig-1", "fix the label")]
    assert local.records == [("gen", "generated", {"target": "fig-1", "cost_usd": None, "attempt": 1})]


def test_failed_generation_exits_one(repo, fake_local, monkeypatch):
    monkeypatch.setattr(gen.generate, "settle_unknown", lambda s, log: [])
    monkeypatch.setattr(gen.generate, "generate", lambda *a, **k: {"state": "budget-exhausted"})
    assert gen.run(fake_local(repo), "fig-1") == 1


def test_settle_only(repo, fake_local, monkeypatch):
    monkeypatch.setattr(gen.generate, "settle_unknown",
                        lambda s, log: [{"job": "j", "state": "lost", "cost_usd": "0.05"}])
    monkeypatch.setattr(gen.generate, "generate", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert gen.run(fake_local(repo), None, settle=True) == 0


def test_grant_uses_the_date_as_request(repo, fake_local, monkeypatch):
    seen = []
    monkeypatch.setattr(gen.generate, "settle_unknown", lambda s, log: [])
    monkeypatch.setattr(gen.generate, "grant", lambda s, fid, request: seen.append((fid, request)) or ({"request": request}, True))
    assert gen.run(fake_local(repo), "fig-1", grant=True) == 0
    assert seen == [("fig-1", f"helyi-{today()}")]
    monkeypatch.setattr(gen.generate, "grant", lambda *a: None)
    assert gen.run(fake_local(repo), "unknown-fig", grant=True) == 1
