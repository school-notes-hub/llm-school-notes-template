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

The template's shared `subject-cards.json` holds one card per subject, the same for every
learner: `{"cards": {"<subject>": {"role": ..., "style": ...}}}` with nonempty strings and
only generally worded content. It is part of `shared-files.json`, so it is byte-identical in
every learner repo; it is edited only in the template, in an interactive session. A learner's
`tools/subjects.json` holds no card, and a `card` key there has no effect.
`schemas/subject-card.json` is shared by the card file and the `fetch.json` contract.
Taught notation is never on a card: the writer reads it from the notebook. The subject's
place comes from the configured `grade` (`fetch.json` `learner.grade`, required in the
configuration) and the learner's PROFILE. Preparation snapshots cards in the durable package
data; resume does not reload a changed card file. A missing card stays absent: the run goes
on and `school-notes status` shows `hiányzó kártya: <subject>` per learner until the shared
file has it. The card file is validated before Drive movement. Download retries validate
against a fresh base; the first move pins the preparation commit before its external action,
also across an interrupted move.

The prompts' reader yardstick is the learner's school year: the tool fills `{grade}` from
the configuration, as it fills `{output_instruction}`.

The source-grounded repair rules and writer/fix prompts support the P1–P6 flow.
Source-free daily fixes use `fix.txt`; nightly review uses a separate topic contract
with exact page, closure and warning accounting and private `owner_notes`.
Writer `owner_notes` are emitted as `writer.owner_notes` JSONL log events and, at completion,
in the private task `report.json`, the finish response and an existing once-per-run e-mail
notice, with token-like secrets redacted. Operational reports provide the full e-mail layout.
The additive figure lists and `coverage` survive range merging. Warning decisions are validated per writer invocation. `coverage` records
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
`mode: repair` support the repair entry point. No rule enters the publication gate.
The fixed corpus is tested against the optional local learner checkouts, read-only.
`SN_LEARNER_REPOS` may supply their paths as a colon-separated list (directories named
`school-notes-<learner>-active`); absent that variable, the tests search the usual sibling
directories.
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
The reader's second pass and nightly topic calls consume these lists;
the storage API returns `hiba` findings for review-item creation.

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
Notes-run owner items, repair handoffs and `owner_notes` mail also enter the private
per-learner `pending-owner-notices.json` before delivery. Every `run` retries that
queue, even after the originating task has completed; receipts prevent duplicate mail.
Reviewer input groups only open, owner and disagree items by page. Independent review
transitions and appended tool sections merge during rebase; contradictory edits still stop.
An upstream transition to an item in a new closure's `before` map also stops the merge,
so repeated finish cannot restore an obsolete status.
Nightly targeting and blame-based chain routing are implemented by unit 5 below.
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
Interactive preparation puts owner items first within the same capacity, so the owner
can settle them in chat. Both dated report names and repair run IDs supply calendar dates.
Subjectless items go to the first call; asset items go to the subject of their first
embedding content page by path. D36 ranges receive each review/image assignment once.
Finish defects return to every affected subject; subjectless wiki files and unembedded
assets return to the first call. A defect outside writer paths is a tool error.
Retry assignments survive interrupted checkpoint invalidation. Relation discovery skips
unreadable page frontmatter; metadata checks report old defects to the owner and new
defects to the writer, keeping preparation and chat available for repairs.
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
The scheduler reads the queue in its stored order after new packages and daily fix work
(including eligible pending figures).
Runs change status without rebuilding or reordering the queue. A direct topic repair
without a queue is allowed, but does not create one or complete absent entries.

Two bad repair attempts hand the topic to an owner review item: the failed work is archived
as a local Git bundle, then a tool-only continuation commits the queue's `owner` state
(if a queue exists) and notifies once. The next runnable entry can proceed. Dependencies of an owner-blocked topic
remain blocked. Preparation, per-call result saving, queue replacement and the committed
hold all have interruption/resume tests. No new phase or model is introduced.

The controller's trial order is sequential: create the queue, repair one topic page with
`--no-push`, inspect, `finish`, then its lesson log after its topic dependencies are done.
The concrete pages belong to the operations runbook.

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

`figures/` is a separately callable pipeline, wired into P2–P5, owner notifications
and the pending notice/fetch handoff by unit 2b. Units 2a and 2b deploy together.
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
`corrections[]` (possibly empty) and cannot use `no-figure`. Mermaid uses the SHA-256 of its UTF-8 fenced source (including the trailing newline)
in `mermaid` instead of `asset`; exactly one matching block must be in the named
section. Its Markdown and identity marker remain inline. Reordering unchanged blocks
does not require new commissions.

