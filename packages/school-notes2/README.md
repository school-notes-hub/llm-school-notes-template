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
session may edit valid cards of existing subjects or preload an entry containing only
`name` and `card`; cron cannot edit them or other settings. A missing subject index
triggers creation with the first package, even for a preloaded card. The tool fills
missing display metadata without overwriting existing values. Card validation precedes
Drive movement and pins the preparation commit, also across an interrupted preparation.

The source-grounded repair rules and writer/fix prompts describe the target step-1/2
contracts; their remaining flow integration is staged separately. `fix.txt` is loadable,
but this unit does not introduce a fix run or the new reviewer state machine. The current
nightly prompt uses the existing output contract, with additive private `owner_notes`.
Writer `owner_notes` are also emitted as `writer.owner_notes` JSONL log events, with
token-like secrets redacted. The additive figure lists and `coverage` survive range merging; their remaining
consumers are staged separately. Warning decisions are validated per writer invocation. `coverage` records
`source`, `unit` and either a `target` topic-section link or an omission `reason`,
without creating an image evidence record. `question`/`settled` closures now validate the reference on the item's page and close it.
A disagreement requires a substantive note; one reviewer reply may reopen it at round 2,
where only `fixed` or `question` can close it.

Reader wording is defined in PROFILE's *Wording* table. Like `generate.TABLE_HEAD`,
the current tool-rendered catch-up heading in `wiki/catch_up.py` is Hungarian;
it is not dynamically localized from PROFILE. A deployment in another language
needs corresponding renderer localization, including the lesson-source line.

## Lesson logs, questions and drafts

`wiki/lesson_log.py` checks the lesson-log heading and its 3–8 learning points, each
linked to a listed topic section. `lessons[].materials` is an optional list of public
names including their kind (`A polisz (prezentáció)`); it never comes from a filename.
The tool renders the fixed 📎 line in `lesson-sources`, after the header. Teaching
coverage, the meaning of the linked section and public suitability remain writer/reviewer checks.

`wiki/decisions.py` checks question anchors and the `decisions` frontmatter records
(`id`, `claim`, `answer`, `by`, `on`), including sorted, unique decision IDs and their
exclusion from open questions. Cron compares the raw decision YAML against the base
before auto-fixes; alias-resolved values are compared too. Interactive answers may
replace questions with decisions. The private `docs/review/dontesek.md` is generated
in page-path/ID order. Frontmatter and comment anchors never enter the site or print
payload. Review findings use `relates_to` with a page question/decision ID or the complete
`docs/review/<file>.md#R<n>` key. The private `relations.json` input supplies those keys.
New review output requires that field and no longer accepts `family_questions`; already
saved old reports can still finish without losing their historical questions.

`status` accepts `draft`, `stable`, `deprecated`; absence means stable. The protected
`draft_tracking: {since: YYYY-MM-DD, lessons: [...]}` field starts when the tool first
observes a draft. Lesson identities are log path plus list position, independent of
lesson date values. Renaming a log (including its date prefix) or inserting a lesson
before an existing one changes those identities and can reset the clock; stable lesson
IDs would be needed to avoid this. An additional linked lesson resets the clock;
prose edits, date-value corrections and repeat checks do not. After more than 14 days,
`check` warns on author-changed draft pages, using the run's pinned observation date.
The repository-wide list is available in `status`. Leaving draft clears tracking
and its generated `pending` notice. Legacy drafts start tracking on first observation;
their original start cannot be inferred from the last edit timestamp.

MCP `check` and finish/rebase generation refresh these outputs. Content checks compare
the author-written part with the run base; tool blocks and machine fields alone do
not subject legacy pages to the new lesson-log or question form. Invalid metadata on
unchanged pages requires owner intervention instead of returning to the writer. `flows/learning.py`
records each impending replacement before writing and pins the observation date in
the existing task state, so interrupted generation resumes without restarting the
clock or rejecting the tool's own writes. No new phase or LLM call is introduced.


## Checks and review closure (unit 1c)

Source-reference patterns in `study-site/public-patterns.json` are warning-only. The scanner
uses changed lines, including Markdown title/description, Mermaid and SVG labels, with the
structural exceptions from repair plan 8.2. `source_refs.scan(full=True)` and task data
`mode: repair` support the later repair entry point. No rule enters the publication gate.
The fixed corpus is tested against both optional local learner checkouts, read-only.
Per-file counts (before verdict suppression) appear in logs and status.

MCP check returns errors first, full counts, `truncated` and the full-list path. A durable
counter permits three checks per invocation, including across background-job restarts;
interactive fetch does not reset it. The last own check's warning IDs must have decisions.
Later tool warnings without decisions are persisted with `unhandled` for reviewer handoff.
Accepted/false-positive list verdicts use `review.warnings.record` and the private
`warning-verdicts.json`; repeating a write is idempotent, content changes invalidate it.
The reader's two-pass orchestration and nightly warning-list assembly remain later units;
the storage API returns `hiba` findings for their review-item creation.

Review metadata is additive `item_details`, keeping old `items: {R1: status}` maps readable.
Legacy headings supply the page when metadata is absent. Full keys avoid cross-report R1
collisions. Question/decision references are page-local. Existing question/open-item
references go to the pending section, decisions to owner, unknown references to unlocated.
Owner notification and the full nightly targeting/chain policy remain controller-layer work.
No new phase, LLM role or call is added; persisted checks, verdict writes and replies have
interruption/resume coverage.

`llm_failures` resets with the successful G5 build checkpoint. T-016 uses last-written
whole-file hashes plus provenance: stamping machine fields cannot turn a changed author
page into tool-owned output. Exact tool-only output errors are program errors, never strikes
against the writer. Author text is checked before stamping as well as afterwards.

## Development

```
uv sync
uv run --group dev pytest -q          # unit, integration and end-to-end tests
cd ../study-site && npm test          # renderer tests
```
The tests use real `git` with local bare origins, and fake Drive, OpenRouter and `podman`.
