# school-notes2 – map

The host-side tool of School Notes v2 (plan: `school-notes-ops/docs/v2/2026-10-02-school-notes-v2-terv.md`).
It does every mechanical step; the LLM runs in a container and asks for mechanical work only through MCP.

## Commands (local pipeline, `school-notes-ops/docs/v2/helyi/terv-helyi-pipeline.md` 3.2)

`~/.local/bin/sn` runs `school-notes` from a tagged release worktree. The command line knows only these;
each is one module under `local/`, thin over the library. The VM flows below remain in the package until
the clean-up step (plan 7, step 4) but have no command any more.

| Command | What it does | Code |
|---|---|---|
| `sn fetch <t> [--apply]` | Drive inbox list; `--apply`: download → place in the working copy → move on Drive → delete the download; resumable | `local/fetch.py` |
| `sn book <t> <subject> <code> [<source>] [--offset N]` | a converted textbook into `references/`, README table, map | `local/book.py` |
| `sn check <t> <page…>` | page check, read-only (`check_files(fix=False)`) | `local/check.py` |
| `sn gen <t> <id> [--note f]`, `--settle`, `--grant` | one paid image generation through the host ledger | `local/gen.py` |
| `sn close <t> --subject s --snapshot [--only id,…]` | before the reviewer (and before the confirmation pass for the named figures): `keys.json` (the verdict key of each figure's content now) and `diff.patch` into the hand-over folder | `local/close.py` |
| `sn close <t> [--subject a,b] [--check]` | hand-overs in `.school-notes/out/<subject>/` → STOP (exit 2) when an accept does not match its snapshot key, a `replaces` differs from the commission or an inserted figure vanished → insertion, renewals, machine blocks, STOP on invalidated verdicts, indexes, `public.json`, content check; never deletes a figure verdict | `local/close.py` |
| `sn done <t>` | is the content finished (exit 0/1) | `local/done.py` |
| `sn publish <t> [--reviewed] [--build-only DIR]` | clean tree + `sn done` 0 → push main → build → public gate → gh-pages → live check | `local/publish.py` |

Keys come only from `school-notes-ops/.env` at run time (`local/keys.py`); git runs over HTTPS with `gh`'s
token in git's environment (`git/run.py` `HttpsToken`); each command writes one line to `logs/school-notes.log`.

## Folders

| Folder | Responsibility |
|---|---|
| `config.py` | reads and validates `~/.config/school-notes/config.toml` |
| `state/` | `phase.json` (task folder), the per-learner lock, error classes, atomic writes |
| `log/`, `notify/` | JSONL log; e-mail through `msmtp`, one sentence per success or unresolved error |
| `git/` | the only Git caller (`run.py`), bare clones, work branch, `finish` G0–G9, conflicts, discard |
| `drive/` | listing, readiness, download, move (built on `tools/drive_media.py`) |
| `sources/` | order, photo and PDF preparation, hashes, duplicates, batching |
| `wiki/` | path guard, `check`, machine frontmatter, indexes, `public.json`, migration |
| `review/`, `evidence/` | nightly review (range, input, closing), review files, evidence records |
| `images/` | wrapper of `tools/learning_image.py`: monthly budget, lock, generation, acceptance |
| `site/` | public build from a commit (`study-site`) and the `gh-pages` release |
| `llm/` | the `podman run` argv, role templates (`templates.toml`), fixed prompts, output |
| `container/` | `Containerfile`, entrypoint, firewall, preflight |
| `mcp/` | the MCP server on a unix socket, background jobs, `redact()` |
| `flows/` | wiring per entry point; one error policy (`policy.py`) |
| `ops/` | `install.sh <tag>`, crontab, logrotate and configuration examples |
| `schemas/` | the schema of every JSON contract |

## 2.6.0 KISS (fix-46): the current contract

This section is authoritative; where an older unit section below says otherwise, this wins.

* **Finished notes work is never discarded.** No set-aside, bundle-and-reset or round
  rollback exists. A program error stops the task with its worktree for the owner; the
  next release lifts that stop (`needs_owner.release`). A run-level bad result stops the
  same way, with the work kept. Legacy `set-aside.json` rows, `rollback.json` receipts and
  round folders are ignored; such tasks simply continue.
* **One counter per writer call** (`flows/correction_calls.py`, `call-<k>/call.json`). After
  a failure the writer continues once on its own files with the error list. Only output
  still unusable at the last attempt (invalid `result.json`, a secret, unprocessable
  metadata or block markers: `kind: blocking`) is undone from the call's pre-call bytes.
  Otherwise the call's files and valid result are kept and remaining errors become items.
  A fix call that failed twice, timed out or asked a question leaves its items open; the
  run goes on. A package call that failed twice stops for the owner with its files kept.
  The two-timeout role brake and the quota wait are unchanged.
* **Errors vs. warnings** (`wiki/check.py`). Errors: secrets, conflict markers, tool block
  markers, frontmatter YAML and metadata the tool must process, broken links/anchors,
  math delimiters, local image/embedding rules, render receipts, required frontmatter
  fields, public.json rights, the path guard. Everything else is a warning that needs no
  decision: typography, page size, lesson-log form, material names, question form, file
  names, tags, order, banner presence, infographic decisions, closure accounting, pending
  figure candidates. `machine_paths` are judged only by the public output gate. An error
  that already existed in the base is a non-blocking warning (exact file+message match);
  the tool never turns it into an item. Unreadable base frontmatter is the only old
  error that stops (the generators cannot read the page).
* **Mechanical restore, not failure** (`flows/protected.py`). Edited machine keys and blocks
  come back from the tool's own last write; in cron the base's `decisions` come back. A
  removed block is the writer's choice; tool blocks are placed at the fixed place right
  after the frontmatter (or where the writer left the block). A page may be deleted or
  renamed; links to it are checked. Writer-drawn SVG and inline Mermaid need no
  commission; a raster image keeps the commission and rights gate.
* **One pass per run.** Phases: `figures` (P2) → `inspecting` → `review_ready` → `finishing`.
  Package and chat runs: the reader (P3) reads only changed pages without a current
  verdict; the rest of the topic is context, its findings are owner notes. Fix runs and
  resumed 2.5.x correction tasks (`recheck_all`): one recheck (P5) of every author-changed
  page against the run base. The reviewer names file and line; the tool only validates the
  line. A `hiba` on a changed line is an item (`chain` +1, deeper than three: owner);
  everything else is an owner note. A `fixed` closure without a text change, an invalid
  closure or an empty disagreement leaves the item open.
* **Finish.** Remaining content errors after the writer's calls become items; the commit
  goes ahead. A G5 build failure on content records items and holds the publication; the
  notes commit is still pushed (no new attempt, no reread, no attribution). `publish`
  remembers a held commit and does not rebuild it.
* **Brakes by time and real attempts.** An assigned item or figure without progress in a fix
  run is parked for 24 hours (`state/<learner>/parked.json`), nothing else. Only `fixed`/
  `disagree` closures count as repair attempts (three → owner, including P5 `not-ok`). A
  pending figure exhausted after three runs is reported by status and mail, not by an item.
  Pending figures get their own fix calls, after the text work. A pending bookkeeping
  migration alone starts no run.
* **Nightly review from the diff** (`review/nightly.py`, `flows/nightly.py`). The reviewer gets
  `git diff <claude-reviewed>..<main> -- wiki/`, the commit list with run kinds, the writer's
  `review_requests` (carried unchanged in `School-Notes-Review-Request:` commit trailers),
  the closures without an independent verdict and the changed sources; the worktree at H is
  read-only. It decides what to check. Only a `hiba` on an added author line of the diff
  (not inside a tool block) becomes an item; every other finding is an owner note. An empty
  wiki diff makes no call. A legacy topic review task is closed unapplied; the marker did
  not move, so the diff review covers its range.
* **Removed:** source-reference/footnote scanners, reader pass two and warning verdicts, the
  quote-based finding routing and tool-literal classification, the 30% infographic rule,
  the browser-defect excusing regex and target copying, banner-dependency routing, the MCP
  check limit and warning accounting, order checks, nightly topic planning, nightly figure
  review and its retry markers, round identities and the writer-output identity counters.

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
Source-free hourly fixes use `fix.txt`; nightly review uses a separate topic contract
with exact page, closure and warning accounting and private `owner_notes`.
Writer `owner_notes` are emitted as `writer.owner_notes` JSONL log events and, at completion,
in the private task `report.json` and finish response, with token-like secrets redacted.
They never enter e-mail; only the short operational status is mailed.
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

Warning lists, source-reference scanning, the MCP check limit and inherited-error items are gone (see
*2.6.0 KISS*). MCP check returns errors first, full counts, `truncated` and the full-list path.

Review metadata is additive `item_details`, keeping old `items: {R1: status}` maps readable.
Legacy headings supply the page when metadata is absent. Full keys avoid cross-report R1
collisions. Question/decision references are page-local; asset findings also use the
questions and decisions of their embedding pages, excluding links in code blocks.
Existing question/open-item and disagreement references go to the pending section,
decisions to owner, unknown references
to unlocated. A decision reference without new evidence is invalid reviewer output.
The tool inherits the related item's chain and automatic repair count. Chain 1 stays
open; a real decision, a third unsuccessful automatic repair, or an unbound P5 chain deeper than three goes to owner. Owner-item notifications pass through the common mail gate and
are logged as `notify.suppressed`; their state remains visible in `status`.
The durable handoff completes after suppression, including across closing restarts.
Invalid or stale responses are dropped and logged. Completion mail enters the private
per-learner `pending-owner-notices.json` before delivery. Every `run` retries that
queue, even after the originating task has completed; receipts prevent duplicate mail.
Legacy queued non-completion notices are suppressed and removed on retry. Old JSON
summaries are rebuilt from task metadata; if that metadata is gone, suppression is
logged and the unsafe message is removed.
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
review/image assignments. The tool assigns all repair items in calls of at most 30, keeping each page together where possible, in round-2,
report-date and numeric item order. Unassigned items do not accrue untouched counts.
Interactive preparation puts owner items first, so the owner
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
The scheduler reads the queue in its stored order after new packages and hourly fix work
(including eligible pending figures).
Runs change status without rebuilding or reordering the queue. A direct topic repair
without a queue is allowed, but does not create one or complete absent entries.

Two bad fix/repair outputs use the same archival path as a tool failure: a local Git
bundle and `state/<learner>/set-aside.json` retain the work keys, release and reason.
The same work cannot restart on that release, including a repeated explicit repair;
other work continues. One completion notice says the run was set aside for controller
inspection, never that the notes are ready. Package runs still stop for the owner.
Pre-upgrade owner-queue handoffs remain resumable. No new phase or model is introduced.

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
commission is no longer eligible, except while a generated candidate awaits judgement
(`review_pending`): its free check remains eligible. The 2b orchestrator creates/notifies the owner item and the learner-facing pending notice. No owner wording is invented here.

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

P3/P5, the correction rounds, rollbacks and the chat handoff described in older versions are
replaced by the one-pass contract in *2.6.0 KISS*.

Reader keys omit machine content and insertion markers. Figure keys keep the 2a
contract. G4/G5 recompute keys on the final tree, remove stale verdict records and
refresh fixed pending notices without an LLM or a publication hold. The final
commit carries `School-Notes-Run`. Pending figures restore into subject-scoped
fetch inputs; after three runs they become owner items. The scheduler starts an hourly fix run without new sources when writer items or pending figures remain.

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
TOML table order, runs notes first, then due nightly reviews only when no immediate learner work remains
or 06:00 has passed since the due time. Successful publication immediately repeats the
cycle; errors, owner stops and archived runs do not. `nightly_after`
defaults to `03:15` Budapest time. Open nights resume; timed-out nights wait until
the next date. A round crossing an hourly boundary starts one immediate successor;
each successor makes the same decision, without collecting missed-hour jobs.
The single cron job replaces the previous per-learner jobs. Direct run/nightly,
repair, chat, host fetch/finish and owner clear share the same VM admission.
Manual commands, chat, host fetch/finish and clear return 75 with a Hungarian
stderr message if the VM lock is busy; cron round returns 0 without waiting.
A failing learner step is logged; later learners still run.
An empty successful night also consumes today's review slot. Finishing an older
night does not consume today’s new review.
The lock is inherited by detached MCP jobs and is never forcibly broken. A busy
lock older than twelve hours records one VM-wide incident, visible for every learner.

Weekly quota probes use the role's home in a short container without a model call:
Codex app-server JSON-RPC and Claude OAuth usage. Only the weekly window counts.
The cache is shared by harness family for one round. Unknown usage (including 401)
permits the call and logs the failure; known remaining usage at or
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
fix calls share the writer counter. A second timeout suspends that role and stops
the run for the owner – also for the reader, recheck and figure-review roles
(2.6.1: a run without its checks could only hold its release). One mail names the
role. Clear after adjusting the configured role timeout with
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

Processing invocations accumulate active elapsed time; idle hours are excluded. A
successful notes run or nonempty nightly review sends one Hungarian sentence with
start/end time and work minutes; after continuation it describes the resumed segment.
Stops send one immediate content-free sentence stating that work stopped, why, and who acts.
Transient errors stop on the third consecutive failure, bad writer output on the second;
intermediate retries send no mail. Taskless failures keep per-operation retry counters.
Timeout mail opens one incident per learner/role upon suspension, never per topic.
A successful role call closes it only when no unit of that role remains suspended;
a successfully completed run also closes its remaining incidents and sends completion mail.
`state/<learner>/incidents.json` keeps the unresolved error's durable identity; repeated
rounds and the terminal report do not repeat it. Identity uses scope, class and the safe
Hungarian sentence's meaning, ignoring changing measurements, never raw exception text.
Recovery closes the identity, so a
new failure can mail again. Pre-task errors and publish-task errors use the same path.
`pending-owner-notices.json` and `notify-once.json` recover interrupted delivery. As
with any SMTP handoff, a crash after server acceptance but before the local receipt
can repeat delivery; the tool cannot atomically commit a receipt at the mail server.
Item, image, license and quota notices remain suppressed. Discard sends its own one-sentence outcome: its work was not published, and the
archive bundle name is included when one exists. A closed night awaiting retry says
“éjszaka újrapróbálja”. A saved clear outcome recovers delivery after a crash. Free-form questions are never assumed content-free: only approved safe
operational sentences are quoted, otherwise the mail refers to the private session.

`school-notes status` shows current work, today's runs, unresolved failures and
responsibility, queue sizes and the remaining monthly image budget in Hungarian.
`--details` keeps the full former view; `--json` keeps the structured details. Every
completed round atomically saves the short view to `state/allapot.txt`, with a `Készült:` timestamp. A broken learner
state is reported without hiding the other learners. Installation takes the VM lock
before learner locks and retains them through the atomic release switch. Before waiting
it atomically writes `state/operations/install-pending` with its PID and start time;
round logs and releases its lock while that installer is alive and the flag is at most
two hours old. A dead installer, older flag or unreadable legacy flag is logged and
removed before the round continues, with one VM incident mail and a durable last-error
record. Installers serialize, write lock-holder metadata, and remove the flag after
switching (or on a handled failure).
Review inventory parses each report once; nightly closure batches changes by report,
using `CSafeLoader` when available. Machine-only changes without items or hits do not
start recheck. `review.finalize`, `review.final_keys`, `review.close` and
`review.topic_input` log durations, including failed invocations. Repair's link-only
comparison ignores separator differences only at removed/generated notice positions;
it still compares against the current upstream after rebase and protects all prose.
No new phase or model call is introduced.
The VM verification/deployment,
T-144 owner gate and cron installation are outside this repository change.

## Closure and export (unit 4)

`wiki/rights.py` validates output hashes for `render.json` and generation receipts;
`public.py` only inherits rights for unchanged bytes. Generation records under
`docs/evidence/image-generation/` are copied from the host ledger in the main content flow and cannot collide with
accepted figure identities. A request-based licensed image always revalidates its grant; hash-matching legacy licensed rights survive without a request record.
An independently accepted `figure.json` also grants `authored` rights for its exact
`output_sha256` only for a non-generated, non-licensed SVG whose source is the asset
itself or a byte-identical SVG under `wiki/assets/`. Raster authorship still requires
`render.json`. Insertion's rights field documents the decision; the shared eligibility
function and hash checks decide rights even for older records without that field.
Candidate preflight rejects missing rights paths before independent review, using
render outputs, generation receipts (including the host ledger), licensed requests
or that own-SVG rule.
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
They use the sibling `school-notes2/.venv/bin/python` (or `SCHOOL_NOTES_PYTHON`) to
feed the real `public.build` manifest into the renderer.
Set `STUDY_BROWSER` to the installed Chromium executable for both synthetic learners'
actual HTML/PDF/site-file negative tests; without it those two browser builds skip.

## Topic-based nightly review and hourly fixes (unit 5)

The topic-based nightly review is replaced by the diff-based review in *2.6.0 KISS*.

A source-free `fix` run follows new Drive packages and precedes the one-time repair
queue on each hourly round, with no daily cap. It assigns every open error in deterministic
page groups of at most 30 items per writer call. All assignable pending figures go to the
first call, before text repairs; paid generation still obeys its existing budget. Saved
call results survive restart. Scope restoration rejects only links whose target page or
section is missing afterwards, using the site's renderer for section IDs. In split fix
and P4 writers this check runs inside each call's bounded retry; a failed call cannot
roll back earlier calls. A dependency found at P4's final gate returns to the affected
call without restoring the whole phase. A common targeted recheck (P5) and one finish chain follow
all writer calls; up to three correction/recheck rounds run immediately. A zero-progress
run records only actually assigned work keys and the release under `state/<learner>/set-aside.json`; new work
and a new release can run. The stop sends one tool-error incident, appears in status, and the completion mail says that no progress was made. Completed tasks are never archived by this brake.
Chat and repair P4 stay within their own assignments and run report; package and fix P4 include the backlog.
New unbound P5 errors inherit the repaired page/item's chain depth plus one (the maximum source depth when ambiguous); depth above three requires the owner without spending another item's repair attempts.
Round identities include both attempt and round (`-fix-a{attempt}-r{n}`); P1 fix always uses round one.
Transient task retries wait at least 30 minutes, so three failed attempts span at least one hour. A transient owner stop permits one automatic probe in each following clock hour. Monthly-budget and unknown-call waits do not set this brake. Three failed automatic repairs still escalate to the owner.
Package writers receive no old review items.
Nightly calls are full reviews only, triggered exclusively by author changes in `run`
or `chat` commits. For `run`, the `School-Notes-Material` trailer limits selection to
P1–P2 material; old pages fixed by P4 are excluded. Fix, repair, migration, tool and shared-rule commits cause no nightly
call. Reader recheck retains its narrow repair scope. Legacy targeted receipts remain
readable. New suggestions (`severity: javaslat`) go to the run report’s `owner_notes` section;
only new `hiba` findings enter review queues. Existing backlog items are never reclassified.
There is no suggestion migration or new learner file. Status separately reports automatic
processing completion and readiness for learning.
The legacy `fix_runs_per_day` and `review_closures_per_run` configuration keys remain
readable for upgrades, but do not cap repair work.
The fix scope uses the pre-edit unit, including related
lessons, summaries and image embedding pages. Textbook inputs contain printed-page
excerpts selected through the book index; ambiguous or unavailable references are
explicitly marked. `keep` reopens the existing disagreement at round 2. Successful P5
fixed verdicts are now persisted as well, so nightly does not judge the same closure
twice.

The upgrade tests retain legacy saved-report closure recovery. New fake-harness tests
cover preparation, valid-output recovery, missing-topic continuation, failed-topic
blocking/clearing, exact accounting, a report push interrupted before its checkpoint,
new-material admission, blame routing, zero-progress fix admission and legacy figure inspection.

The pending-figure migration (units 21–25) runs after installing 2.4.0, with
no open notes tasks. Use the tool user's configured learner names, not worktree paths:

```sh
/srv/school-notes/current/packages/school-notes2/.venv/bin/python -m school_notes2.figures.migrate_pending --config "$HOME/.config/school-notes/config.toml" <learner> --dry-run
/srv/school-notes/current/packages/school-notes2/.venv/bin/python -m school_notes2.figures.migrate_pending --config "$HOME/.config/school-notes/config.toml" <learner> --push
```

Dry-run reads the local snapshot without fetching, switching, logging or creating
state/lock files; it lists the snapshot commit and the absolute host receipt directory.
Tracked changes (including staged changes) or untracked files cause exit 2, with every
path listed and no writes. Each planned pending entry lists its ID, kind, exact image
job ID (or null for a drawn figure), used paid attempts, post-migration eligibility,
owner status and whether an existing candidate can be checked for free. Eligibility
here is before the ordinary monthly budget check. Missing-page entries stay
unassignable. Job identity is exactly `<learner>-<commission-id>`: a v1 job called
`learner-topic-banner` does not match a v2 commission `topic-header`; the latter
uses `learner-topic-header`. No alias or cost reset is inferred from similar names.
Real execution takes the learner
lock, refuses open notes runs, fetches main and switches the configured notes worktree
to detached origin/main with discarded tracked changes. Untracked files must be clean.
The migration resets pending counters, restores the latest clean historical defects,
lists missing-page commissions without modifying them, and lists IDs with and without
clean history. Poisoned defects without history are cleared. Pending banners and
infographics switch to `image` markers; existing headers without generation proof
receive replacement commissions with reason `c`, retaining the old image until acceptance.
Hash-matching `generated` public-manifest entries and v1 compression receipts linked
to proven generated originals preserve already accepted WebP headers.

The tool rebuilds `public.json` and commits with `School-Notes-Run: fix`. `--push`
uses the configured deploy key and checks `ls-remote`. Without `--push`, the commit
stays local; repeat with `--push` to publish it. Neither mode generates images.
The hash-only migration receipt and the operation journal live in `state/<learner>/`;
the latter saves the commit before publishing. Repeating after a crash resumes the
same transaction, including after a successful push whose verification was interrupted.
The repository flag `docs/figure-pending-migrations.json` prevents another counter
reset even when the host receipt is lost. If migration inputs changed before commit,
preserve and inspect the changes, remove the two host receipts named in the error,
and rerun dry-run followed by the migration command. The same recovery applies when
main moved after the local commit: preserve that commit and later changes first, then
remove the two host receipts whose absolute paths the error names and rerun. The tool
never force-pushes it.

Until `docs/figure-pending-migrations.json` exists, a nonempty pending queue is frozen:
notes (package, fix and repair-queue runs) and nightly review do not assign its figures,
count attempts, escalate owners or create related review items; its bytes stay intact.
Other work proceeds. A log event and a suppressed `send_once` notice record the missing
migration. An initially empty queue gets a `pending_format` marker before its first
current-format record; this does not claim that the legacy-header migration ran.
New failed commissions and nightly retry requests dropped during this window log
`figure.migration_dropped` with the commission ID.

Rollback to 2.3.7 also requires restoring each learner repository's compatible
pre-migration pending records and page markers in a new commit (keep pushed history).
Stop scheduling and finish/discard open runs first; preserve later learner work and
the host receipts before restoring the old release. Merely changing the release
symlink leaves `runs: 0` records that 2.3.7 cannot read.

Every pending figure with remaining attempts is assigned, across all subjects.
There is no image capacity reservation or daily admission limit; generation enforces
the monthly budget.
New content precedes replacements regardless of their IDs. An exhausted paid job
is excluded and marked `owner_required` when no generated candidate awaits review
(including a rejected or lost last attempt), with an owner record and suppressed notification;
if no writer work remains, a tool-only fix persists that flag without an LLM call.
An unreviewed generated candidate is eligible for free retrieval and independent
rechecking even at the paid limit or with no remaining budget; no generator call is
made. Hash-bound independent `repair`/`reject` verdicts update the matching ledger
attempt without changing its cost. `review_pending` defers run-count escalation until
that candidate has a verdict, including after an interrupted third run.
Free rechecking is limited to two assignments per commission; exhaustion requires
an owner decision with a suppressed notification. `state/<learner>/figure-rechecks.json` records
assignment run IDs before writer input is handed over. Resumes and ranges of the
same assignment share a receipt; P4 uses its child run ID. Worktree rollback cannot
reset this limit. These receipts do not consume paid generation attempts.
After a rejected or lost last paid attempt, a changed image plan opens a linked
`variants` record (`<job-id>~2`, and so on) inside the same logical ledger entry.
Attempt numbers and the three-paid-attempt limit stay shared across variants and
job-ID aliases for `learner:target:role`. Accepted or unreviewed candidates refuse
plan changes before the saved plan or preview is replaced. Existing rejected jobs
need no migration; reservation and variant metadata are saved atomically before
the provider call. A resumed generated variant reuses its preview without spending.
A generated figure counts a run only with a candidate or a paid host-ledger attempt
for the same learner/plan since the serialized run's creation. Budget refusals consume
no attempt. P4 assignments and attempt decisions are checkpointed before continuation.
The mandatory generated-header gate covers touched topics, chapter summaries and
subject indexes; unassigned and exhausted pending header markers remain valid.

The real-gap notice policy shows pending figures and drafts. A page-review notice
applies only to a never-reviewed reader page (`topic`, `lesson-notes`, `summary`,
`review`) created by a v2 writer run. `docs/review/new-pages.json` records that origin;
Legacy, home, index and info pages never receive a page-review notice. Stale reader
verdicts retain a `reader-history` record (not a valid verdict).
`docs/review/notice-policy.json` marks a one-time whole-wiki refresh; local verdict history
recovers reviews deleted by older releases. The refresh only removes notices. Published
figures awaiting nightly review have no notice. Notice-only changes leave author keys and nightly scope unchanged; inherited
browser defects become durable warnings in `status`. Print chapters and PDFs omit
only notices marked by the tool.

The infographic decision contract is removed; an infographic is an optional commission.

Pre-task prerequisites, setup, round-step, report and prolonged-lock failures persist
in `state/<learner>/last-error.json` with a timestamp and one safe Hungarian sentence.
`status` shows the record and the common incident path mails it once; a successfully completed run clears it.
Nightly restores the caller’s logger even after interruption.

Automatic review repairs persist `repair_attempts` and sorted `repair_runs` per item.
A completed automatic fix assignment counts once, including an unchanged item or an
individually restored P4 call; resuming that assignment never adds another attempt.
A full-round rollback consumes no attempt. A third `fixed`
closure remains fixed unless a reader/nightly `not-ok` verdict rejects it. Related
findings inherit the consumed budget. Interactive closures do not consume it.
`category: forrásellentmondás` and confirmed-decision references go directly to owner;
item notifications stay suppressed, and status shows one owner-item count.

The journaled chain-policy migration runs before notes assignment. Legacy chain-1
owner items reopen with zero attempts except genuine decisions/tool defects; figure
owner records without a `repair_attempts` key settle with “elavult: az ábra elkészült
vagy újra sorban van” unless their pending commission currently requires its owner.
Completed figures no longer on the pending list also settle. Independent figure exhaustion stays under
the existing figure policy. `repair_policy` marks each migrated report, so replay or
rebase does not reset counters. A tool-only fix can persist migration without writer
work, and review metadata alone does not create a nightly topic.
