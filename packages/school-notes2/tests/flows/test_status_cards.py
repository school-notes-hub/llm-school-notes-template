"""Missing shared cards are reported per learner by `status`, interactively (plan 4.3)."""

import json
from pathlib import Path

from school_notes2 import config
from school_notes2.flows import context, setup, status
from tests.conftest import make_origin
from tests.sources.test_cards import CARD, LEARNERS


def learners(tmp_path, cards: dict | None) -> config.Config:
    """Three learners in one configuration; each repo has two subjects, only `proba` is carded."""
    students = {}
    for grade, name in enumerate(LEARNERS, 9):
        files = {"wiki/index.md": "# W\n", "wiki/proba/index.md": "# Próba\n",
                 "tools/subjects.json": json.dumps({"subjects": {"proba": {"name": "Próba"},
                                                                 "masik": {"name": "Másik"}}})}
        if cards is not None:
            files["subject-cards.json"] = json.dumps({"cards": cards})
        (tmp_path / name).mkdir()
        origin = make_origin(tmp_path / name, files)
        students[name] = {"repo": str(origin), "repo_key": "/nonexistent", "site_repo": str(origin),
                          "site_key": "/nonexistent", "drive_root": f"drive-{name}", "grade": grade}
    return config.parse({
        "root": str(tmp_path / "srv"), "secrets_dir": str(tmp_path / "secrets"),
        "email_to": "o@example.com", "git": {"name": "O", "email": "o@example.com"},
        "release_dir": str(Path(__file__).resolve().parents[4]), "students": students,
        "roles": {"writer": {"harness": "codex", "model": "fake", "effort": "high", "timeout_s": 60},
                  "reviewer": {"harness": "claude-review", "model": "fake", "effort": "high",
                               "timeout_s": 60}},
    })


def summaries(cfg):
    out = []
    for name in cfg.students:
        ctx = context.make(cfg, name, console=False)
        setup.setup(ctx)
        out.append(status.summary(ctx))
    return out


def test_status_lists_missing_cards_for_every_learner(tmp_path, local_origin):
    cfg = learners(tmp_path, {"proba": CARD})
    for data in summaries(cfg):
        assert data["cards"] == {"missing": ["masik"]}
        text = status.render(data)
        assert "hiányzó kártya: masik" in text and "hiányzó kártya: proba" not in text


def test_without_the_shared_file_every_subject_is_missing(tmp_path, local_origin):
    for data in summaries(learners(tmp_path, None)):
        assert data["cards"] == {"missing": ["masik", "proba"]}
        assert status.render(data).count("hiányzó kártya:") == 2


def test_invalid_card_file_is_reported_not_raised(tmp_path, local_origin):
    for data in summaries(learners(tmp_path, {"proba": {"role": " "}})):
        assert "error" in data["cards"]
        assert "kártyafájl:" in status.render(data)