Call `commissions.validate_assignments`, then `inputs.batches` and
`review.run_batch` with a configured reviewer `RoleRun`. It uses the configured
`claude-review` model, 1800 seconds, the reviewer home, no MCP and only `wiki/`
mounted read-only at `/work`. `figures.render.Renderer` invokes the study-site's
existing Mermaid renderer/SVG sanitizer and an offline browser rasterization;
it needs the installed study-site dependencies and Chromium. Tests inject a renderer
and harness. Preparation isolates each failed figure and persists its reason; the remaining
figures are reviewed. The saved preparation and receipt survive interruption.
Heuristic warnings never prevent review.

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
commission is no longer eligible. The 2b orchestrator creates/notifies the owner item and the learner-facing pending notice. No owner wording is invented here.

## Reader and shared correction phases (unit 2b)

Notes finish now advances through durable `figures`, `inspecting`, `correcting`,
`rechecking` and `review_ready` phases before the existing Git finish chain. They
correspond to P2–P6; each attempt has separate call receipts. A valid completed
output survives interruption. Invalid reviewer output permits one format retry;
a crashed call permits one retry; timeout proceeds with the role's missing-review
fallback. `waiting_quota` preserves its phase and does not consume these retries.
The quota provider, weekly pre-call gate and T-125 suspension/notification policy
remain the next operational unit; this unit supplies their resumable state boundary.

The reader receives a read-only wiki snapshot with candidate images in place,
assigned pages, diffs, questions, decisions and open/disputed items. Pass one has
no machine-list file, source, evidence, rule module or writer explanation. Pass
two runs only for nonempty warning lists, with `covered_by` deduplication. The
three fixed Hungarian prompts and output schemas are `reader-1`, `reader-2` and
`recheck`. Receipts are private; outputs are copied to `.school-notes/reader/`.

P3 writes one run report; relation routing precedes writer assignment. P4 invokes
the existing subject writer with `fix.txt`, the remaining closure capacity and a
saved pre-fix tree. Failed fixes restore that tree; a completed or rolled-back P4
can enter P6 directly when there is nothing to recheck. P5 judges only the closed
items, new hits and changed figures. It never starts another correction pass.
Open, disputed and owner items retain their chain and round metadata.

In chat, the first `finish` returns `state: review_items`, the assigned items and
`fix.txt`; P4 stays `correcting`. The existing session writes its fix and closure
result, and the next `finish` applies the same result, scope, path and content gates
before P5. The saved handoff and check budget survive restart/fetch without erasing
the result. No second writer container is launched. A busy writer home in cron
still leaves the items open through the existing rollback fallback.

Reader keys omit machine content and insertion markers. Figure keys keep the 2a
contract. G4/G5 recompute keys on the final tree, remove stale verdict records and
refresh fixed pending notices without an LLM or a publication hold. The final
commit carries `School-Notes-Run`. Pending figures restore into subject-scoped
fetch inputs; after three runs they become owner items. Unit 5 starts a daily fix run without new sources when writer items or pending figures remain.

`[limits] max_agents = 3` is a positive integer, pinned for a run. Process-safe
admission uses global slots and an exclusive lock per learner/home volume.
Reader and figure review share the reviewer home and run sequentially. There is
no parallel Claude experiment or B-mode activation here. Container names contain
the learner, run, role, unit and attempt; stale cleanup uses only that exact name.
The new tests cover the shared behavior of all configured learners, physical
blind inputs, interruption at each phase, bounded retries, rollback, disputes,
admission and hash invalidation after a real local rebase.

Unit 2a review repairs: P1 validates candidates, crop bounds, marker placement and
notebook-drawing assignments. Figure IDs cannot overwrite another commission's
history. Section keys exclude other images and machine blocks, including at shared
uses; finalization prunes deleted figures without stale-verdict noise. The writer
copies generated publication-preview bytes into `wiki/assets/` before handing off
its candidate; the tool inserts only the independently accepted version. The old
`images.accept` module and generation-only cron path are removed. Paid generation
requires a valid commission/marker and retains existing cost/attempt limits.
The B-mode `figure.txt` remains deferred to implementation step 13/8.
Deploy with no open notes tasks: numeric Mermaid candidates and saved review
inputs from the earlier contract must not resume under the new schema. Existing
committed evidence stays private history; obsolete verdict keys become invalid
through the normal final-key check, without a model call or publication hold.

