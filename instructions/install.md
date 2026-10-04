# Installation and reconstruction record

This is the maintained entry point for rebuilding the school-note system. It distinguishes implemented components from planned roles. Append each completed installation step with exact commands, version pins, configuration locations, checks and rollback instructions. Never depend on chat history for a required step. Keep actual account IDs and deployment receipts in private records; credentials belong in a secret store or protected files outside Git.

The mandatory starting point is a Git checkout, an initialized learner profile when requested, and the dependencies of the tools actually selected. Hermes/Discord rows below are optional legacy deployment paths; skip them for another harness. Pi scheduling, Drive inbox polling, public-site export and automated PDF delivery are not installed by this release.

## Order and current coverage

| Component | Rebuild input | Status |
|---|---|---|
| School repositories | This template commit, shared-files.json, local PROFILE.md and subject/index configuration | Implemented; compare common files after bootstrap/update |
| Python note tools | pyproject.toml and uv.lock | Implemented; use uv run, not system pip |
| Optional visual tools | [Installation and execution](install-visual-tools.md), optional `visuals` dependency group, external runtime versions | Repository runner and samples available; verify the selected programs on each machine |
| Curriculum references | Learner's own professional package, general reference package, supplied hashes and catalog | Implemented; raw references remain private; never copy the other learner's package |
| Hermes base runtime | Recorded Hermes Git commit, package-manager lock and private configuration | Existing deployment; a fresh full-machine rebuild has not yet been exercised |
| Drive authentication and upload | [Drive installation](install-drive.md) | Repository CLI available; validate your own configured destinations |
| Separate learner/role executors, Discord identities and routing | Approved private bot plan plus future deployment record | Planned; shared-profile access is not isolation |
| Media generation and bounded spending | Repository image executor, project policy and persistent budget state | Banner/infographic CLI implemented; verify each deployment separately from Discord automation |
| Nightly review and correction | Private scheduler record, timezone, repository, model/effort and trusted channel IDs | Existing jobs audited separately; profile migration still pending |
| OAuth informational website | Public app description and actual privacy page on an owned domain | Deferred by user; not part of the Drive data path |

## Base machine and repositories

Use a dedicated Linux service account, persistent storage and working HTTPS/DNS. Record the OS release, architecture, timezone, system Python and the actual Hermes runtime interpreter separately. The Drive helper uses only the Python standard library on Linux and needs Python 3.10+; Hermes has its own managed runtime and dependencies. Do not infer that invoking the managed Python binary directly activates Hermes packages.

Only for an explicitly selected legacy Hermes deployment, install Hermes using its [official installer and service-user instructions](https://hermes-agent.nousresearch.com/docs/getting-started/installation/). Save the installer and its hash, the resulting Git commit and package-manager lock with the deployment record. The moving installer URL is not an exact-version pin. Keep the actual installed Hermes commit in your private deployment inventory; use the matching upstream installation instructions when rebuilding it and verify the resulting revision. This document does not claim a clean-machine reproduction of that baseline has already passed.

Clone the public template from `https://github.com/dlaszlo/llm-school-notes-template`; record the exact checkout commit. Keep it uninitialized. Create or restore separate child repositories and their local profiles. A new repository follows [Bootstrap](wiki-workflows.md); a restored one retains its original settings and content. Run:

```bash
uv run python -m unittest discover -s tools -p 'test_*.py'
uv run tools/check_shared.py --template /absolute/path/to/llm-school-notes-template
```

Run the second command in each initialized repository. Shared files stay byte-identical; learner settings, approved source/reference files and evidence remain local. Requirements are indexed for bounded retrieval, not bulk-ingested into lesson pages. Never modify the user's external requirements symlinks or their targets.

## Required private deployment inventory

Maintain a private record of the following as each component is installed:

* Machine OS/architecture, service account, timezone, runtime/package-manager versions, repository remotes and exact commits, installation method and file hashes.
* Hermes home/profile paths, model/provider/effort, actual enabled tools and skills, filesystem/executor boundaries, service unit and restart/health-check commands.
* Discord guild/channel/user/bot IDs and routing/mention behavior; secret-manager locations for tokens, not token values. Record invitations and actual access separately from planned membership.
* Google Cloud project and OAuth client type, enabled APIs, scope, Audience publishing status, authorized domains, verified folder IDs/parents and where token/config/ledger backups live.
* Provider model identifiers, enforced cost limits, output paths, source/evidence records and media delivery/verification policy.
* Existing cron job IDs, expression, timezone, target repository, model/effort, correction authorization and delivery destination. Do not create duplicate schedules when restoring.
* Every live check, actual observed output, known limitation and rollback procedure. A copied config, successful unit test or skill discovery is not an end-to-end bot test.

A credential backup is private and encrypted; ordinary Git is never the secret backup. Profile exports may omit credentials. Retain private raw references, evidence and upload ledgers separately from the public template. Reauthenticate when credentials are unavailable or revoked.

## Completion criteria for a future full rebuild

Rebuild on an empty machine from the pinned inputs, restore or freshly authorize secrets, then prove: each bot sees only its intended learner/context; authorized ingest reaches the right repository; one artifact per media type passes content and delivery checks; repeated/interrupted work does not duplicate uploads or paid calls; budgets stop execution; reviewer evidence is accessible; scheduled corrections run at the intended local time; backup and rollback work. Until that exercise passes, report the installed stages and remaining stages individually, not "fully reproducible system".

## Banner and infographic executor

Follow [repository-local setup](install-learning-images.md). All executable code and instructions remain in a Git checkout. No global skill or agent-program modification is required. Test the ordinary unconfigured wiki first; then configure only the requested optional services. Actual private credentials and historical state are separate restore inputs and never supplied by a clone.

## Optional page-check runtime

For agents maintaining Markdown pages, install the locked repository-local Node dependencies and select an available Chromium browser using [page-check setup](page-check.md). Record Node/browser versions and paths in the private inventory. No global skills or Hermes code changes are needed. Outside a school-notes tool run, ordinary note work may run the prepared checker and does not repeat installation; inside a run the tool builds and checks the pages.
