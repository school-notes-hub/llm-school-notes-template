# school-notes2 – map

The host-side tool of School Notes v2 (plan: `school-notes-ops/docs/v2/2026-10-02-school-notes-v2-terv.md`).
It does every mechanical step; the LLM runs in a container and asks for mechanical work only through MCP.

## Flows

| Command | What it does | Code |
|---|---|---|
| `school-notes run <learner>` | hourly: Drive → sources → writer (container) → `finish` (check, generation, commit, rebase, build, push, release) | `flows/run.py`, `flows/fetch.py`, `flows/writer.py`, `flows/finish.py`, `flows/steps.py` |
| `school-notes repair <learner> --topic wiki/<subject>/<page>.md [--no-push]` | existing-page repair with the writer and finish chain, without Drive or paid generation | `flows/repair.py`, `repair/` |
| `school-notes repair <learner> --queue [--no-push]` | build/reorder the private repair queue and SVG inventory, without an LLM | `repair/queue.py` |
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
Drive movement. Download retries validate against a fresh base; the first move pins
the preparation commit before its external action, also across an interrupted move.

The source-grounded repair rules and writer/fix prompts describe the target step-1/2
contracts; their remaining flow integration is staged separately. `fix.txt` is loadable,
but this unit does not introduce a fix run or the new reviewer state machine. The current
nightly prompt uses the existing output contract, with additive private `owner_notes`.
Writer `owner_notes` are emitted as `writer.owner_notes` JSONL log events and, at completion,
in the private task `report.json`, the finish response and an existing once-per-run e-mail
notice, with token-like secrets redacted. The new full e-mail layout remains step 3. The additive figure lists and `coverage` survive range merging; their remaining
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
The tool renders the fixed 📎 line in `lesson-sources`, after the header, collapsing
consecutive identical dates (including undated lessons). Teaching
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
not subject legacy pages to the new lesson-log or question form. Metadata errors that
already exist in the base require owner intervention even on author-edited pages;
new errors return to the writer. Content errors do not hide independent order or
publication findings from the same check. `flows/learning.py`
records each impending replacement before writing and pins the observation date in
the existing task state, so interrupted generation resumes without restarting the
clock or rejecting the tool's own writes. No new phase or LLM call is introduced.


## Checks and review closure (unit 1c)

Source-reference patterns in `study-site/public-patterns.json` are warning-only. The scanner
uses changed lines, including Markdown title/description, Mermaid and SVG labels, with the
structural exceptions from repair plan 8.2. `source_refs.scan(full=True)` and task data
`mode: repair` support the later repair entry point. No rule enters the publication gate.
The fixed corpus is tested against both optional local learner checkouts, read-only.
`SN_LEARNER_REPOS` may supply their paths as a colon-separated list (directories named
`school-notes-benedek-active` and `school-notes-barna-active`); absent that variable,
the tests search the usual sibling directories.
Per-file counts (before verdict suppression) appear in logs and status.

MCP check returns errors first, full counts, `truncated` and the full-list path. A durable
counter permits three checks per invocation, including across background-job restarts;
fetch of the same interactive run does not reset it; a new run gets its own budget.
The last own check's warning IDs must have decisions.
An unfinished question session keeps its result and returns to `needs_owner` when those
decisions are missing; cron cannot overwrite the owner's answer.
Later tool warnings without decisions are persisted with `unhandled` for reviewer handoff.
Accepted/false-positive list verdicts use `review.warnings.record` and the private
`warning-verdicts.json`; repeating a write is idempotent, content changes invalidate it.
The reader's two-pass orchestration and nightly warning-list assembly remain later units;
the storage API returns `hiba` findings for their review-item creation.

Review metadata is additive `item_details`, keeping old `items: {R1: status}` maps readable.
Legacy headings supply the page when metadata is absent. Full keys avoid cross-report R1
collisions. Question/decision references are page-local; asset findings also use the
questions and decisions of their embedding pages, excluding links in code blocks.
Existing question/open-item and disagreement references go to the pending section,
decisions to owner, unknown references
to unlocated. A decision reference without new evidence is invalid reviewer output.
The tool inherits the related item's chain; findings about fixed/settled items escalate to
chain 1 and owner. Owner items use the existing once-per-item notification path, with
a durable handoff across closing restarts. Failed deliveries retry on later nights;
the per-item receipt skips already delivered notices, and the handoff completes only
after every notice has a receipt. Invalid or stale responses are dropped and logged.
Reviewer input groups only open, owner and disagree items by page. Independent review
transitions and appended tool sections merge during rebase; contradictory edits still stop.
An upstream transition to an item in a new closure's `before` map also stops the merge,
so repeated finish cannot restore an obsolete status.
The full nightly targeting/blame policy remains later work.
No new phase, LLM role or call is added; persisted checks, verdict writes and replies have
interruption/resume coverage.