The real SVG/Mermaid rasterizer tests run with `npm test` in `packages/study-site`.
Set `CHROMIUM_EXECUTABLE` to the installed Chromium path if needed (default:
`/usr/bin/chromium`). They require a host on which Chromium can launch; they are
not silently skipped in a restricted sandbox. Python tests use a fake `node`
executable to verify argument, output and failure handling without Chromium.

Unit 2b review repairs: chat check failures start a new attempt with mandatory
content checks. The commit race snapshot precedes review; inserted figure blocks
normalize to their original markers. Rollback reports its reason and preserves the
rejected edits and binary patch in the task folder. Chat P4 restores the original
range-local result before a later retry. Conflict resolution runs the path guard
before regeneration. Reader inputs label assigned/context pages; extra page verdicts
are ignored. Context findings carry `outside_assignment`; `unlocated` records a
missing quote. Unknown finding paths become private owner notes without a retry.
Format retries explicitly read their error file. P1 checks inherited commissions
that were valid at the run's base; P2 isolates pre-existing damage as failed.
Unchanged page and figure keys reuse their
receipts across attempts. Regression tests cover chat handoff, rollback, receipt
interruption, figure insertion, G4/G5 retries and pending-figure damage.

## Operational rounds (unit 3)

`school-notes round` takes the VM flock (`state/operations/vm/lock`), visits `[students]` in
TOML table order, runs due nightly reviews first, then notes runs. `nightly_after`
defaults to `03:15` Budapest time. Open nights resume; timed-out nights wait until
the next date. A round crossing an hourly boundary starts one immediate successor;
each successor makes the same decision, without collecting missed-hour jobs.
The single cron job replaces the previous per-learner jobs. Direct run/nightly,
repair, chat, host fetch/finish and owner clear share the same VM admission.
Manual commands, chat, host fetch/finish and clear return 75 with a Hungarian
stderr message if the VM lock is busy; cron round returns 0 without waiting.
A failing learner step is logged and mailed daily; later learners still run.
An empty successful night also consumes today's review slot. Finishing an older
night does not consume today’s new review.
The lock is inherited by detached MCP jobs and is never forcibly broken. A busy
lock older than twelve hours triggers the existing daily notification path.

Weekly quota probes use the role's home in a short container without a model call:
Codex app-server JSON-RPC and Claude OAuth usage. Only the weekly window counts.
The cache is shared by harness family for one round. Unknown usage (including 401)
permits the call, logs the failure and mails daily; known remaining usage at or
below 2% pauses in `waiting_quota`. `run/nightly --manual`, chat, host fetch/finish
and CLI repair bypass only this pre-call gate. Recognized harness quota error
events still pause manual runs. Interactive waits name `school-notes chat` as
the continuation command and do not promise automatic resumption. No credentials
or provider error bodies leave the helper. Claude sends `claude-code/<version>`
using the image's build-time `CLAUDE_CODE_VERSION` (or `unknown` when absent),
without invoking the CLI; it never refreshes tokens. `status`
reads persisted observations and the last known value without probing.

T-125 counters are separate from bad-work strikes, persist per learner/role, and
reset on a successful role call. Reader passes/recheck share the reader counter;
fix calls share the writer counter. A second timeout suspends that role. Writer
work awaits owner action, while missing reader/figure verdicts use the existing
pending fallback. Clear after adjusting the configured role timeout with
`status --clear <learner> writer|reader|figure-review|figure|reviewer --continue`.
Explicit `[roles.reader]` and `[roles.figure-review]` override the corresponding
role's model/harness/timeout; absent these, the existing fixed stage defaults apply.
The reader's list and recheck calls use `list_timeout_s` (600) and
`recheck_timeout_s` (1200), independently of its first-call `timeout_s` (1800).
P4 still rolls a timed-out correction back (5.6); the second consecutive timeout
also stops the parent run (6.6). Quota waits preserve the correction and do not use
its crash retry budget.

Unit 5 replaces the original capped nightly range with topic calls, while retaining
this scheduler, quota gate and timeout policy.

Processing invocations accumulate active elapsed time (quota-wait hours do not
count). Work over ten minutes gets a private summary through the durable notice
queue, including available per-topic review/figure outcomes, pending indicators,
timeouts, quota observations, owner notes and transcript metrics. Nights report
even empty ranges. The email renderer preserves the full summary instead of the
previous 500-character truncation. Summaries are sent once per terminal state
(done, owner intervention or closure). Quota waits and retry invocations only
accumulate elapsed time; they send no summary. The VM verification/deployment,
T-144 owner gate and cron installation are outside this repository change.

