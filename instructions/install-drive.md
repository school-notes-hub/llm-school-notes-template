# Install the private Drive media connection

This runbook reconstructs the implemented Drive layer from a Linux Git checkout. The common code and skill contain no family-specific IDs. A running multi-bot deployment is not required for these checks. See [installation inventory](install.md) for the full-system boundary and [handoff contract](media-handoff.md) for future protected executors.

## 1. Prerequisites and cloud setup

* Linux and Python 3.10+. Any agent with repository/file and terminal access can use the tools; Hermes is not required. No pip packages, MCP server or general Google Workspace credential are needed by these helpers.
* A Google account owning the learning-media folders, a Cloud project, and enabled Google Drive API and Google Picker API.
* A Google Auth Platform OAuth client of type **Desktop app**. Download its JSON privately. The helper expects the `installed` block, not a web-client credential.
* Scope: only `https://www.googleapis.com/auth/drive.file`. This is per-file authorization plus app-created files, not a sandbox for exactly two folders. A selected parent does not prove access to pre-existing child files.
* For persistent use, check Google Auth Platform > Audience > External / In production. Drive refresh tokens for an External / Testing app expire after seven days. Production status is distinct from verified/published Branding. Personal/few-known-user use can be exempt from submitting verification; there is no separate personal-use switch.
* Branding URLs describe the app and data practices. Use actual public informational/privacy pages when supplying those links; a repository front page is not a privacy policy. These URLs are not where the desktop app runs or where Drive content passes through.