Deployment requires no open notes runs: old saved `result-<k>.json` disagreements
without a substantive `note` cannot satisfy the new closure contract. The controller
checks this before installation; the tool does not invent a historical justification.

`llm_failures` resets with the successful G5 build checkpoint. T-016 uses last-written
whole-file hashes plus provenance: stamping machine fields cannot turn a changed author
page into tool-owned output. Exact tool-only output errors are program errors, never strikes
against the writer. Author text is checked before stamping as well as afterwards.


## Subject calls and one-time repair (unit 1d)

Cron persists the writer assignments in `phase.json`: subjects follow `tools/subjects.json`,
new subjects follow by path; each call receives only its own packages, pages, card and
review/image assignments. The tool assigns at most 20 review items per run, in round-2,
report-date and numeric item order. Unassigned items do not accrue untouched counts.
Subjectless items go to the first call; asset items go to the subject of their first
embedding content page by path. D36 ranges receive each review/image assignment once.
Finish defects return to every affected subject; an unassignable finish defect is a tool
error, not bad writer work. Retry assignments survive interrupted checkpoint invalidation.
Original page sequence IDs survive noncontiguous subject groups. Whole-run validation and machine metadata use the complete input. D16 still selects
whole packages up to `sources.pages_per_call` (30 by default); D36 splits only a single
oversized package, sequentially. Each call is checked before its result checkpoint is saved;
restart after saving reuses it. Existing saved runs without assignments keep their old ranges.
The writer timeout defaults to **7200 s** when omitted; explicit configuration still wins.

`repair --topic` accepts an existing content-page path. It uses the current local
`origin/main` snapshot, no Drive scan or move, and the same writer/check/finish chain.
`fetch.json` has `mode: repair`, a pinned subject/card and `repair_targets` with related
pages and complete local source files. The writer prompt's repair section preserves existing
content, lesson metadata and anchors. A topic pass can adjust only links in related lesson
logs and summaries. The separate lesson-log pass requires item coverage and evidence checks;
semantic completeness remains a writer/reviewer responsibility. Paid generation is disabled.
The independent reader/figure phases will join this chain in step 2, without a separate
repair implementation. This unit does not launch the later figure-agent trial.

`--no-push` stops at **committed**, before fetch, build, push or publication. The
`notes/<run_id>` branch and task stay open. Repeating the command keeps the hold; cron also
leaves it alone and sends a daily reminder with the current phase.
Inspect that worktree/commit on the VM, then explicitly run
`school-notes finish <learner>` to resume the normal finish chain, or
`school-notes status --clear <learner> notes --discard` to archive/discard it. `finish`
may publish only under the existing learner configuration; the trial never changes it.
`status --continue` alone does not release the no-push hold.

Create the queue first with `repair <learner> --queue`. Edit only the `priority` and `urgent` fields
in `docs/repair-queue.json`, then repeat `--queue` to reorder. Lower nonnegative numbers
run first; null is unprioritized. `urgent: true` is an owner designation, preserved
on rebuild; default is false. A visible source-pattern match also makes a page urgent
for ordering, without changing this owner field. No page names are built into the tool.
This command accepts those uncommitted queue edits and
rejects unrelated dirty files. It creates a normal tool-only notes commit (or holds it
with `--no-push`). The queue has `items` and `figures`: page state is `pending`, `done` or
`owner`; figure state starts as `pending` (awaiting inspection), later `keep`, `context`
or `remake`. The tool does not judge diagrams. SVG hashes invalidate old judgements.
Sorting follows plan 11.2: owner-designated or pattern-matching urgent pages, owner priority,
descending pattern-hit count,
descending actual lesson date, path. Filenames never supply lesson dates. Dependent lesson
logs, chapter summaries and review pages wait for every referenced topic to be `done`.
Invalid or dependency-blocked targets are rejected against the local `origin/main`
snapshot before creating a task; they cannot stop another run or the cron.
The scheduler reads the queue in its stored order after new packages and existing pending
image work; the separate daily `fix` entry condition is staged with the later fix flow.
Runs change status without rebuilding or reordering the queue. A direct topic repair
without a queue is allowed, but does not create one or complete absent entries.

Two bad repair attempts hand the topic to an owner review item: the failed work is archived
as a local Git bundle, then a tool-only continuation commits the queue's `owner` state
(if a queue exists) and notifies once. The next runnable entry can proceed. Dependencies of an owner-blocked topic
remain blocked. Preparation, per-call result saving, queue replacement and the committed
hold all have interruption/resume tests. No new phase or model is introduced.