## Closure and export (unit 4)

`wiki/rights.py` validates output hashes for `render.json` and generation receipts;
`public.py` only inherits rights for unchanged bytes. Generation records under
`docs/evidence/image-generation/` are written by the host and cannot collide with
accepted figure identities. A licensed image always revalidates its grant.
`figures/requests.py` and `figures/licenses.py` own the private request/license
contracts; `flows/licensing.py` files requests through the existing tool-write
journal before inspection. Source image hashes are distinct from the uploaded
material's hash; extracted figures resolve to their package's `document.md` mapping.
The same declaration record supports pre-recorded permission without an owner question.
The normal figure commission supplies the learning text and candidate; the tool never
invents an alt or caption while resolving a license. Keep the request marker until
independent acceptance inserts the credited image. Both records enter the existing
Git commit inventory; only the owner's interactive session may edit licenses.

`wiki/banners.py` maintains lesson header references, and the reader key includes
the referenced banner's bytes. `wiki/footnotes.py` adds non-blocking mixed-footnote
warnings to the usual check and reviewer handoff. `sourceNote` uses the initialized
PROFILE's explicit Student first name; the uninitialized template stays untouched.
No new phase, model call or publishing switch is introduced.

Run the JS export tests with `node test/learning-export.test.mjs` in `packages/study-site`.
Set `STUDY_BROWSER` to the installed Chromium executable for both synthetic learners'
actual HTML/PDF/site-file negative tests; without it those two browser builds skip.

## Topic-based nightly review and daily fixes (unit 5)

The night pins `claude-reviewed..H`, derives topic units from actual author changes
and unanswered review closures, and calls the reviewer once per topic in path order.
D60's `review_max_images` and `review_max_diff_kb` configuration keys are removed;
remove them from installed configuration before upgrading. The reviewer timeout
defaults to 5400 seconds; explicit configuration still wins. Fix-only topic ranges
use the literal targeted-review prompt; any ordinary author commit selects full review.
Per-topic receipts recover valid output after a crash and skip completed calls after
quota suspension. Format and crash retries are bounded independently; timeout has
no immediate retry. The configured `claude-review` template leaves native Agent/Task
tools enabled, without MCP; the real VM confirmation remains the deployment test.

`docs/review/nightly-state.json` carries each completed topic's own reviewed commit,
blocked topics with their original range start, and consecutive failed-night counts.
A timeout/failure ends that topic's work for this night; other topics continue. Two
consecutive failed nights block only that topic. `status --clear <learner> reviewer
--continue` clears the timeout counters and records a local unblock timestamp; the
next report persists the removal. The global marker advances exactly to H only when
all topics are complete. One report commit contains topic sections, closure replies,
hash-bound page/figure verdicts, warning decisions and recomputed pending notices.
Concurrent changes invalidate H-bound verdicts, without overwriting a newer valid one.

A quota suspension is a continuation of the same night: successful results remain
in durable task receipts and the report commits once the invocation can finish.
Timeout nights commit partial results and `done_topics` immediately. This preserves
one report commit per night and append-only pushed history; publishing a quota-time
partial commit and later extending it would require another commit or history rewriting.
An abrupt process crash likewise resumes from receipts before committing its report.

Unreviewed embedded figures use the existing independent figure reviewer, including
phone rendering, with four figures per topic call. Legacy image identity markers exist
only in a private review view. Receipts bind the original image/context fingerprint;
the source page and asset are not rewritten. Existing valid figure verdicts skip the
call. Missing/rejected figure checks remain visible as review findings and pending
notices. Nightly never generates an image or runs an LLM during publication.

A source-free daily `fix` run follows new Drive packages and precedes the one-time
repair queue. It assigns open/round-2 items and eligible pending figures, uses P1 in
fix mode, only figure checks in P2/P3, then P6. No reader call or second correction
pass is introduced. Every new finding is located at H; Git blame determines whether
its quote was last changed by a fix commit, in full and targeted mode alike. Such a
finding, or `not-ok` on a fix commit's `fixed` closure, goes to owner with chain 1.
`keep` reopens the existing disagreement at round 2. Successful P5 fixed verdicts
are now persisted as well, so nightly does not judge the same closure twice.

The upgrade tests retain legacy saved-report closure recovery. New fake-harness tests
cover preparation, valid-output recovery, missing-topic continuation, failed-topic
blocking/clearing, exact accounting, a report push interrupted before its checkpoint,
targeted mode, blame routing, daily fix admission and legacy figure inspection.
