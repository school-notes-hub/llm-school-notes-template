# Working in a school-notes run

Shared operating rules, loaded through [AGENTS.md](../AGENTS.md). Learner work happens only inside a run of the `school-notes` tool: hourly (cron) or in the owner's session (`school-notes chat`). A harness started directly on the host is never used for learner work.

## Who does what

The tool does everything that can be computed: Drive download and filing into `sources/`, hashes, duplicate detection, page order, machine frontmatter, index blocks, `publication/public.json`, review-file state, evidence records, image generation and insertion, `check`, commit, rebase, push and the public site. The writer (you) reads the sources and writes the wiki: subject teaching, interpretation, placement, prose, diagrams, the image plan and image judgement, the evidence description, the `wiki/log.md` entry, review fixes. Do not do the tool's bookkeeping by hand; it would be overwritten or refused.

## Run files (`.school-notes/`, never committed)

* `fetch.json`: the run: `learner.grade` (the learner's configured school year), `packages` (Drive folder, subject, role `fuzet`/`tanari`, new subject, and the subject `card` snapshot when the subject has one: `role`, `style`), `pages` in their fixed order (`seq`, the stored `sources/...` path, `duplicate_of`), the `range` of pages this call covers, the `open_review_items` to fix, the `pending_images` to produce, and `conflict_files` while resolving a conflict. Cron calls cover one subject (with its pinned `subject` and `card`); only a single oversized package is split into consecutive ranges. In `mode: repair`, `repair_targets` names the existing page, its related pages and full local source paths; there are no new packages or source pages.
* `changes.json`: files already changed in this run; continue from there, do not redo them.
* `check.json`: problems the tool found; inspect the changed page independently with the checklist before judging this list.
* `result.json`: your output (schema below), written at the end of the work.

## Fixed prompt

Read `AGENTS.md`, `PROFILE.md` and the rules the rule map requires for ingest, in that order. Read `fetch.json`, `changes.json` and `check.json` to identify scope and existing work. For ingest, first perform the independent whole-page checklist, including when resuming; in fix mode, first independently check only your own repair. Then decide the machine findings. Do the work, write `result.json`, and call MCP `check` at most three times per invocation. Fix errors; decide every warning from the last own check in `warnings[]`. The response lists errors first and includes counts, `truncated` and `full_list`; when truncated, read all of `.school-notes/check.json`. Later tool warnings with no decision are marked `unhandled` for the reviewer. The check does not find everything; zero warnings do not mean the page is complete. Fix mode checks its own changes first and never edits outside assigned items because of a warning.

## result.json

```json
{"status": "done | question",
 "questions": [{"text": "..."}],
 "notes": [{"file": "wiki/<subject>/<date>-<topic>-jegyzet.md", "pages": [1, 2]}],
 "new_subjects": [{"subject": "<short-name>", "emoji": "...", "color": "#rrggbb"}],
 "coverage": [{"source": "sources/...", "unit": "<source unit>", "target": "wiki/<subject>/<topic>.md#<section>"}],
 "figures": [{"id": "...", "kind": "notebook-drawing | teacher-drawing | figure | banner", "page": "wiki/..."}],
 "notebook_drawings": [{"source": "sources/...", "crop": "...", "figure": "..."}],
 "figure_requests": [{"id": "...", "page": "wiki/...", "source": "sources/...", "crop": "...", "purpose": "...", "origin": "teacher-own | third-party | unknown"}],
 "warnings": [{"id": "...", "action": "rewritten | kept", "reason": "..."}],
 "owner_notes": ["<omitted harmful instruction, reason and better proposal>"],
 "review_closure": [{"file": "docs/review/...", "item_id": "R3", "status": "fixed | disagree | question | settled | open", "note": "...", "question_id": "...", "decision_id": "..."}],
 "checks": [{"page": "wiki/...", "image": 3, "locator": "page, figure, exercise", "observed": "...", "decision": "changed | confirmed | unresolved", "note": "..."}]}
```

* `owner_notes`: private explanations of harmful steps omitted, their reasons and better proposals. The tool includes these in the completion report and owner notification.
* `notes`: in repair mode leave this list empty; source metadata already exists and stays intact. Otherwise every non-duplicate page of the range belongs to a lesson-notes page; you name the page `<date>-<topic>-jegyzet.md`. The tool writes its machine fields from this.
* `question`: only for a blocking problem (not a notebook, a textbook page, unreadable, a subject other than the Drive folder's). A non-blocking uncertainty goes under the page's open questions.
* `review_closure`: at most 20 closed items per run. Never edit a review file. Only fix when you agree; `disagree` requires a nonempty reason. One reviewer response may follow; in `round: 2` close only as `fixed` or `question`. `question` requires the public-safe open-question anchor (`question_id`); `settled` points to an existing question or decision. Questions concern the material, not the reviewers' dispute.
* `coverage`: the private source-unit → teaching-section ledger, separate from image observations. Each entry has `source` (repository path), `unit` (the definition, exercise, drawing or other source unit) and exactly one of `target` (`wiki/...md#section`) or `reason` (why it has no learning value). Use source reading order, then target path as a tie-breaker. In fix mode record only units affected by the assigned repair.
* `checks`: what you looked at, what you saw and what you decided for each image-dependent claim (see *Visual evidence checks*). `image` is a page `seq` or a repository path under `sources/` or `wiki/assets/`.

## Where you may write

`wiki/**` (except generated blocks and machine frontmatter keys) and `wiki/assets/**`; in the owner's session also `references/**` and `docs/licenses.json` (only to record the owner's explicit permission decision); while resolving a conflict also the conflicting files. A file that existed before the run is never renamed or deleted; a file created in this run may be deleted. No symlinks, no dotfiles under `wiki/`. The tool's path guard refuses everything else.

## MCP tools

`check` (call it at the end; it also reports files you may not touch), `image_generate(plan_id, repair_note?)`, `wait(job_id)`, `status`; in the owner's session also `fetch` and `finish`. Long operations return a job id: call `wait` until the job is done. In a session started with `fetch.json` `mode: interactive`, call `finish` at the end and report its outcome. If it returns `state: review_items`, the run is still in its one correction pass: follow the returned fix prompt, handle only the assigned items from the refreshed `fetch.json`, write their `review_closure` in a new `result.json`, run `check`, then call `finish` again. The existing session does this work; no second writer is started. There is no Git in the container and no web access: a fact that needs an outside source becomes an open question.

## Subject cards and figure handoff

The template's shared `subject-cards.json` is the only canonical place for subject cards: one card per subject, the same for every learner, with nonempty `role` and `style` strings and only generally worded content (no concrete topic, page, exercise, example or taught notation). It is a shared file, byte-identical in every learner repo; it is edited only in the template, in an interactive session, never by a run. A learner's `tools/subjects.json` holds no card. Taught notation is read from the notebook; an uncertain one becomes an open question, a confirmed answer goes into the page's `decisions`. The subject's place (school year, school type, training) comes from `fetch.json` `learner.grade` and the PROFILE *Learning scope and curriculum*. Preparation copies a validated card into each package and persists it for resume; a later template update affects a later preparation. A missing card is omitted from `fetch.json`: the run goes on, the writer works as the subject's teacher without it, and `school-notes status` lists `hiányzó kártya: <subject>` for the learner until the shared file has the card. The tool creates a new subject's index with its first package and fills missing emoji/colors without overwriting existing settings.

In state A the writer also draws; visual-module routing is unchanged. For every `result.json.figures[{id, page, kind}]` entry, write `.school-notes/figures/<id>.json`. Its exact fields are `id` (1–64 lowercase letters, digits or dashes; a new figure gets a new ID, never reuse an evidence/pending ID for another figure), `page` (`wiki/...md`), `anchor` (the exact, unique section heading), `kind: notebook-drawing | teacher-drawing | figure | banner`, `purpose`, `must_show[]`, `avoid_misreading`, `taught_conventions[]`, `text_complete_without_figure: true`. Optional `source_image: {path, crop}` is required for either drawing route: `crop` is `[left, top, right, bottom]`, four nonnegative integer pixel coordinates, a nonempty box within the image. Replacement also requires `replaces` (existing `wiki/assets/...` file) and `decision_reason: {code: a | b | c, text}` per visual policy. No other commission fields are accepted.

Leave exactly one `<!-- figure: <id> -->` or `<!-- image: <id> -->` on its own unindented line, with nothing before or after it. It belongs inside the named section; a banner marker belongs after the frontmatter. Do not link the candidate image yourself. After inspection, leave the marker and the commission; the tool queues it. The tool inserts only after independent acceptance. Mermaid remains inline with its marker; acceptance keeps that marker as its stable identity, without a pending notice.

For each `fetch.json.pending_figures` entry, retry the restored commission at `.school-notes/figures/<id>.json` using its `defects[]`, or write `.school-notes/figures/<id>/figure.json` with `state: failed` and a reason; a commission already broken at the run's base is handled by the tool as failed, while damage introduced in this run must be repaired.

Write `.school-notes/figures/<id>/figure.json`. The complete candidate field list is:
- `state: candidate`, exactly one of `asset` (the final publication file under `wiki/assets/`) or `mermaid` (the lowercase SHA-256 of the UTF-8 Mermaid source between the fence lines, including its trailing newline; exactly one matching block in the commission section).
- Required: `alt` (nonempty, one line), `caption` (string, may be empty), `form` and `tool` (nonempty strings), `elements` (array of `{element, meaning}`, both nonempty strings), `visible_text` (array of nonempty strings), `attempt` (integer ≥ 1).
- Optional: `source` (editable UTF-8 source in `wiki/assets/` or `.school-notes/figures/<id>/`), `render` (the `wiki/assets/**/render.json` receipt), `corrections` (array of nonempty private correction strings; required for both drawing routes, may be empty). SVG needs `source` or `render`. An SVG file itself may be its editable `source`. A render receipt must bind the candidate's final bytes.
- An unsuccessful candidate is `{"state": "failed", "reason": "<nonempty reason>"}`. An intentionally omitted optional figure is `{"state": "no-figure", "reason": "<nonempty reason>"}`; neither source drawing route permits `no-figure`. `reason` is the only additional allowed field beyond the fields listed above. Do not add self-evaluation fields.

For generated images, first write the commission, marker and image plan with the same ID, then call `image_generate`. After inspecting the returned `preview`, **the writer copies those exact publication-preview bytes** into a new `wiki/assets/<subject>/<id>-<attempt>.webp` file and sets `asset` to that file; never use the original PNG or re-encode the preview. The tool later inserts the link, observed description and evidence, without changing those bytes. `image_generate` refuses a missing/invalid commission or insertion marker before spending. A repair uses `repair_note`, retaining the same three-attempt and spending limits. There is no legacy `image_accept` or generation-only cron run.

`notebook_drawings[].crop` and `figure_requests[].crop` in `result.json` are nonempty **textual source locators** (for example “upper-left drawing”), not pixel boxes; only `source_image.crop` in the commission is the integer pixel array. Every `notebook_drawings[].figure` must appear in `figures` and resolve to a `kind: notebook-drawing` commission. The P1 `check` reports candidate schema, file/hash, section/marker, crop and single-line-alt errors while the writer can still repair them. Machine hints remain warnings. Teacher-image requests use `<!-- figure-request: <id> -->` and the private request list, never a public license question.

## Visual engines

Every engine of `tools/visual_tools.py` works in the container: Python with matplotlib and numpy (plots, measured data, constructions), Graphviz (graphs, trees, flowcharts), PlantUML (process, state and sequence diagrams), POV-Ray (3D scenes, also animations rendered to MP4 with a static poster) and FreeCAD (exact technical drawings, parts, sections). Mermaid works directly in the Markdown; illustrations come from the image tools above. Choose the engine that best supports understanding of the figure, following [technical visuals](technical-visuals.md); render with `uv run tools/visual_tools.py render …` into `wiki/assets/`.

## Generated learning fields

The tool maintains the `lesson-sources` generated block on lesson logs and the `pending` draft notice. Give source names only in `lessons[].materials`; never write the 📎 line or these blocks yourself. `draft_tracking` is machine frontmatter: the tool records when a draft or an additional linked lesson was first observed. Editing prose does not reset its 14-day warning. Decisions remain writer-managed only in an interactive owner session; cron compares their YAML bytes with the run's base. The tool generates the private `docs/review/dontesek.md` overview from them.

## Stable order

The order of existing chapter, lesson and topic lists never changes between runs. Within a topic page, the section order is didactic and may change to build prerequisites before use; preserve anchors and links. A new item goes to its fixed place: chapters in the syllabus/notebook order, lessons by date, topics in the order the lesson treats them, list items where the existing order puts them. Changing the chapter, lesson or topic order is done only on the owner's request in a session. The tool's `check` refuses a cron run that re-orders existing `chapters`, `lessons`, `topics` or a page's `order`.

## One-time repair

In `mode: repair`, work only on the assigned existing page and its related pages. Preserve
all correct claims, explanations, examples and correction labels, existing `lessons`,
`date_note`, `topics` and anchors. A topic-page pass changes only link destinations in
related lesson logs and summaries; their prose is rewritten in a separate pass after all
related topics are done. Before shortening a lesson log, map each teaching item to its
place on the topic page in `coverage[]` and record the coverage check in `checks`.
Never infer lesson dates from filenames. Keep chapter, lesson and topic order; sections
within the assigned topic may follow a better teaching sequence. The full target page
gets the Reader check. No Drive fetch or paid image generation happens in repair.
The host tool manages the queue and the `--no-push` hold; never edit the queue yourself.

## Licensed figures and closure

The tool files `figure_requests` into private `docs/figure-requests.json`, binding each stable ID to its page, source bytes and the original material hash. Keep exactly one unindented `<!-- figure-request: <id> -->` at its place. Never reuse an ID for changed source/crop/purpose; never edit the generated request list. An unresolved request gets the fixed generated figure-pending notice and appears in status and the private owner notification. A valid pre-recorded permission proceeds without another owner question.

In an owner's session, record `docs/licenses.json` as a JSON array. Each record has `sha256` (the original uploaded material), `granted_by`, `scope: private | public-with-credit | none`, `credit` (one public-safe line), `own_work_confirmed` (boolean) and `on` (`YYYY-MM-DD`). No teacher's private name belongs in the public credit. A material-wide permission only covers `origin: teacher-own` with `public-with-credit` and confirmed own work. For third-party or unknown origins, the owner must establish the particular image's separate permission with an additional `request_id` on the license record; the permission giver must own the licensed work. A request-specific record overrides the material-wide record, including a refusal.

After permission, on the next touching run or repair, supply a normal `figures` commission and candidate with the request's ID and page; keep the request marker. The commission's `source_image` identifies the requested source and a pixel crop for the independent checker. The tool adds the exact public credit before review and inserts only on a current independent accept; it records the license and output hash together. If the owner chooses another image or a redraw, remove the request marker and use a new commission ID for that route; if they choose deletion, remove the marker and adapt the teaching text. Historical request records remain private. Never place an unlicensed candidate in the wiki.

For a reused lesson banner, set `banner_from` to a listed topic page. The tool maintains `lesson-banner` with that topic's current header; do not copy a banner link by hand. The reader checks the lesson context, and a changed banner invalidates its previous verdict. Request filing, banner refresh and publication metadata use the existing resumable tool-write journal; none starts another writer or review cycle.
