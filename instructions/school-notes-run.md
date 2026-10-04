# Working in a school-notes run

Shared operating rules, loaded through [AGENTS.md](../AGENTS.md). Learner work happens only inside a run of the `school-notes` tool: hourly (cron) or in the owner's session (`school-notes chat`). A harness started directly on the host is never used for learner work.

## Who does what

The tool does everything that can be computed: Drive download and filing into `sources/`, hashes, duplicate detection, page order, machine frontmatter, index blocks, `publication/public.json`, review-file state, evidence records, image generation and insertion, `check`, commit, rebase, push and the public site. The writer (you) reads the sources and writes the wiki: subject teaching, interpretation, placement, prose, diagrams, the image plan and image judgement, the evidence description, the `wiki/log.md` entry, review fixes. Do not do the tool's bookkeeping by hand; it would be overwritten or refused.

## Run files (`.school-notes/`, never committed)

* `fetch.json`: the run: `packages` (Drive folder, subject, role `fuzet`/`tanari`, new subject, and the subject `card` snapshot: `role`, `conventions`, `style`), `pages` in their fixed order (`seq`, the stored `sources/...` path, `duplicate_of`), the `range` of pages this call covers, the `open_review_items` to fix, the `pending_images` to produce, and `conflict_files` while resolving a conflict.
* `changes.json`: files already changed in this run; continue from there, do not redo them.
* `check.json`: problems the tool found; inspect the changed page independently with the checklist before judging this list.
* `result.json`: your output (schema below), written at the end of the work.

## Fixed prompt

Read `AGENTS.md`, `PROFILE.md` and the rules the rule map requires for ingest, in that order. Read `fetch.json`, `changes.json` and `check.json` to identify scope and existing work. For ingest, first perform the independent whole-page checklist, including when resuming; in fix mode, first independently check only your own repair. Then decide the machine findings. Do the work, write `result.json`, and call MCP `check` at most three times per invocation. Fix errors; decide every warning from the last own check in `warnings[]`. The check does not find everything; zero warnings do not mean the page is complete. Fix mode checks its own changes first and never edits outside assigned items because of a warning.

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

* `notes`: every non-duplicate page of the range belongs to a lesson-notes page; you name the page `<date>-<topic>-jegyzet.md`. The tool writes its machine fields from this.
* `question`: only for a blocking problem (not a notebook, a textbook page, unreadable, a subject other than the Drive folder's). A non-blocking uncertainty goes under the page's open questions.
* `review_closure`: at most 20 closed items per run. Never edit a review file. Only fix when you agree; `disagree` requires a nonempty reason. One reviewer response may follow; in `round: 2` close only as `fixed` or `question`. `question` requires the public-safe open-question anchor (`question_id`); `settled` points to an existing question or decision. Questions concern the material, not the reviewers' dispute.
* `coverage`: the private source-unit → teaching-section ledger, separate from image observations. Each entry has `source` (repository path), `unit` (the definition, exercise, drawing or other source unit) and exactly one of `target` (`wiki/...md#section`) or `reason` (why it has no learning value). Use source reading order, then target path as a tie-breaker. In fix mode record only units affected by the assigned repair.
* `checks`: what you looked at, what you saw and what you decided for each image-dependent claim (see *Visual evidence checks*). `image` is a page `seq` or a repository path under `sources/` or `wiki/assets/`.

## Where you may write

`wiki/**` (except generated blocks and machine frontmatter keys) and `wiki/assets/**`; in the owner's session also `references/**` and valid `card` fields of existing entries in `tools/subjects.json`, or new entries containing only `name` and `card` (no other subject metadata); while resolving a conflict also the conflicting files. A file that existed before the run is never renamed or deleted; a file created in this run may be deleted. No symlinks, no dotfiles under `wiki/`. The tool's path guard refuses everything else.

## MCP tools

`check` (call it at the end; it also reports files you may not touch), `image_generate(plan_id, repair_note?)`, `wait(job_id)`, `status`; in the owner's session also `fetch` and `finish`. Long operations return a job id: call `wait` until the job is done. In a session started with `fetch.json` `mode: interactive`, call `finish` at the end and report its outcome. There is no Git in the container and no web access: a fact that needs an outside source becomes an open question.

## Subject cards and figure handoff

The subject's `tools/subjects.json` entry is the only canonical place for `card`: nonempty `role` and `style` strings, and an ordered `conventions` array of distinct nonempty strings. An empty convention list means no confirmed local convention; it never grants permission to invent one. A missing card is omitted from `fetch.json` for existing configurations and newly discovered subjects. Preparation copies a validated card into each package and persists it for resume; an interactive update affects a later preparation. The configured `grade` stays separate. Only the owner's interactive session may edit cards or preload a new subject with only `name` and `card`; cron cannot. The tool creates its index with the first package and fills missing emoji/colors without overwriting the card or existing settings. See [the template example](../examples/subject-card.json), which does not initialize a subject.

In state A the writer also draws; visual-module routing is unchanged. Every figure assignment in `.school-notes/figures/<id>.json` has `id`, `page`, `anchor` (section title), `kind`, `source_image` (path and crop, required for either drawing route), `purpose`, `must_show[]`, `avoid_misreading`, `taught_conventions[]` and `text_complete_without_figure: true`; replacement also has `replaces` and `decision_reason` (a/b/c plus explanation, per visual policy). The candidate's `figures/<id>/figure.json` records form, tool, elements and meanings, visible texts, `attempt` and private `corrections[]` for a notebook drawing. Leave `<!-- figure: <id> -->` or `<!-- image: <id> -->`; leave the marker and the commission; the tool queues it. The writer does not self-accept. The tool inserts only after the independent figure check. Teacher-image requests use `<!-- figure-request: <id> -->` and the private request list, never a public license question.

## Visual engines

Every engine of `tools/visual_tools.py` works in the container: Python with matplotlib and numpy (plots, measured data, constructions), Graphviz (graphs, trees, flowcharts), PlantUML (process, state and sequence diagrams), POV-Ray (3D scenes, also animations rendered to MP4 with a static poster) and FreeCAD (exact technical drawings, parts, sections). Mermaid works directly in the Markdown; illustrations come from the image tools above. Choose the engine that best supports understanding of the figure, following [technical visuals](technical-visuals.md); render with `uv run tools/visual_tools.py render …` into `wiki/assets/`.

## Generated learning fields

The tool maintains the `lesson-sources` generated block on lesson logs and the `pending` draft notice. Give source names only in `lessons[].materials`; never write the 📎 line or these blocks yourself. `draft_tracking` is machine frontmatter: the tool records when a draft or an additional linked lesson was first observed. Editing prose does not reset its 14-day warning. Decisions remain writer-managed only in an interactive owner session; cron compares their YAML bytes with the run's base. The tool generates the private `docs/review/dontesek.md` overview from them.

## Stable order

The order of existing chapter, lesson and topic lists never changes between runs. Within a topic page, the section order is didactic and may change to build prerequisites before use; preserve anchors and links. A new item goes to its fixed place: chapters in the syllabus/notebook order, lessons by date, topics in the order the lesson treats them, list items where the existing order puts them. Changing the chapter, lesson or topic order is done only on the owner's request in a session. The tool's `check` refuses a cron run that re-orders existing `chapters`, `lessons`, `topics` or a page's `order`.
