import json

import pytest

from school_notes2.images.executor import ExecutorError, read_key
from school_notes2.local import keys
from school_notes2.state.errors import Prerequisite


def test_parse_env_plain_quoted_multiline_and_comments():
    text = ("# keys\nexport A=1\nB = 'two words'\nC=\"x=y\"  \nD='{\"a\": 1,\n \"b\": 2}'\n"
            "E=plain # comment\nnot a line\n")
    assert keys.parse_env(text) == {"A": "1", "B": "two words", "C": "x=y",
                                    "D": '{"a": 1,\n "b": 2}', "E": "plain"}


def test_drive_token_takes_client_fields_from_the_client_json():
    token = {"refresh_token": "r", "scopes": ["https://www.googleapis.com/auth/drive"]}
    client = {"installed": {"client_id": "id", "client_secret": "secret"}}
    got = keys.drive_token({"GOOGLE_DRIVE_TOKEN_JSON": json.dumps(token),
                            "GOOGLE_CLIENT_SECRET_JSON": json.dumps(client)})
    assert got == {**token, "client_id": "id", "client_secret": "secret"}
    full = {**token, "client_id": "own", "client_secret": "own-secret"}
    assert keys.drive_token({"GOOGLE_DRIVE_TOKEN_JSON": json.dumps(full)}) == full
    with pytest.raises(Prerequisite):
        keys.drive_token({})


def test_image_key_from_the_dotenv_file_among_other_entries(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GOOGLE_DRIVE_TOKEN_JSON='{\"a\":\n1}'\nOPENROUTER_API_KEY=\"sk-or-1\"\n")
    assert read_key(env) == "sk-or-1"
    env.write_text("OTHER=1\n")
    with pytest.raises(ExecutorError):
        read_key(env)
    bare = tmp_path / "openrouter.key"
    bare.write_text("sk-or-bare\n")
    assert read_key(bare) == "sk-or-bare"


def test_https_url():
    from school_notes2.local.common import https_url
    assert https_url("git@github.com:org/x.git") == "https://github.com/org/x.git"
    assert https_url("https://github.com/org/x.git") == "https://github.com/org/x.git"


def test_https_token_lives_only_in_the_environment_and_goes_only_to_github(log):
    from pathlib import Path
    from school_notes2.git.run import Git, HttpsToken
    git = Git(Path("/x/.git"), "n", "e", log, HttpsToken("secret-token"), Path("/x"))
    argv = git.argv(["push"])
    assert all("secret-token" not in a for a in argv)
    helpers = [a for a in argv if "credential" in a and "helper" in a]
    assert "credential.helper=" in helpers                      # every generic helper reset
    assert any(a.startswith("credential.https://github.com.helper=!f()") for a in helpers)
    assert not any(a.startswith("credential.helper=!") for a in helpers)
    assert "protocol.allow=never" in argv and "protocol.https.allow=always" in argv
    assert git.env()["SN_GIT_TOKEN"] == "secret-token" and "GIT_SSH_COMMAND" not in git.env()
    assert "secret-token" not in repr(HttpsToken("secret-token"))


def test_auth_failures_need_the_owner():
    from school_notes2.git.run import classify
    from school_notes2.state.errors import NeedsOwner
    for text in ("fatal: Authentication failed for 'https://github.com/x/y.git/'",
                 "fatal: unable to access 'https://github.com/x/': The requested URL returned error: 403",
                 "fatal: could not read Username for 'https://github.com': terminal prompts disabled"):
        assert isinstance(classify("push", text, 128), NeedsOwner)


def test_local_git_network_branch_carries_gh_token(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from school_notes2.git.run import HttpsToken
    from school_notes2.local import common
    monkeypatch.setattr(common, "gh_token", lambda: "tok")
    (tmp_path / ".git").mkdir()
    cfg = SimpleNamespace(git_name="n", git_email="e", log_path=tmp_path / "log")
    local = common.Local(SimpleNamespace(cfg=cfg, name="t"), tmp_path)
    assert local.git(network=True).remote == HttpsToken("tok")
    assert local.git().remote is None


def test_require_github():
    from school_notes2.local.common import require_github
    from school_notes2.state.errors import NeedsOwner
    assert require_github("https://github.com/o/r.git", "x")
    for url in ("http://github.com/o/r.git", "https://github.com.evil/o", "/tmp/origin.git",
                "git@github.com:o/r.git", "https://gitlab.com/o/r.git"):
        with pytest.raises(NeedsOwner):
            require_github(url, "x")
