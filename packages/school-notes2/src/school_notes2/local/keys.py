"""Keys of the local commands: one place, the ops repo's `.env`, read at run time (plan 5).

Nothing here copies a key into a file or prints it. The variable names are the ones the
`.env` holds: `GOOGLE_DRIVE_TOKEN_JSON` (the authorized-user token, full `drive` scope),
`GOOGLE_CLIENT_SECRET_JSON` (the OAuth client, used when the token lacks its client fields)
and `OPENROUTER_API_KEY` (read by the image executor from the same file)."""

import json
import re
from pathlib import Path

from ..state.errors import Prerequisite

ENV_FILE = Path("~/jegyzet/school-notes-ops/.env").expanduser()
LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse_env(text: str) -> dict[str, str]:
    """A dotenv file: `NAME=value`, `export NAME=value`, single- or double-quoted values
    (a quoted value may span lines), `#` comments. Unparsable lines are skipped."""
    values: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = LINE.match(lines[i])
        i += 1
        if not match:
            continue
        name, value = match[1], match[2].strip()
        if value[:1] in ("'", '"'):
            quote, body = value[0], value[1:]
            while quote not in body and i < len(lines):
                body += "\n" + lines[i]
                i += 1
            value = body.split(quote, 1)[0]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[name] = value
    return values


def load(path: Path = ENV_FILE) -> dict[str, str]:
    try:
        return parse_env(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Prerequisite(f"the key file is missing: {path}", todo="restore school-notes-ops/.env") from None


def drive_token(values: dict[str, str]) -> dict:
    """The Drive token as a dict; client id and secret from the client JSON when absent."""
    try:
        token = json.loads(values["GOOGLE_DRIVE_TOKEN_JSON"])
    except (KeyError, ValueError):
        raise Prerequisite("GOOGLE_DRIVE_TOKEN_JSON is missing or not JSON in the key file",
                           todo="put the Drive token into school-notes-ops/.env") from None
    if not (token.get("client_id") and token.get("client_secret")):
        try:
            client = json.loads(values["GOOGLE_CLIENT_SECRET_JSON"])
        except (KeyError, ValueError):
            raise Prerequisite("GOOGLE_CLIENT_SECRET_JSON is missing or not JSON in the key file",
                               todo="put the OAuth client into school-notes-ops/.env") from None
        client = client.get("installed") or client.get("web") or client
        token = {**token, "client_id": client.get("client_id"), "client_secret": client.get("client_secret")}
    return token
