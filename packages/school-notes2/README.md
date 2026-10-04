# school-notes2 – map

The host-side tool of School Notes v2 (plan: `school-notes-ops/docs/v2/2026-10-02-school-notes-v2-terv.md`).
It does every mechanical step; the LLM runs in a container and asks for mechanical work only through MCP.

## Flows

| Command | What it does | Code |
|---|---|---|
| `school-notes run <learner>` | hourly: Drive → sources → writer (container) → `finish` (check, generation, commit, rebase, build, push, release) | `flows/run.py`, `flows/fetch.py`, `flows/writer.py`, `flows/finish.py`, `flows/steps.py` |
| `school-notes nightly <learner>` | nightly: review of `claude-reviewed..main`, report commit, atomic push | `flows/nightly.py`, `review/` |
| `school-notes chat <learner> [codex\|claude]` | the owner's session in the same container; `fetch`/`finish` through MCP | `flows/chat.py`, `flows/handlers.py`, `flows/session.py` |
| `school-notes status [<learner>]` | local state; `--clear <learner> notes\|review\|publish --continue\|--discard` | `flows/status.py`, `flows/clear.py` |
| `school-notes setup <learner>` | bare clones and the three durable worktrees, once | `flows/setup.py` |
| `school-notes fetch\|finish <learner>` | the MCP operations, from the host shell | `cli.py` |
| `school-notes verify-tasks` | the installer checks that this release can read every open task | `cli.py` |
| `python -m school_notes2.migration` | the one-time v1 → v2 migration and the T1 difference list | `migration.py` |

## Folders

| Folder | Responsibility |
|---|---|
| `config.py` | reads and validates `~/.config/school-notes/config.toml` |
| `state/` | `phase.json` (task folder), the per-learner lock, error classes, atomic writes |
| `log/`, `notify/` | JSONL log; e-mail through `msmtp`, once a day per kind |
| `git/` | the only Git caller (`run.py`), bare clones, work branch, `finish` G0–G9, conflicts, discard |
| `drive/` | listing, readiness, download, move (built on `tools/drive_media.py`) |
| `sources/` | order, photo and PDF preparation, hashes, duplicates, batching |
| `wiki/` | path guard, `check`, machine frontmatter, indexes, `public.json`, migration |
| `review/`, `evidence/` | nightly review (range, input, closing), review files, evidence records |
| `images/` | wrapper of `tools/learning_image.py`: daily budget, lock, generation, acceptance |
| `site/` | public build from a commit (`study-site`) and the `gh-pages` release |
| `llm/` | the `podman run` argv, role templates (`templates.toml`), fixed prompts, output |
| `container/` | `Containerfile`, entrypoint, firewall, preflight |
| `mcp/` | the MCP server on a unix socket, background jobs, `redact()` |
| `flows/` | wiring per entry point; one error policy (`policy.py`) |
| `ops/` | `install.sh <tag>`, crontab, logrotate and configuration examples |
| `schemas/` | the schema of every JSON contract |

## Subject cards

A subject entry in the learner's `tools/subjects.json` may contain `card` with nonempty
`role` and `style` strings and an ordered `conventions` array (empty if no local convention
is confirmed). `schemas/subject-card.json` is shared by configuration loading and the
`fetch.json` contract. See [the empty-template example](../../examples/subject-card.json).
Preparation snapshots cards in the durable package data; resume does not reload changed
configuration. Missing cards stay absent, including newly discovered subjects. The owner's
session may edit valid cards of existing subjects; cron cannot edit them or other settings.

The source-grounded repair rules and writer/fix prompts describe the target step-1/2
contracts; their remaining flow integration is staged separately. `fix.txt` is loadable,
but this unit does not introduce a fix run or the new reviewer state machine. The current
nightly prompt uses the existing output contract, with additive private `owner_notes`.

## Development

```
uv sync
uv run --group dev pytest -q          # unit, integration and end-to-end tests
cd ../study-site && npm test          # renderer tests
```
The tests use real `git` with local bare origins, and fake Drive, OpenRouter and `podman`.