The controller's trial order (repair plan 13/1, K-6) is sequential. Every step uses
`--no-push`; the controller (and the owner in the morning) inspects it, then `finish`
closes it before the next step:

1. Create the repair queue.
2. Repair the polisz topic page.
3. Repair its lesson log, after all its topic dependencies are done.
4. Adjust only the polisz links in the Hellász summary. Use a topic-page repair pass
   for these related-page link changes; do not target the summary for a full rewrite.

The full summary rewrite belongs to implementation step 6, when every topic in the
chapter is done. `require_ready` stays strict; held branches never satisfy the next
run's dependencies. Queue-only and failed-repair handoff holds also resume with `finish`.

## Development

```
uv sync
uv run --group dev pytest -q          # unit, integration and end-to-end tests
cd ../study-site && npm test          # renderer tests
```
The tests use real `git` with local bare origins, and fake Drive, OpenRouter and `podman`.

## Independent figures (unit 2a)

`figures/` is a separately callable pipeline; P2–P5, owner notifications and the
pending notice/fetch handoff join in unit 2b. No new scheduler phase is enabled here.
The existing `image_generate` retains its budget and attempt limits. `image_accept`
is no longer an MCP tool in either mode. The writer guard refuses direct insertion
of new/changed image bytes, including SVG; an inline Mermaid change requires a
commission and goes through the same independent review input.

The writer leaves exactly one `figure` or `image` marker and writes
`.school-notes/figures/<id>.json` (schema `figure-commission`). `anchor` is the exact,
unique section heading. `source_image` has `path` and a pixel crop
`[left, top, right, bottom]`. Replacements require `replaces` and
`decision_reason: {code: a|b|c, text}`. The commission's page determines the primary
topic; a lesson log belongs to its first listed topic. Duplicate replacements fail.

The candidate at `figures/<id>/figure.json` uses schema `figure-candidate`:
`state: candidate|failed|no-figure`; failures/omissions have `reason`. A candidate
has `asset` (the final publication bytes under `wiki/assets/`), `alt`, `caption`
(possibly empty), `form`, `tool`, `elements[{element, meaning}]`, `visible_text`,
`attempt`, and optional `source` or `render`. Generated images use the publication
preview bytes, not a different later encoding. Source drawings require private
`corrections[]` (possibly empty) and cannot use `no-figure`. Mermaid uses a one-based
`mermaid` block number instead of `asset`; its Markdown remains inline.

Call `commissions.validate_assignments`, then `inputs.batches` and
`review.run_batch` with a configured reviewer `RoleRun`. It uses the configured
`claude-review` model, 1800 seconds, the reviewer home, no MCP and only `wiki/`
mounted read-only at `/work`. `figures.render.Renderer` invokes the study-site's
existing Mermaid renderer/SVG sanitizer and an offline browser rasterization;
it needs the installed study-site dependencies and Chromium. Tests inject a renderer
and harness. A rendering failure is a hard preparation error for the caller to turn
into a failed/pending commission; heuristic warnings never prevent review.

Each call receives full/390px images, editable source/render record, machine hints,
commission, embedding section and neighbours, source crop when present, other uses,
topic image inventory, open questions, decisions and open/disputed review keys.
It never receives the generating prompt, `figure.json` self-evaluation or alternatives.
The output schema requires exactly one hash-bound verdict per assigned ID plus
`owner_notes`. A valid saved result survives interruption; malformed output has one
format retry, a crashed call one retry, timeout none. Retry counters survive restart.
The trusted task receipt is the input to `insert.insert`; never load that argument
from a writer-controlled file. The repo copy is at
`.school-notes/figure-review/<topic>-<n>.json` (topic path hash disambiguates names).

`insert.insert` rechecks the key, writes evidence and `docs/review/verdicts.json`,
then atomically replaces the page marker with the image, caption and observed
`image-description` in a protected generated block. `verifier` is the independent
reviewer's configured model/effort. Replays are idempotent; replacement retains the
old asset and removes its old link/comment. Mermaid only gets evidence/verdicts.
`insert.invalidated` detects stale final keys after rebase without launching an LLM.
Teaching keys bind image bytes, alt, caption and section (and other real uses);
banner keys bind image bytes, title and description. Rule versions are excluded.

`pending.record/load/eligible/restore/clear` maintains `docs/figure-pending.json`
in commission-ID order. It keeps the full commission and latest defects; unique run
IDs make increments replay-safe. At three runs, `owner_required` is true and the
commission is no longer eligible. The future orchestrator creates/notifies the owner
item and the learner-facing pending notice. No owner wording is invented here.