References: [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration), [personal-use exception](https://developers.google.com/identity/verification/authentication-verification#personal-use).

## 2. Install the code from the pinned template checkout

Run from your own private repository checkout. Keep all executable code in Git; do not install copies in the agent's directories. For a new setup, create the ignored `.drive-state/` directory with mode 0700 and place your own downloaded Desktop credential there as `client_secret.json`, mode 0600. Use the repository's `tools/drive_connect.py` and `tools/drive_media.py` directly.

Before transferring any existing credential/token, disclose source, destination and purpose and obtain explicit approval. Existing deployments can leave their credentials and state untouched and pass `--config-dir /existing/private/directory` to each command. No global skill installation or agent-program modification is required.

## 3. Authorize interactively

```bash
python3 tools/drive_connect.py start
python3 tools/drive_connect.py finish
```

The first command prints an authorization link. Open it in a normal browser, sign in as the Drive owner, and select the intended existing folders explicitly. The second command waits for hidden input. After completing consent, the browser reaches `http://localhost:1/...`; no callback server is running there, so a connection/unsafe-port error is expected. Copy the complete final URL from the address bar directly into the hidden terminal prompt, then Enter. A `drive.google.com/picker/...` URL is an intermediate step and must not be pasted. Authorization URLs from another setup run do not match the current state/PKCE verifier.

The helper verifies state, exchanges the code, refuses unexpected scopes, requires a refresh token, and stores `token.json` privately. Confirm:

```bash
python3 tools/drive_connect.py check
```

Expected: `REFRESH_OK; scope=drive.file`. Folder access must still be checked, even after authentication succeeds.

### Picker failure observed during the pilot

The Google-hosted Picker returned a white screen because a `gstatic.com` JavaScript URL returned HTTP 404 with `text/html`; browser `nosniff` correctly blocked it. Removing the optional folder MIME filter allowed the selection interface to appear; the helper now omits that filter. Adding `hl=en` did not solve the later failure. This was not fixed by configuring the application's website. A full Picker success is not claimed.

The working fallback, with the same narrow scope, was:

```bash
python3 tools/drive_connect.py start-basic
python3 tools/drive_connect.py finish
python3 tools/drive_connect.py check
```

`start-basic` omits the Picker, so it can complete authentication without newly granting access to pre-existing folders. In the pilot the earlier selection had already granted the root and both child folders; an actual API query confirmed them afterward. Do not assume that a fresh installation will inherit that grant. If the required folders remain inaccessible, complete a working Picker flow or explicitly arrange app-created destinations before continuing. Do not silently broaden to full Drive access or claim a pasted folder URL grants access. `start`/`start-basic` refuse to overwrite an existing token; an administrator must deliberately back it up and choose a reauthorization procedure if needed.

## 4. Configure and verify destinations

Create `.drive-state/uploader.json` privately, with actual IDs obtained from the user's Drive links/authorized metadata. Replace all placeholders; use a separate ordinary outbox directory for each learner:

```json
{
  "schema_version": 1,
  "parent_id": "PARENT_FOLDER_ID",
  "destinations": {
    "learner-a": {
      "folder_id": "LEARNER_A_FOLDER_ID",
      "outbox": "/home/SERVICE_USER/.local/share/hermes-drive/outbox/learner-a"
    },
    "learner-b": {
      "folder_id": "LEARNER_B_FOLDER_ID",
      "outbox": "/home/SERVICE_USER/.local/share/hermes-drive/outbox/learner-b"
    }
  }
}
```

Set the JSON to mode `0600`; create the outboxes mode `0700`. For each configured learner:

```bash
python3 tools/drive_media.py check --learner learner-a
```

Expected JSON: scope `drive.file`, refresh `ok`, parent `verified`. A missing or moved folder fails. Check every configured learner independently. The pilot's `destinations.json` and `selected-folders.json` are setup records; the uploader's authoritative mapping is `uploader.json`.

## 5. Upload, verify and retry

Place an approved artifact in the selected learner's outbox. Supported types: PNG, JPEG, PDF, MP3, WAV, maximum 128 MiB. Use a stable ASCII request ID for one artifact version:

```bash
python3 tools/drive_media.py upload --learner learner-a --request-id topic-infographic-v1 --file /home/SERVICE_USER/.local/share/hermes-drive/outbox/learner-a/topic.png
python3 tools/drive_media.py verify --learner learner-a --request-id topic-infographic-v1
```

Success returns file ID, Drive URL, SHA-256, byte count and `verified: true`, after downloading all uploaded bytes and comparing them. Repeat the upload command: the same ID must be returned. A changed artifact requires a new version ID. Lost responses and interrupted transfers retain the original request ID and ledger; the next invocation reconciles the preallocated Drive ID and resumable offset. It never blindly creates a second file. A remote file with wrong parent, ownership marker, learner or contents is refused. Inputs outside the learner's outbox, symlinks, unsupported formats and unknown learner IDs are refused. The helper has no sharing, delete, trash or arbitrary-target option.

Run a small synthetic PNG trial for each learner before real media. Save receipts in the private deployment record. The initial pilot left one 135-byte `drive-connection-test.png` in each destination; it repeated each upload and verified the same file ID. Those files are test artifacts, not learning material. A future installation can use any valid, non-sensitive small PNG for the same check.

Open each returned link while signed in as the owner. Then the parent configures intended sharing and checks access from the child's account; the uploader never changes sharing. `shared: false` means API verification alone has not established learner access. The cloud reviewer needs its own approved evidence access; the Hermes token is not automatically available there.

## 6. Hermes integration and limits

Agents read this guide from the selected Git checkout and invoke its tools through their existing terminal. No installed skill, copied script, MCP server or daemon restart is part of this integration. Verify real file/terminal access separately from reading these instructions. Legacy installed copies must not be used as the source of truth; execute the pinned repository revision with an explicit legacy `--config-dir` if needed.

This is a bounded CLI, not a security boundary against the Unix account that owns its credentials. The current common profile may choose either configured learner. Future child-specific bot profiles must use separately enforced executor/filesystem access before claiming that a bot cannot access another child. Never present a prompt, a CLI check or `0600` files readable by that same bot user as OS isolation.

## 7. Backup, restore and rollback

* Back up `client_secret.json`, `token.json`, `uploader.json` and `uploads/` together in private encrypted storage; include outboxes for interrupted jobs. Upload ledgers contain temporary resumable URLs and must remain private. Keep the pinned common-code commit and deployed hashes alongside the backup.
* After restore, preserve owner and `0700` directory/`0600` file modes, run `check` and `verify`, then retry any unfinished work with its original request ID. Losing the ledger loses local deduplication history; do not generate new IDs and repeat old jobs blindly.
* To roll back code, check out the reviewed previous Git revision; retain private state and uploaded files. Do not delete tokens or revoke access merely to revert a code change. For intentional disconnection, the account owner can revoke the app in Google Account security settings.
* Keep OAuth credentials out of Git. The template's private deployment records, app IDs, receipts and actual folder configuration are not required in the public shared files. Update the repository through Git, then rerun checks. No separate installed program copy needs synchronization.
