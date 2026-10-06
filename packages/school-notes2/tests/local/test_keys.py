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


def test_https_token_lives_only_in_the_environment(log):
    from pathlib import Path
    from school_notes2.git.run import Git, HttpsToken
    git = Git(Path("/x/.git"), "n", "e", log, HttpsToken("secret-token"), Path("/x"))
    assert all("secret-token" not in a for a in git.argv(["push"]))
    assert any(a.startswith("credential.helper=!f()") for a in git.argv(["push"]))
    assert git.env()["SN_GIT_TOKEN"] == "secret-token" and "GIT_SSH_COMMAND" not in git.env()
    assert "secret-token" not in repr(HttpsToken("secret-token"))
