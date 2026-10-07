# Template changelog

Newest first. Each entry says what changed in the shared files and what an existing wiki must do when it applies the update (see *Template updates* in [Wiki workflows](instructions/wiki-workflows.md)). A wiki records the version it is on in `PROFILE.md`.

## 1.22.6 - 2026-10-07

- Dates on the subject index (owner feedback: the ranges and words were too long and the page filled up with them). Every generated lesson date - the 📍 block, the chapter spans, the lessons table, the catch-up list - is a quiet date item after the important information, like a release line: on the study site a small outline clock and small grey text (`okt. 4.`, `szept. vége óta`, `szept. eleje – okt. eleje`); the year only outside the school year (`2025. okt. 4.`); never an ISO date in visible text (a full date is `2026. 10. 04.`). An uncertain date or place (an undated lesson, a span resting on one) only gets `~` before it; its range and reason are the hover tooltip (`Dátum nélküli óra: szept. 23. – okt. 4.`), never visible text; the words "dátum nélkül", "után, legkésőbb" and "még tart" and the ↕ mark and its legend are gone. Paper (PDF) prints only certain dates. Wiki structure (*Subject index*, *Stable order*); PROFILE *Wording*: *lesson date* and *uncertain date* (new), *current chapter*, *latest lesson*, *earlier chapters*, *chapter span* updated, *uncertain place* and *undated in the block* replaced.
- The study site (`.study-when`, `.study-when-unsure` in the renderer's allow-list and the stylesheet, light and dark theme, print) and the local page checker (`tools/page-check`: the `title` of a `span` kept, the same style) show them.
- Migration (controller-owned): synchronize the changed `instructions/wiki-structure.md` and `tools/page-check/{core.mjs,style.css,test.mjs}`; the next `sn close` regenerates the subject indexes. No learner content changes.

## 1.22.5 - 2026-10-07

- Teaching order, fix round of the 1.22.4 review (Wiki structure *Subject index*, *Stable order*; Helyi menet *Stable order*): a chapter's start is, of its lessons, one that no other of them certainly precedes (preferring one with a known lower bound; a lesson with only an upper bound starts it when the evidence puts it before the others), placed by its own chronology; `<X> után` means X+1 at the earliest. The average-date tie-break is dropped (it moved with revisits): two chapters started in one lesson stand by the order of their first topic in that lesson's `topics`, then by the syllabus; a file name never decides. Inside one lesson log only the notebook order decides. Evidence of order is the notebook order of one lesson log, successive pages of one source folder and non-overlapping ranges; ↕ marks a lesson whose order is not so evidenced, and a chapter span whose start (or a finished chapter's end) is an undated range - an uncertain end is never cut at the next chapter's start as if certain. The `sn check` chapter warning reports every provable inversion of the list with the place the chapter belongs. The upper-bound warning compares a lesson only with dated lessons of its own source folder.
- Subject index: the 📍 block stands right after the back link, before the catch-up list, on every index (an index with another order converges at the next close); its list uses the *undated in the block* wording like *Latest*. PROFILE *Wording*: *uncertain place* and *undated in the block* updated.
- The `wiki/log.md` entries (Helyi menet *Hand-over*, *The commands*): written only for a hand-over the close retires, once per pass by its pass id (a `<!-- pass: <id> -->` marker in the log, `logged: true` in the `closed.json` the folder carries into its move), newest pass first under the day's heading; an interrupted close is repaired by the next one; `sn done` reports a retired pass without `log` under its subject, which holds only that subject's retirement.
- Migration (controller-owned): synchronize the changed `instructions/wiki-structure.md` and `instructions/helyi-menet.md`; the next `sn close` regenerates the subject indexes. No learner content changes.

## 1.22.4 - 2026-10-07

- Teaching order (owner decisions of 2026-10-07: the learner should see where the class is and in which order it took the material; the order belongs to the chapters, the units a test is written from, and is the order the class started them). Wiki structure (*Subject index*, *Topic pages*, *Lesson-notes pages*, *Stable order*), Helyi menet (*Stable order*):
  - chapters stand in the `chapters` list in the order the class started them: a chapter's start is the first lesson whose `topics` names one of its pages (a dated lesson by its date, an undated one by the lower bound of its `date_note`); a tie is decided by the average date of its lessons, then the syllabus; a later lesson (a revisit, a mixed review) never moves it. "Chapters in the syllabus order" is replaced. `sn check` warns when the `chapters` list contradicts this, only when the two starts are in a known order;
  - `topics` names only what the lesson actually teaches (a definition, an explanation, an exercise, its own notes in the notebook); a forward mention or a brief reference stays in the lesson log's text, at most as a link;
  - within a chapter, topic pages stand in the order that makes sense for learning, by default the order the class started them - the writer judges it, the reviewer checks it, no machine warning; `sn check` warns about a topic page that no lesson's `topics` names;
  - a revisit updates the existing topic page (no new page), which keeps its place; a section's lesson line lists every lesson that taught it, first to latest (Content and curriculum, *When was it taught*);
  - moving a chapter or topic page that the evidence shows misplaced is a standing re-ordering request of the owner; any other re-ordering only on the owner's request; the reviewer checks the order in every pass.
- Undated lessons stand by the LOWER bound of their `date_note` range (then the upper bound, then the notebook), no longer by the upper bound, so a catch-up lesson with a wide range no longer floats above later dated lessons; inside one lesson log the notebook order narrows the range. An undated lesson whose order with another lesson is not known (overlapping ranges from different source folders) gets the *uncertain place* mark ↕ with its legend.
- The `date_note` bounds: the lower bound is the date of the last lesson known to come before it, the upper bound the next lesson known to come after it or, for catch-up material, the day the material was fetched - `sn fetch` now records it as `placed` in the folder's `sn-fetch.json` (an older manifest: the day it was committed) - never a Drive folder label. `sn check` warns about a `date_note` without a lower bound and about a `legkésőbb` bound earlier than a dated lesson from the same source folder.
- Subject index: the generated *📍 Itt tartunk* block right after the back link (the chapter started last with its span, the latest lesson with its topic pages, the chapters before in the order they were started, the five lessons before the latest, newest first), and a generated *chapter span* (🗓️ when the chapter was taught) under every chapter heading. PROFILE *Wording*: rows *uncertain place*, *where we are*, *current chapter*, *latest lesson*, *earlier chapters*, *lesson order*, *undated in the block*, *chapter span*.
- The `wiki/log.md` entry: the writer hands it over in `adatok.json` `log` (`[{kind: Creation | Update, text}]`, one Hungarian line each, links relative to `wiki/`), `sn close` writes it under the day's heading (newest first, a replay adds nothing); `sn done` reports a finished pass without `log`. The controller no longer applies a proposed log entry. Helyi menet (*Who does what*, *Hand-over*, *The commands*), Wiki workflows (*Ingest*).
- Migration (controller-owned): synchronize the changed `instructions/wiki-structure.md`, `instructions/helyi-menet.md`, `instructions/wiki-workflows.md` and `instructions/content-and-curriculum.md`; the next `sn close` regenerates every subject index (the new block, the chapter spans, the lessons table in the new order). Learner content: the `sn check` order warnings are the writers' fix list (a `chapters` list against the teaching order, a topic page no lesson names, a `date_note` without a lower bound or with a folder-label upper bound), and a `topics` entry that is a mere mention is removed.

## 1.22.3 - 2026-10-07

- Wiki workflows (*Open-question anchors and decisions*): the exceptions to "only when a human has answered ... remove" name the date-only lesson question of 1.22.2 (*Lesson-notes pages*): it, and the date part of a mixed question, is removed without a `decisions` entry.
- Links and images (`sn check`, `sn done`, `sn close`): one shared label pattern reads link text and image alt the way the renderer does - a backslash escape (`\]` never closes the alt, `\!` and `\[` are text, `\\!` is a backslash before a real image), balanced brackets nested up to four deep, never across a blank line, and only with a complete destination. Every image-specific step uses it (writer guard raster check, broken-image count, directly linked SVGs, figure contexts and replacements, banners, heading ids, web footnotes). An alt text with escaped interval brackets (`\]-1; 3\]`), as `sn close` writes it, is now an image everywhere; before, such an image counted as a plain link, so these checks skipped it.
- Formulas: image alt text is masked (never deleted) before the `$$` count; an undefined reference image or an incomplete destination is not an alt text. `\[ \]` and `\( \)` are no longer counted: neither renderer reads them as math, so LaTeX between them is a warning ("`\[…\]` does not render as math, use `$$…$$`"). Wiki structure (*Math and formulas*) says so. An unbalanced `$$` stays an error.
- Migration (controller-owned): synchronize the changed `instructions/wiki-workflows.md` and `instructions/wiki-structure.md`; no learner content changes (on both learners only the five figure links of Benedek's `wiki/matematika/intervallumok.md` change from a link to an image; no figure verdict key changes).

## 1.22.2 - 2026-10-07

- Lesson dates (owner decision): a lesson without a date is a normal state, not an open item - a lesson is not always uploaded after class, an illness mixes up the order, and sometimes the student does not write the date. Wiki structure (*Lesson-notes pages*): the sentence "The student is asked to date every lesson in the notebook" is replaced; the lesson keeps its `date_note` range, which the lessons table shows, and no open question is raised only to ask the student for a lesson date. An existing open question that only asks for a lesson date is removed by the writer and the removal logged (no `decisions` entry, its ID not reused); a question that also asks for something else (a missing page, a sharper photo, whether two pages are one lesson) keeps that part and drops the date part. Wiki workflows (*Ask self-contained, useful questions*: questions concern the material or reading, a missing lesson date is never asked for) and Sources and evidence (*Check a fact on the web before leaving it open*: the lesson date is no longer an example of an open question) refer to it. No `sn` check counts or requires a date question.
- `sn check` and `sn done`: the `\[ \]`/`\( \)` and `$$` delimiter count leaves out image alt text (CommonMark escapes and one level of balanced brackets), where interval notation such as `\]-1; 3\]` is escaped and never rendered as math; body text is counted as before. The local page checker (`tools/page-check/core.mjs`) keeps escaped characters in an image's alt text (markdown-it dropped them there: `]-1; 3]` showed as `-1; 3`); the site renderer already did.
- Migration (controller-owned): synchronize the changed `instructions/wiki-structure.md`, `instructions/wiki-workflows.md`, `instructions/sources-and-evidence.md`, `tools/page-check/core.mjs` and `tools/page-check/test.mjs`. Learner content changes in the next writer pass of each subject: its date-only open questions are removed (and the date part of mixed ones dropped), each removal logged. At the time of this release most lesson logs of both learners carry one (Benedek about 26, Barna about 8); `sn done` does not report them, so the controller names them in the writer brief.

## 1.22.1 - 2026-10-07

- Helyi menet (*Hand-over*, *The commands*): a hand-over is never deleted. `sn close` (full or `--subject`) moves, of the hand-overs it read at its start, each subject's whose part succeeded (no STOP, no `sn done` problem on that subject's pages, unchanged meanwhile, and in a full close a snapshot `keys.json`) from `.school-notes/out/<subject>/` to `.school-notes/done/<pass id>/` (the evidence records' pass id `helyi-<digest>-<subject>`; a replay gets `-2`, `-3`, ...); `--check` and `--snapshot` move nothing. A hand-over left from an unfinished pass is finished or moved by the controller with `mv` into `.school-notes/done/`.
- Web footnote (Sources and evidence, *Check a fact on the web*): the link form may be preceded by the source's publisher or author. `sn check` and `sn done` enforce the structure exactly - `[^id]: Title. https://... (ellenőrizve: YYYY-MM-DD).` or `[^id]: [Title](https://...) (ellenőrizve: YYYY-MM-DD).` and nothing between the URL and the date or after the date, no other date wording (`letöltve`, `lekérve`, `korábbi ellenőrzés`), no angle brackets or link title, no continuation paragraph, an `https` URL. In the title's rendered text they refuse a number with a locator (page, slide, figure, exercise, chapter, annex, table, section, paragraph, `§`, `(N)`, a page id) and a word of the private context (textbook, `tk.`, notebook, teacher, lesson, slide deck, notes); whether a title names only the web source is the reviewer's judgement. The message names `page:line [^id]:` and what is extra, with the expected form.
- Migration (controller-owned): synchronize the changed `instructions/helyi-menet.md` and `instructions/sources-and-evidence.md`; learner content changes only where `sn done` reports a web footnote that is not in the form - a writer pass fixes it before the learner is published.

## 1.22.0 - 2026-10-07

- Local pass: learner work happens in the owner's interactive Claude Code or Codex session; the controller starts a writer and an independent reviewer agent per subject, and the `sn` commands (`fetch`, `book`, `check`, `gen`, `close` with `--snapshot`, `done`, `publish`) do the mechanical steps. The VM run (cron, container, MCP tools, `fetch.json`, `changes.json`, `check.json`, `result.json`, nightly reviewer, review-item queue, e-mail) no longer exists. *Working in a school-notes run* (`instructions/school-notes-run.md`) is replaced by [Working in a local pass](instructions/helyi-menet.md): who does what, the hand-over folder `.school-notes/out/<subject>/` (`iro-jelentes.md`, `figures.json`, `ujranezes.json`, `render/`), the commands, where the writer may write, and, unchanged, the subject cards, the figure commission and candidate contract and *Stable order*. What `result.json` carried goes into the writer's report (coverage ledger, open and settled questions, teacher-image requests, blocking problems, omitted harmful instructions, proposed log entry, emoji and color of a new subject); its machine-readable part (lesson logs with their source pages, image checks, teacher-image requests) goes into `adatok.json`, from which `sn close` writes the machine data (below).
- `AGENTS.md` (*Start here*, rule map, *Finish the authorized work*), `CLAUDE.md` (the `fetch.json`/MCP paragraph removed), Wiki workflows (*Open-question anchors and decisions*, *Write policy*, *Session start*, *Ingest*, *Self-check*, *Reader check*, *Git*, *Review* in place of *Review handoff and closure*, *Template updates*: files that leave the shared set are deleted), Sources and evidence (filing, processing status, teacher materials, tools, *Visual evidence checks*, teacher-image requests; the license record format moved here from the run module), Visual policy, Media workflows (*In a local pass* in place of *In a school-notes run*), Wiki structure, Note formatting, Task execution, Content and curriculum, the visual-tools install guide and the technical-visuals example README: VM, MCP, cron and run-file wording replaced by the local pass. Every content rule (notes, figures, visual policy, the web check of 1.21.7) is unchanged in meaning, except the changes listed below (the reviewer-sentence exception, the web-footnote form, machine data by the tool). Mechanical changes: a figure not accepted after the one confirmation is not inserted, its marker is removed with the reason recorded (it no longer waits as pending); the decisions rule says "without a human answer" instead of "cron".
- Removed from the shared set and the template: `instructions/{hermes-and-bots,install,install-drive,install-learning-images,learning-image-execution,agent-capabilities,media-handoff,system-guide}.md`, `instructions/policy-migration-1.15.0.json` and `tools/test_policy_migration.py`, `.agents/skills/` (4 skills), `tools/{drive_connect,check_hermes_tutor}.py`, `tools/test_repo_setup.py`, `learning-images.example.json`, `.env.example`. Removed from the shared set only (the template's `sn` command line still uses them): `tools/{drive_media,learning_image,prepare_photo}.py` and `tools/test_{drive_media,learning_image}.py`. `.gitignore` no longer re-includes `.env.example`. 114 shared files become 90.
- Machine data belongs to `sn close` (local-pipeline review of steps 4+7): the writer no longer writes a lesson log's machine keys, the page evidence records or `docs/figure-requests.json`; it lists them in the hand-over's new `adatok.json` (`writer`, `notes` with the source pages of each lesson log, `checks`, `requests`), and `sn close` writes them from the source manifests `sources/**/sn-fetch.json` that `sn fetch` now keeps (hashes, Drive file and folder; a page known by its hash is listed, not stored again). Helyi menet, Wiki workflows (*Ingest*), Wiki structure (*Lesson-notes pages*), Sources and evidence (*Filing is the tool's work*, *Preserve the check for the next agent*, *Teacher images and rights*). A lesson's `date` comes only from its notebook page or material, never from a Drive folder name (the folder's date is the upload label).
- `sn close --snapshot` and `sn close` run the candidate preflight (schema, files, crop, editable SVG source or render receipt, generation proof, rights path) and the writer guard (committed `sources/` and `references/`, symlinks and dotfiles under `wiki/`, existing `decisions`, machine keys and generated blocks, raster images only through a figure block) before any write; `sn done` runs the guard too. A `figure-request` place is not a missing figure.
- Visual policy (*Inserted figures in edited sections*): the exception for a reviewer-proposed sentence applied word for word is removed; any change of the section after the review sends the figure to the confirmation pass. Helyi menet: restored from the removed run module, "A writer-drawn SVG or inline Mermaid may be edited directly without a commission; a generated or licensed image keeps the commission and its rights gate."
- Web footnote (Sources and evidence, *Check a fact on the web*; *Keep attribution visible*): exactly `[^id]: Title. https://... (ellenőrizve: YYYY-MM-DD).` - one web URL, title, retrieval date, no second link, path, file name or page identifier; `sn check`/`sn done` refuse other forms, the footnote read with its continuation paragraphs and reference-style links; a credit with a license link uses two footnotes. The public gate (`study-site/public-patterns.json`) refuses `data-private-link` and, in visible text with web URLs left out, `sources/`, `references/` and a page id `p0001`; `sn check`/`sn done` apply the same visible-text patterns to the page's public view. A `materials` name that is a file name with an extension is an error (it would be published on the 📎 line).
- `tools/book_index.py`: a README may give several printed-page offset bands (`printed-page offset: N from PDF p`); unnumbered inserts before a band have no printed number. `tools/test_shared_tools.py` covers a two-band book.
- Migration (controller-owned): copy the shared set, `git rm` the removed files above from every linked wiki, and delete a learner-local `tools/test_book_index.py` if present (its cases are covered by the shared `tools/test_shared_tools.py`); links from local files (README, `docs/`) to removed files are turned into plain text so that no link breaks. The migration itself changes no learner content, but the stricter checks need a content round where a wiki does not meet them: `sn done` reports each web footnote that is not in the fixed form (page:line and what is wrong), and the learner is not published until a writer pass has fixed them (at the time of this release: Benedek, 19 footnotes; Barna, none).

## 1.21.7 - 2026-10-06

- Sources and evidence (*Sources*): the rule *A URL is a pointer, not a source* ("the run has no web access ... record it as an open question") is replaced by *Check a fact on the web before leaving it open*: when a factual question or doubt comes up while writing or reviewing (a name, a date, a spelling, a fact), it is looked up on the internet first (for general facts, for example, on Wikipedia). The check verifies and makes precise what is taught, it brings in no new material; the textbook stays the primary reference where it covers the question. The reliable source is cited in a keyed footnote of its own (title, URL, retrieval date) that holds no notebook, teacher-material or textbook quote or location, because the public site shows footnotes with a web link; visible text never names the website. When the source settles the question, the page teaches the correct statement with the existing correction label and notebook correction request; only what this cannot settle (a lesson date, the teacher's expectation, the learner's own data, or any question in a run without web access) stays an open question; an existing open question the check settles is removed by the writer and logged, without a `decisions` entry. The web source also gets a `sources` entry. Content rules (*Never invent facts*), Wiki workflows (*Reading handwritten sources*: a fact in doubt is not settled by the notebook, the teacher's material or memory alone; *Open-question anchors and decisions*) and the run module (*result.json* `question`, *MCP tools*) refer to it.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.21.6 - 2026-10-06

- Visual policy (*Decide before drawing*, *Inserted figures in edited sections*): when a pass changes the text of a section that holds an inserted figure, the figure's verdict no longer holds; the one review of the change actually looks at that figure against the new text and gives its verdict, and only its `accept` renews the verdict. Only the figures whose verdict the edit invalidated are looked at, only for what the edit could change; a sentence the reviewer proposes with its acceptance needs no further look. Nothing is regenerated for this: a replacement only when the figure's content is outdated or no longer correct (`decision_reason` `a` or `b`); a text clarification that resolves the mismatch is the fix. No new review round (in a tool run the run module applies).
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.21.5 - 2026-10-06

- Visual policy (*Decide before drawing*): the visual decision and its figures are part of the writer's pass, not a separate round; the one independent review checks text and figures together and gives the figure verdict; a rejected figure is repaired once and the same reviewer confirms only that figure (no new review round). The owner may ask for the decision, figures and review on named pages only. Media workflows (*In a school-notes run*) refers to it.
- Sources and evidence (*Inspect available evidence*, *Reading a book*), references README: a textbook image without a description is decoration, a photograph or the like and is not opened by default; its OCR text may be read, and the image is opened only when that OCR text gives a concrete reason; otherwise a point that depends on it stays an open question. Notebook and teacher source images are still inspected directly.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.21.4 - 2026-10-06

- Textbook line (Note formatting, Sources and evidence, run module): the `🔖 Tankönyv:` line either names an identified lesson and page or states that the learner's grade-N textbook does not cover the topic; a "not yet identified" placeholder is never published – the line is left out and the gap goes to the evidence record or the open questions. The check warns about a textbook line without a lesson or page number, and an existing placeholder becomes one machine item.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.21.3 - 2026-10-06

- Learning images (`tools/learning_image.py`, Learning image execution): an owner-approved reopen (`status --reopen … --paid`) records a grant in the image ledger; the paid-attempt limit counts the attempts since the latest grant, so one approval opens exactly one new frame of three paid attempts. The monthly image budget still applies.
- Migration (controller-owned): synchronize the changed shared files through Template updates; no learner content changes.

## 1.21.2 - 2026-10-06

- Visual tools (`tools/visual_tools.py`): font and matplotlib caches go to a private temporary directory that is removed after the render; nothing is written under the output folder in `wiki/assets/` except the figure and its render record.
- School-notes run (fix calls): an item whose figure is a pending figure of the run is worked in that figure's call, so one figure is assigned once; an orphan figure place (a marker with no pending or accepted figure) becomes one machine item: embed an accepted figure with its commission or remove the stale marker – the writer decides. A `figure-request` marker waiting for a licence decision is never such an item.
- Migration (controller-owned): synchronize the changed shared files through Template updates; no learner content changes.

## 1.21.1 - 2026-10-06

- School-notes run and Wiki workflows: the rules now describe the 2.6 one-pass run throughout – no in-run correction rounds; P3 or P5 checks every change once; an unchecked page holds the release until a later run rechecks it; a writer question in a fix call becomes an owner item; the nightly reviewer decides from the git diff; an owner item can be reopened by the controller when its obstacle is gone.
- Figures (run module, writer and fix prompts): a whole `figure-…` block may be removed when the figure is accepted elsewhere; the block's content stays tool-owned.
- Wiki structure: an explicit `<a id>` anchor must not repeat an id the page already has (a heading's id); the check reports it in the writer's call.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.21.0 - 2026-10-05

- School-notes run (Fixed prompt, result.json): each run has one pass – the writer works, the machine check runs, P5 judges every changed author line once; there are no in-run correction rounds, and findings of the independent check become items for the next run. An undecided item and a `fixed` closure without a text change stay open. Pending figures come in their own writer calls after the text work. `infographic_decisions` and `warnings` are removed; the optional `review_requests` asks the nightly reviewer to look at a page and removes nothing from the review.
- Writable scope: a page may be renamed or deleted when every link to it is updated; the check reports a link to a missing page.
- Visual policy: a new topic, summary and subject index gets a banner; a text edit on an existing page never requires one. A writer-drawn SVG or inline Mermaid may be edited directly without a commission; a generated or licensed image keeps its commission and rights record.
- Catch-up material (Sources and evidence): the tool explains the 📝 mark in one sentence above the lesson table; the index catch-up list opens with one sentence saying what to do and gives each lesson's date and topics from its `lessons` frontmatter. No illness icon or absence wording anywhere.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.20.1 - 2026-10-05

- School-notes run (Fixed prompt, result.json): calls and page groups describe the work focus, not page permissions; every wiki page may be edited as needed, without unjustified rewrites. P3 reviews all changed pages and P5 judges every changed author line, including changes outside assigned items. A failed machine check is fixed by the writer on the same tree; finished work is not rolled back.
- Repair mode: start from the assigned page and edit any wiki pages the repair needs; related lesson logs and summaries may be edited too.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.20.0 - 2026-10-05

- School-notes run (Fixed prompt): errors that already existed at the run base (`kind: inherited-check`) do not block the run and are never fixed on an unassigned page; the tool records them as review items.
- School-notes run (`review_closure`, pending figures): every assigned item is decided, with no per-run closure cap; a fix run takes the complete assignable list in page groups of at most 30 items per call, all pending figures first.
- Wiki workflows (Review handoff and closure): the nightly reviewer examines only new material (`run`, `chat` commits); findings carry `severity: hiba | javaslat`, only errors become items, suggestions go to the private report; every existing backlog item stays assignable; up to three correction/recheck rounds in one run; no daily fix-run cap.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.19.3 - 2026-10-05

- Learning images (Learning image execution): after a rejected or lost image the plan may be changed; the tool generates it as a linked job version, and all versions of one target share the three paid attempts. A plan awaiting a verdict or already accepted stays unchanged.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.19.2 - 2026-10-05

- Pending notices (run module): only a pending figure, a continuing (`draft`) topic and a new reader page from a v2 writer run that was never reviewed show a notice; review items never do.
- Infographic decision (run module): in a fix or repair run every assigned topic page gets a recorded infographic decision (a `kind: infographic` commission or a short reason).
- Lesson logs (Wiki structure): a log that covers several lessons may use the plural heading „Mit tanultunk ezeken az órákon”.
- Migration (controller-owned): synchronize the changed instructions through Template updates; the tool removes stale notices once; no learner content changes.

## 1.19.1 - 2026-10-05

- Image plan (Media workflows, run module): the exact required and optional fields of `image-plan.json` with a valid example; the commission fields (`id`, `kind`, `page`, `purpose`) belong in `figures/<id>.json`, not in the image plan.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.19.0 - 2026-10-05

- Banner and infographic are always generated images: an image plan, `image_generate` and an independent figure reviewer (Visual policy, Media workflows, run module). Every topic page, chapter summary and subject index has a banner; a lesson log takes its topic's banner through `banner_from`. An infographic goes where an overview teaches more than the text, at most one per topic page. Banner text is at most two lines, the smallest letter at least 3.5% of the image width. Notebook drawings, teacher drawings and exact teaching figures stay drawn.
- Pending figures (run module): a fix run and the in-run correction round get the pending figures as assigned work outside the closure limit; each needs a new candidate or a reasoned `failed`.
- After a correction only the corrected items and the changed lines are checked again; a finding on an untouched line goes to `owner_notes`.
- Migration (controller-owned): synchronize the changed instructions through Template updates; the tool's one-time pending-figure migration runs separately; no learner content changes.

## 1.18.2 - 2026-10-04

- Inside a school-notes run the tool builds and checks the pages; the writer runs no renderer (Task execution step 5 and the runtime-blocker sentence, Install, Wiki workflows self-check: MCP `check` checks formula delimiters, the build compiles the formulas).
- One-time repair (run module): the writer may add or correct `lessons[].materials` of an existing lesson log (plan 7.3); every other lesson field stays protected.
- Migration (controller-owned): synchronize the changed instructions through Template updates; no learner content changes.

## 1.18.1 - 2026-10-04

- Math and formulas (Wiki structure): the school-notes tool compiles every formula with MathJax when it builds the site before the push and returns a formula error as a check item; the writer installs and runs no renderer during a run, and a missing local renderer is not a blocker (a v1 rule had stopped a repair run on the VM).
- Migration (controller-owned): synchronize the changed instruction through Template updates; no learner content changes.

## 1.18.0 - 2026-10-04

### Closure and export

- Bind inherited asset rights, render outputs and generated-image receipts to the actual output SHA-256. New request-based licensed output additionally requires the current permission and independently accepted image record. Receipt folders alone grant nothing; teacher copies under `wiki/assets/orai/` remain forbidden.
- Persist private figure requests with original and extracted-source hashes, validate owner license records, include both in the normal commit inventory, reuse independent figure acceptance and visible credit, and show unresolved requests through the existing pending/status/notification paths.
- Render lesson-log `banner_from` references to the topic's current header; include the reused image in the lesson's reader verdict. Use the fixed Hungarian `sourceNote` from the initialized PROFILE first name. Warn, without blocking, on source-location patterns inside web-linked footnotes.
- Add two synthetic-learner privacy regressions for decisions, hidden markers, source files, private footnotes, review files and the private log; add optional full HTML/PDF/site builds with the controller's Chromium. No publishing or learner migration is enabled.
- Review corrections: file P4 requests and generated receipts through the public tool-write journal; background image jobs never save run state. Missing original hashes use request-specific, source-hash-bound permission. Show approved requests in scoped fetch/status inputs and reopen their completed pages when rebuilding the repair queue. Validate owner license data before writer work; separate footnote metrics and check probable teacher authorship.
- Migration (controller-owned): shared-rule version 1.18.0. Synchronize the changed instructions and changelog through Template updates after review. Deploy tool and renderer together. Hash-matching legacy rights, including licensed assets without a new request-based record, remain valid; request-based licenses are rechecked on every build so revocation takes effect. Before a private build, replace stale or hashless image rights with genuine matching receipts or explicit permission; never regenerate a hash just to preserve a stale right. Initialized profiles supply the already authorized first name; no profile or learner content is copied by this change. Run the full socket/browser tests and inspect both private builds and one interactive license workflow before considering publication; `publish = false` remains in effect.

## 1.17.0 - 2026-10-04

### Learner-neutral template

- Subject cards move to the shared `subject-cards.json` in the template root (one card per subject, `role` and `style` only, generally worded, the same for every learner); it starts empty. The `conventions` field, the learner `tools/subjects.json` `card`, the owner-session card edit/preload exception of the path guard and `examples/subject-card.json` are removed. Taught notation is read from the notebook. A missing card does not stop a run; `school-notes status` lists `hiányzó kártya: <subject>` per learner.
- `fetch.json` carries `learner.grade`; `grade` is required in each `[students.<name>]` table. The prompts' reader yardstick is the learner's school year, filled by the tool; the rule modules use the youngest main reader named in PROFILE *Audience*. The owner's principle sentence is unchanged.
- Learner-specific examples in the prompts are generalized; the owner's open-question rule names roles instead of learners. The reader prompt gets the complete owner yardstick. The *undated lesson* wording uses placeholders instead of dates. `install.sh` takes the learner list from the configuration; the crontab example names no learner.
- Review fixes: preparation validates the pinned learner `tools/subjects.json` (object shape and text `name`; a leftover `card` is ignored) before any Drive move; `install.sh` passes its configuration to `verify-tasks` and reports a missing `tomllib` (Python 3.11+) plainly; the Drive install guide says *every configured learner*. The neutrality guard compares learner names in the syntax tree, forbids a fixed learner count in shared text and treats only multi-word page stems as learner tokens.
- Migration (controller-owned): synchronize the shared set (new `subject-cards.json`, removed `examples/subject-card.json`, changed rules and run module) through Template updates; replace the *undated lesson* Wording row of each learner PROFILE with the placeholder form; check that every VM `[students.<name>]` has `grade` before deploying the package.

### Subject calls and repair (unit 1d)

- Call the writer sequentially per subject, using pinned role cards and stable source IDs. Only one oversized package gets D36 ranges. Validate each call before saving its resumable result; use complete run data for merged checks and metadata. The default writer timeout and example are 7200 s; explicit configured overrides remain effective.
- Add `repair --topic` and `repair --queue`, dependency-aware page passes, deterministic queue ordering and SVG inventory. A topic pass preserves linked logs' and summaries' prose; log shortening requires item coverage. Repairs use no Drive or paid generation. `--no-push` holds the committed branch until explicit finish or discard; cron cannot release it. Two failed attempts archive the work and hand the item to the owner while the queue proceeds.
- Deliver private writer `owner_notes` through the task completion report, finish response and existing once-per-run notification path. The step-3 e-mail format and step-2 independent figure/reader phases remain staged; repair uses the shared current chain.
- Migration (controller-owned): synchronize this changelog and the run module as part of the shared 1.17.0 set; deploy code, prompt and schema together. Set the VM writer timeout separately. Existing runs without subject assignments keep their saved ranges. Queue creation and priority edits require the explicit host `repair --queue` command. No learner content, deployment or publication is changed by this template work.

### Review corrections (unit 2)

- Report content, order and publication findings in the same check when metadata is valid. Existing metadata defects remain owner work even when the writer edits the page. Collapse consecutive identical lesson dates in the source pointer. Restore the required question and drawing clauses in the scoped fix prompt. Refresh the preparation base during downloads and pin it only before moving sources, preserving it across interruptions.

### Checks and review closure (unit 1c)

- Warning-only source-reference scanning covers changed Markdown public text, Mermaid labels and SVG text, with the plan's structural exceptions and a fixed two-learner corpus. Add complete check counts, error-first ordering, explicit truncation, durable three-call invocation limits, writer warning accounting and `unhandled` handoff. List verdict storage binds acceptance to file, normalized line hash and occurrence.
- Activate reference-aware `question`/`settled` closure, required disagreement reasons, one reviewer response and round-2 closure limits. Add full review keys and relation routing. New reviewer output requires `relates_to` and removes direct family questions; saved old reports still resume. Reader/list orchestration and the new nightly controller remain staged.
- Fix T-152 by resetting bad-work failures only with a successful G5 build. T-016 checks whole-file hashes and actual provenance; a tool metadata stamp does not make author errors program errors. No new phase or model is introduced.
- Migration (controller-owned): synchronize the shared run instructions and changelog through Template updates; deploy the package and matching prompts/schemas together. Existing report status maps remain readable; per-item metadata is additive. Learner migration and deployment remain controller-owned.

### Review corrections (unit 1a)

- Align the additive result schema and prompts, separating `coverage[]` from image `checks`; narrow fix mode to assigned repairs. Figure handoff now says to leave the marker and commission. Zero daily image budget keeps the pending generation list empty. The example nightly reviewer timeout is 5400 s; deployment remains the controller's work.
- Allow interactive preloading of a new subject with only `name` and a validated `card`. Validate cards before Drive movement and pin the preparation commit; preserve cards and existing display settings when completing a new subject. Writer owner notes reach the run log; private report list text cannot inject closure lines.
- Migration (controller-owned): add PROFILE Wording keys `lesson-log heading`, `lesson-log source line`, `undated source lesson`, `notebook correction request`; use ASCII ` - ` in the catch-up notice. Synchronize the changed shared rules through Template updates. New subject cards may be preloaded before first ingest; conventions require source-image verification or owner confirmation. No learner data is copied here. The template stays uninitialized; these migrations belong to release 1.17.0.
- The new result lists are preserved but their later pipeline consumers remain staged. `question`/`settled` closure and the review dialogue are implemented by unit 1c above. This replaces the former claim that all result fields were still pending. The removed whole-ingest instructions in `fix.txt` are replaced by checks of the repair itself; the nightly reviewer measures the teaching goal rather than writing notes.

### Source-grounded teaching (unit 1a)

- Source-grounded teaching rules (v2 repair plan, unit 1a): visible notes teach the subject without private sources; lesson-notes become short lesson logs. Removed the verbatim-notebook plain-language exception and visible source-error reproduction. Corrections teach the right content, retain a model-free role label and use one neutral notebook-correction question. Source details remain in private footnotes/evidence. Added reader checks, didactic section order, integrated updates, stable question anchors and decisions rules.
- Notebook/board drawings remain mandatory as the same drawing in the same role, correct; meaning-bearing layout is preserved, not errors or clutter. Banners show the topic, not an example; temporary catch-up labels are removed. Independent figure acceptance and the explicit teacher-image permission/request rules replace self-acceptance and the blanket teacher-image ban. Credits remain visible in web and PDF.
- New Hungarian writer/fix prompts and an updated nightly prompt. Subject cards (`role`, ordered `conventions`, `style`) are validated, snapshotted into fetch packages and editable only in an owner's session. Missing cards stay absent; no local conventions are inferred. The template remains empty; `examples/subject-card.json` illustrates the card schema. Catch-up index lists and lesson-table marks are generated deterministically with 📝 / ✅.
- Migration (controller-owned): compare shared-file hashes before replacing the shared set; resolve semantic differences, then synchronize and record this release and its exact commit in each learner profile. Separately update each local Audience, model-free Wording labels, neutral catch-up notice and catch-up heading; remove the `catch-up` banner label from local `tools/subjects.json`. Fill subject cards from confirmed learner settings and notes. Do not copy learner content or local professional settings between repositories. The catch-up `description` states subject matter only; origin stays solely in `notebook: classmate`.
- Staged implementation: these rules/prompts describe the target contracts. Subject call routing and fix execution, then independent figure acceptance (step 2), export and the nightly state machine follow in their assigned units; result fields, warning accounting and question/decision checks are implemented. Unit 1a does not deploy or enable them. The current nightly output contract remains usable, with additive `owner_notes` stored in the private report; writer notes are preserved during merge. Email routing follows the later controller work. Existing learner text and banners are migrated only in authorized repair runs, not by a bulk rewrite. No publication, spending, model change or deployment is authorized by this release.

## 1.16.2 - 2026-10-03

- The public site leaves out what a reader could not open: links into `sources/` and `references/` (a list item that starts with one is dropped, a link in running text keeps its words), every footnote without a public web link, and the grade prefix of chapter titles. One small line under every page says what the notes are based on (`sourceNote` in `publication/public.json`). The private wiki keeps every link and citation; nothing to change in an existing wiki.

## 1.16.1 - 2026-10-03

- Every visual engine is available in a run: Python/matplotlib, Graphviz, PlantUML, POV-Ray (also animations: MP4 with a static poster) and FreeCAD; choose the engine that best supports the figure.
- Original teaching files (PPTX, DOCX, PDF) stay on Drive; the repository keeps only the extracted material.

## 1.16.0 — 2026-10-03

- v2 way of working: learner work happens only in a run of the `school-notes` tool (hourly or in the owner's `school-notes chat`). New module *Working in a school-notes run* (`instructions/school-notes-run.md`, removed in 1.22.0): run files (`fetch.json`, `changes.json`, `check.json`, `result.json`), MCP tools, where the writer may write, stable order. The tool files sources (at most 2000 px JPEG, notebook PDF as page images), computes hashes, writes machine frontmatter, generates the index blocks and `public.json`, keeps review-file state and evidence records, generates and inserts images, commits, pushes and publishes; the corresponding v1 bookkeeping rules are removed from the writer's modules.
- Wiki data: topic pages carry `chapter` and a sparse `order`; the subject index keeps a `chapters` list; lesson-notes pages use `lessons` (date | date_note | title | topics | optional anchor) instead of `lesson_dates`; the lessons table has four columns and is generated. The public site is the wiki 1:1 without the files of `sources/` and `references/`, which are never linked publicly. The order of existing lists never changes between runs (owner rule, 2026-10-03).
- Removed: `tools/banner.py` (headers are image plans generated through MCP), the task-execution module from the ingest reading map, the `docs/evidence/index.md` pointer (records are computed per page). `.gitignore`: `.school-notes/` and renderer logs.
- Migration: the v2 migration (`python -m school_notes2.migration`) converts indexes and page fields; then synchronize the shared set (byte-identical) and record this release.

## 1.15.7 — 2026-10-01

- Preserve explicitly authorized private notebook/teacher-to-learn photo originals byte-for-byte, with verified archive and prepared-copy hashes. Git `sources/` still contains the metadata-free prepared photo. The original archive is append-only and excluded from public derivatives; archive authorization grants no new sharing permission. Teacher-background and book/reference originals and conversions remain local and never enter Drive archives or exports.
- Migration: synchronize the shared set and record its commit. The obsolete automatic disposal of incoming originals is replaced by explicit archival/disposition handling to preserve evidence. Existing source bytes/hashes are immutable; do not re-encode archived photos or claim earlier originals are recoverable. This release creates no archive, OAuth grant, sharing permission or public publication by itself.

## 1.15.6 — 2026-09-30

- Keep the textbook label exactly “Based on the textbook” / “A tankönyv alapján”. Explain its meaning once in the root legend; omit repetitive source-absence and independent-wording qualifiers from individual labels.
- Migration: synchronize the shared set and record its commit. In authorized learner pages, shorten expanded labels while preserving precise citations, source limitations needed for learning, and distinct author/correction labels. Regenerate affected web/PDF derivatives. Raw evidence and historical reports remain unchanged.

## 1.15.5 — 2026-09-30

- Textbook-derived explanations use the label “Based on the textbook” / “A tankönyv alapján”, with source locations and independent wording. The label must not imply verbatim quotation or permission to copy restricted material.
- Migration: synchronize the shared set and the local wording label; update learner-facing labels and regenerate affected web/PDF derivatives. Preserve raw evidence and citations. This wording change does not grant rights to reproduce sources.

## 1.15.4 — 2026-09-29

- Printable notes carry the explicitly approved content license in page footers and a compact closing notice, preserving third-party exceptions. Project introductions and site menus expose the same terms.
- Migration: copy the shared set; select the content license only in initialized local publication configuration. Regenerate affected PDFs and verify notices, pagination and asset credits. The template chooses no license for learner content.

## 1.15.3 — 2026-09-29

- Printable notes use a consistent typographic hierarchy: explanations retain full text size, while source/author labels are secondary but readable. Running titles, dates and page numbers support printed use; exact revision hashes move to PDF metadata, filenames and private receipts.
- The optional renderer bundles Adobe Source Sans 3 under OFL 1.1, uses local fonts without network loading or system installation, and includes font bytes in PDF cache keys. Technical diagrams and mathematical rendering remain unchanged.
- Migration: synchronize the shared policy set and record this release/commit. Update the separately pinned renderer; all PDFs need regeneration and visual review after this typography change. No Markdown lesson rewrite or public publication is authorized.

## 1.15.2 — 2026-09-29

- Keep routine image resizing/conversion/compression details in private provenance or comments, not learner captions. Visible creator/source/license credits and required notices for material changes remain.
- The optional web renderer supports unchanged official GIF symbols and strips only the known standard SVG 1.1 declaration before safe parsing of Graphviz/Matplotlib drawings. Other DTDs, entities and active content remain rejected.
- Migration: synchronize the shared set and record this release/commit in active profiles. Update the separately pinned renderer when using the web preview. No rights, content-publication authorization or raw-source retention policy changes.

## 1.15.1 — 2026-09-29

- Remove the class-material image embedding exception. Teacher/textbook images remain private evidence; learner pages and derivatives use independent authored visuals or independently acquired, verified reusable originals.
- Require file-specific license checks, visible portable credits and factual review of replacement images. Do not replace authentic object recognition or prescribed signs with generated lookalikes; do not infer rights from AI generation.
- Add a generic public GitHub issue form and reader-report handling rule; no automatic issue triage is installed.
- Migration: synchronize the full shared set and update profiles/version/commit. Remove the obsolete `class-image caption` wording row. Audit legacy `wiki/assets/orai/` uses and all renamed/copied equivalents; replace dependent captions, exercises and links along with images. Keep acquired sources and historical evidence immutable. Frozen archive repositories keep their historical release; apply the update in active successors. No site-wide content license or public publication is authorized by this release.

## 1.15.0 — 2026-09-29

- Split shared policy into task-routed modules behind a short, harness-neutral AGENTS.md. Preserve the released 1.14.8 learning, evidence, curriculum, privacy and standardized-symbol requirements; record section hashes and deliberate wording changes in `instructions/policy-migration-1.15.0.json`.
- Add a compact operation workflow: bounded rule retrieval, dependency-aware work, honest progress, source/visual checks and verified authorized delivery. No mandatory task JSON registry, completion gate, scheduler, runtime patch or automatic restart is installed.
- Add an optional pinned repository-local Markdown preview and structural checker with reusable render receipts. It supports phone/desktop, MathJax, Mermaid, disclosures and offline local images; it is not a factual approval or proof of production-site/PDF rendering.
- Opus review refinements: ingest always loads diagram-preservation rules; missing formula rendering blocks completion for affected pages; publication guidance, rule links and initialization wording are consistent. Renderer evidence-hash rejection has a regression test.
- Migration: copy the complete shared manifest through Git, preserve learner profiles and authorization scope, update named-rule references and record this exact template commit. The template remains uninitialized. No VM, agent runtime, site deployment or source migration is part of this release.

## 1.14.8 - 2026-09-29

* Require verified standard artwork for prescribed signs and symbols. Removed the simplified/not-official look-alike fallback for teaching real sign recognition; unavailable artwork is handled with text, an authoritative link and a recorded gap.
* Added cross-subject checks for system/version, sign identity, reuse provenance, exact appearance, dark backgrounds, generated-image composition and correct meaning.
* **Migration**: synchronize the shared files, record this release and exact template commit, and review affected teaching visuals within the authorized content scope. Existing media budgets, source records and agent configuration are unchanged. The separate 1.15.0 draft is not part of this release.

## 1.14.7 - 2026-09-28

* Added explicit `learning_image.py check --provider`: a read-only authenticated key-limit check with whitelisted output, redacted errors and no redirects or image generation. Plain `check` remains offline.
* Documented protected per-user credential files and cumulative incoming-lesson budgets without resetting previous request state. No Hermes program, global skill or role changes.
* **Migration**: synchronize shared files and record version/commit. Existing request IDs, credentials and ledgers remain valid; optional verification does not change them.

## 1.14.6 - 2026-09-28

* Added optional lossless WebP publication for generated infographics, with decoded pixel equality and a separate reviewed publication hash. No resizing, paid generation or SVG conversion occurs during compression.
* **Migration**: synchronize shared files and record version/commit. Existing accepted PNG jobs and evidence remain valid; converting their publication files is a separate authorized migration, with old/new hashes and link updates.

## 1.14.5 - 2026-09-28

* Added an optional, hash-reviewed WebP publication preview for generated banners; original resolution and source candidate are retained, with no additional paid generation. Exact diagrams and infographics retain their existing format.
* Clarified authorized whole-subject maintenance as a repository workflow usable by the current writing agent, independent of future bot separation.
* **Migration**: synchronize shared files and record version/commit. No automatic legacy-image rewrite, history rewrite, service change or paid batch. Existing PNG jobs remain compatible.

## 1.14.4 - 2026-09-28

* Subject tables of contents also have a wide, low subject-level banner after their text heading, before navigation. Choose a motif from the subject's actual scope; keep navigation readable and apply the existing visual checks and spending limits.
* The deterministic banner fallback supports subject indexes without frontmatter, with distinct asset names and preservation of custom headers. Root indexes, logs and operational/reference catalogs are outside this requirement.
* **Migration**: synchronize shared files and record version/commit. Apply on new or explicitly authorized indexes; no automatic paid batch, learner-content copying or agent configuration.

## 1.14.3 - 2026-09-28

* Strengthened explanation order with context before use, precise referents and a learner reading-order review. Essential prerequisites are explained where needed rather than deferred to links or later sections.
* Distinguished source omissions, unreadable captures, exercise unknowns and modeling choices. Require the exact missing detail, its source and immediate supported resolution or consequence; preserve source fidelity and visible material uncertainty without editorial clutter on diagrams.
* Added practical examples to note formatting and carried the same checks into media planning and precise-visual guidance.
* **Migration**: synchronize shared files and record version/commit. Apply the clarification review to authorized notes; no automatic whole-wiki rewrite, image regeneration, installation or agent configuration. Template remains uninitialized.

## 1.14.2 - 2026-09-28

* Added an opt-in Hermes Docker tutor integration probe: actual file reads/write denial, cross-checkout and host canaries, local-image resolution, effective tools and container mounts. It uses the installed Hermes runtime without changing it or calling a model.
* Documented invocation, native profile scratch/cache mounts, test limits and the distinction between a configured tutor pilot and a deployed Discord bot. The probe's synthetic host fixture is explicitly outside Hermes's redirected temporary cache.
* **Migration**: synchronize the shared files and record the revision. Hermes and Docker remain optional; the probe is operator-invoked, not a daily note workflow. No automatic installation, profile activation or lesson change.

## 1.14.1 - 2026-09-28

* Added short repository-owned `study-notes`, `ingest-notes` and `learning-media` skill entries alongside `learning-visuals`. Existing shared policies remain their authoritative references; no global skill installation is required.
* Added the optional role/capability matrix and staged tutor-pilot guide. Skill discovery, tool availability and enforced access are distinct; the guide explicitly identifies unverified deployment boundaries and executor limits.
* **Migration**: synchronize the shared set and record the release/commit. Documentation only: no automatic profile creation, project trust, Docker installation, credential transfer, paid call or lesson change. The template stays uninitialized.

## 1.14.0 - 2026-09-28

* Added an optional, repository-owned visual runner for trusted Python/Matplotlib, Graphviz, PlantUML, POV-Ray and FreeCAD sources. It records hashes, outputs and timing, bounds execution, preserves existing output and leaves visual/subject review explicitly pending. It installs nothing, publishes nothing and is not a sandbox.
* Added locked optional Matplotlib/NumPy dependencies, a machine-local runtime path example, execution-contract tests and reproducible Matplotlib/PlantUML/FreeCAD samples. External programs use documented package-manager or verified official-distribution installation.
* Added a thin cross-agent `learning-visuals` project skill pointing to existing policy owners. Hermes profile/tool configuration remains optional deployment work; no global or bundled skill modification is required.
* Corrected the remaining stale human-feedback sentence for the previous nine samples; new runner samples have their own pending human-review status.
* **Migration**: synchronize the full shared set, record the release/commit, and install optional runtimes only for authorized machines/tasks using `instructions/install-visual-tools.md`. Ordinary note tools retain their dependencies. Local renderer paths and output caches are ignored. No automatic lesson change, paid call, agent configuration or credential transfer.


## 1.13.6 - 2026-09-28

* Added a context-sensitive visual decision process, executable drawing specifications, an open capability-based toolkit (including Matplotlib and PlantUML), faithful fallbacks and reusable planning/review prompts. Professional correctness applies across learning levels; artistic and precise representations are chosen by their task, without a subject/type whitelist or universal tool ranking.
* Consolidated detailed representation selection and form-specific constraints in `instructions/technical-visuals.md`; media workflows retain scope, delivery/style and the existing compact record. Replaced the former five-row selection table with the fuller guide; its safeguards remain. No source-preservation, image QA, animation or feedback rule was removed.
* Applied Astra xhigh planning and Fable high document-review corrections: implicit visual claims, two-way suitability, historical time/space uncertainty, numerical/formal checks, viewer-aware fallbacks and no duplicate mandatory planning records. Recorded acceptance of the nine additional pilot samples.
* **Migration**: synchronize the shared set and record the revision. Documentation and prompt change only; no new runtime dependency, installation, model access or automatic lesson regeneration. The template stays uninitialized.

## 1.13.5 - 2026-09-28

* Added a second optional gallery with three Graphviz relationship/decision diagrams, three headless FreeCAD models with TechDraw views and three genuinely spatial POV-Ray scenes. Sources, checked previews and bounded measurements are reproducible from the checkout.
* Recorded positive feedback on the original three samples, including the request for spatial POV-Ray examples. The nine new examples await separate human feedback; no lesson replacement or runtime deployment follows from them.
* **Migration**: synchronize the shared set and record the template revision. No rule removal, new dependency, addon, secret or installation step is required for ordinary wiki use.

## 1.13.4 - 2026-09-28

* Added tool-independent checks for precision-dependent visual details, distinguishing geometry, notation, final rendering and animation behavior. Preserve the existing source/evidence workflow.
* Added optional reproducible Graphviz, FreeCAD headless and POV-Ray examples with a local gallery, measured results and explicit verification limits. These install nothing and do not replace learner content.
* Track requested human sample review separately from automated checks; no implicit viewing or acceptance.
* **Migration**: synchronize the shared set and record the revision. No new runtime, addon, credential or agent configuration is required; no automatic content regeneration.

## 1.13.3 - 2026-09-28

* Generalized preservation from technical drawings to all precision-dependent teaching structures, including mathematical and linguistic analyses. Preserve classroom notation, source cases/order and meaningful orientation through the existing coverage check. A generative redraw is not preservation; composites retain the exact authored layer and the accessible separate diagram.
* Explicitly permit a useful supplementary infographic in every subject. Adapt style and palette to supported topic context and related image series, preserving legibility and semantic notation instead of imposing subject-wide visual stereotypes.
* Added compact banner/infographic design decisions for viewpoint, comparison, hierarchy, abstraction, density, emotional tone, accessibility and implied visual claims. These map to existing job fields and relevant prompt/QA stages, not a new mandatory form or curriculum retrieval cycle.
* Incorporates the requested Astra xhigh curriculum-based planning supplement and Fable high critique. No generator API, credentials, agent installation or paid retry policy changed.
* **Migration**: synchronize the shared set and record the template revision. Apply the guidance to authorized new or changed visuals; this release does not trigger bulk regeneration. The template remains uninitialized.

## 1.13.2 - 2026-09-28

* Preserve every instructional technical drawing from notebook/teacher material in precise editable form, with source-to-page coverage checks. Generated infographics may add understanding but never replace those drawings; the rule applies across subjects.
* Choose realistic illustrative examples whose problem or contrast makes the taught relationship useful. Apply the same criterion during planning and final-image review, including banners.
* **Migration**: synchronize the shared files and record the template revision. No automatic regeneration or broad content rewrite is required; apply coverage checks when ingesting or changing the relevant pages.

## 1.13.1 - 2026-09-28

* Removed the remaining system-deployment documentation mandate from AGENTS.md. Daily note workflows stay in the agent rules; installation, configuration and rollback documentation remain discoverable through README and the system handbook.
* No executable behavior or lesson content changed. **Migration**: synchronize the shared set and record the template revision.

## 1.13.0 - 2026-09-28

* Optional image generation now starts from a repository-owned nonsecret policy and disabled example; relative paths resolve against that policy. No global active index or installed agent skill is required. Explicit legacy `--config` remains supported.
* Added read-only `check`/`status`, explicit new-request state initialization, portable attempt-artifact lookup and cold-start command-line tests. Missing state never grants a fresh balance. Existing request history and unknown charges survive relocation.
* New jobs may specify output language; old jobs preserve their original prompt. Clarified the fixed supported image model instead of advertising an ignored environment setting.
* Drive programs run directly from the checkout, with optional `--config-dir` for existing private credentials/state; fresh setups default to ignored project state. No credential migration is implicit.
* Removed global image/Drive skill adapters and the image-skill installer. Their instruction content is available in repository guides; no teaching rule was removed. Removed the Hermes-specific deployment paragraph from AGENTS.md: installation/security procedures belong in installation documentation, not the agent-neutral lesson rules.
* **Migration**: synchronize this shared release through Git, remove the two obsolete skill adapters, image installer and its test from initialized repositories, and update profile references. Keep local policy, secrets and persistent state separate from shared files. Existing global adapters require a separately recorded, exact-binding cleanup; never remove unrelated skills or reset accounts. Do not overwrite a local credential file from the changed `.env.example`.
* **Rollback**: repository changes are reversible through Git. Preserve all state and credentials. Pre-1.13 image code cannot read new relative attempt folders without a reviewed path-only compatibility migration; do not roll back and discard the ledger.

## 1.12.2 - 2026-09-28

* Require Git deployment for all repository content; only Hermes-local configuration is an exception. This replaces the ad hoc terminal-copy path used in the pilot, not the content or spending rules.
* Added a versioned, idempotent skill-binding installer and a concrete clone/update/configure/verify/restore guide. The installer rejects uncommitted skill content and refuses to overwrite existing different bindings; it makes no network or paid call.
* **Migration**: synchronize the shared set through Git, preserve any deployment working changes, bind the skill from the committed checkout, and record remaining deployment/rebuild checks separately.

## 1.12.1 - 2026-09-28

* Missing credentials now fail before a cost reservation or network attempt; a regression check covers the deployment failure found during the Hermes pilot.
* Added explicit private active-policy discovery for installed agents and a single-writer budget handoff when execution moves between machines. Deployment settings remain separate from the shared skill.
* Corrected the installation inventory to reflect the implemented image executor; registry/CLI checks remain distinct from Discord end-to-end checks.
* **Migration**: sync the shared set, update the installed skill, and maintain the private active-policy index without expanding authorization.

## 1.12.0 - 2026-09-28

* Applied the accepted Astra visual plan: task-led banner/infographic decisions, standalone context, conditional visual forms, checked transfer examples, and source-grounded final-image QA. Precise SVG/code remains the choice where exact relationships or geometry matter.
* Reuse the lesson's valid curriculum scope; retrieve new requirements only for unresolved priority/depth/applicability. Added banner and prompt-assembly stages; clarified the best-usable-candidate stopping rule.
* Added the common runnable image executor, persistent spending/attempt ledger, source/path checks, direct-review gate, recovery and synthetic tests. Added a thin Hermes skill and reproducible execution/configuration guide; this is not a claim of live Discord role rollout.
* Removed contradictory automatic-Mermaid/rare-header requirements. Later explicit subject-wide requests supersede the earlier two-page pilot scope; no other migration is implied.
* **Migration**: sync every manifest file, keep the template uninitialized, configure private execution policy outside Git, and apply only the authorized subject migration. Preserve acquired sources and accepted suitable images.

## 1.11.9 - 2026-09-28

* Open questions are always sequential numbered Markdown items, each grouping its own context, concrete uncertainty, relevant alternatives/explanation and recommendation or next step. Depth is proportional; no artificial alternatives or empty sections.
* Added a reusable open-question example. Continue the two-page preview; no bulk rewrite or changes to learning facts.

## 1.11.8 - 2026-09-28

* Added one opening break and two closing breaks inside expandable answers, following the user's GitHub preview feedback. Closed questions remain compact; spacing within multi-part answers stays unchanged.
* **Migration**: synchronize the shared rule and examples, then update only the two authorized preview pages. No teaching content or image changes.

## 1.11.7 - 2026-09-28

* Clarified that image generation is not itself an agent-added explanation. Replaced the blanket image author footer from 1.11.6 with scoped content provenance; technical maker credits stay in evidence/comments.
* Source labels now explicitly attach to the affected passage or named image content. Mixed-source images identify the reference-only contribution rather than labeling the entire image indiscriminately.
* Indented expandable answers with the shared HTML wrapper and reduced spacing inside mixed answers to ordinary paragraph gaps. Only the end of an answer gets the optional extra break.
* **Migration**: synchronize shared rules/examples and apply to the same two-page preview only. Keep existing sources, assets and teaching facts unchanged; no new paid generation or bulk migration.

## 1.11.6 - 2026-09-28

* Restored explicit semantic icons beside machine-authorship labels: `💡 Drax🤖 magyarázata`, `➕ Drax🤖 kiegészítése`, `⚠️ Drax🤖 javítása`, using the actual author and localized role. Textbook/background labels keep 📗 and their sources; lesson content remains the unlabeled default.
* Replaced the mandatory bold label at the start of a callout with a small trailing label. This intentional layout change preserves the distinction between explanation, addition, correction and reference content; it does not erase provenance or rename earlier authors.
* Added shared note-formatting examples for small metadata, spacious sections, image captions and mixed expandable answers. Self-tests keep their spacing inside the disclosure and do not acquire an author label for ordinary answers.
* **Migration**: synchronize shared files, localized Wording and the root legend. Apply the page layout only to requested pages; the first preview covers Mezopotamia and Hammurapi. Existing other pages remain valid during staged migration. No new ingest, image generation, bulk rewrite or PDF build is triggered. Keep the template uninitialized.

## 1.11.5 - 2026-09-28

* Added an open, learning-task-led visual repertoire and explicit OTHER/ELSE path, including custom/mixed forms, reuse and no new image. Topology applies only when relationships matter; reciprocal flows are not automatically a cycle.
* Added the requested Astra xhigh research rationale and revised planning, generation, review and role-handoff prompts. Rich meaningful illustrations remain supported.
* Made the existing arrow review explicit per edge: source, arrowhead/direction, target, label and condition, compared with evidence rather than only the prompt.
* **Migration**: synchronize shared files and local template references. Apply to authorized generation/review; no new generation is triggered by this update.

## 1.11.4 - 2026-09-28

* Historical notes and standalone media establish verified time and geographical context at the beginning. A readable banner may repeat it; the body must retain it.
* Infographic planning now chooses composition by semantic structure, compares accepted relevant examples, and checks whole-system understanding separately from individual arrows. Record prompt-design failures and learner feedback before retrying; preserve budget and orientation rules.
* **Migration**: synchronize the shared set and record the template commit in local profiles. Apply on new or revisited content; no bulk rewrite, banner regeneration or additional paid run is authorized by this release. Keep the template uninitialized.

## 1.11.3 - 2026-09-28

* Added *Ask self-contained, useful questions*: context, concrete uncertainty/problem, genuine alternatives where helpful, and an evidence-based recommendation or next step. Applies to conversation, note questions, review and handoff; self-tests keep their solutions hidden.
* Reconciled the previously authorized 1.11.2 handwriting rule into the template without removing the index-only or evidence safeguards.
* **Migration**: synchronize the full shared set and record this release and exact template commit in local profiles. Apply the question rule when creating or revisiting relevant questions; this does not authorize a bulk content rewrite or change every page's label layout. Keep the template uninitialized.

## 1.11.2 - 2026-09-27

* *Reading handwritten sources*: readings are resolved from context and subject knowledge before they become open questions, in every subject (recalculation, unit conversion, arrows and later steps, table and sign patterns, sentence meaning, textbook and standard facts). Visible slips stay visible on the Source summary and get a *correction* or *addition* label on the topic page; open questions remain only for doubts that change what is learned. Reviewers apply the same test.
* **Migration**: copy the shared set. Existing open questions may be re-examined under the new rule during the next review; resolved ones move to labeled content, never silently.

## 1.11.1 - 2026-09-27

* Restored the accidentally removed *Index-only books* rule verbatim. Existing index-only restrictions and profile decisions remain in force.
* Clarified that textbook-only labels exclude content also present in teacher material to learn, and that apparent source contradictions require reopening the original notebook photo before treating its earlier transcription as evidence.
* Added a shared review-closure workflow for correcting agents and reviewers, with archived reports, correction commits, evidence and separately recorded unresolved questions. Added explicit semantic-removal and profile-reference checks to template migration.
* **Migration**: copy the full shared set, update the applied release and exact template commit in local profiles, and preserve each learner's settings. Do not mark an old report resolved without performing its relevant checks. The template remains uninitialized; it receives no learner evidence or review index.

## 1.11.0 - 2026-09-27

* Added the system handbook for learning, blog preparation, operating lookup and full-system reconstruction, including Hermes roles/routing, repositories, media, Drive and scheduled review. Distinguish live components from plans and retain private deployment facts separately.
* Added the reproducible Drive OAuth helper, bounded media uploader and Hermes skill. Uploads use configured learner destinations/outboxes, private durable request records, preallocated Drive IDs, resumable transfers and complete SHA-256 readback. Sharing and deletion are not implemented; shared-user shell access is not OS isolation.
* **Migration**: synchronize the complete shared set; configure credentials, actual folder IDs and outboxes outside Git; install both skill and script following `instructions/install-drive.md`. Never overwrite an existing token/config/ledger during an update. Preserve the template's uninitialized profile. Run unit tests and destination checks before enabling the skill; intended-reader access and separate bot executors remain independent checks.

## 1.10.0 - 2026-09-27

* Shared files are strictly identical and listed once in `shared-files.json`; `tools/check_shared.py` reports missing or divergent files against a local template checkout. Local configuration never belongs in shared policy or code.
* Reusable media planning, prompt and handoff instructions now live in `instructions/` and ship to every linked wiki. Family deployment records remain private and do not imply installed tools or spending authority.
* Banner wording, colors, currency mark and optional decorative symbols live in `tools/subjects.json`. Reference-index wording lives in `tools/book-index.json`. The common indexer preserves checked README overrides (`--readme` or the existing marker) and both English/Hungarian offset recognition.
* **Migration**: preserve existing configuration, source data, evidence and generated assets. Extract local hard-coded banner settings before replacing the tool; move local reference listings out of shared README files into local indexes. Copy every file listed by the manifest, record the same canonical template URL/version/commit structure in each profile and template link in each README, then run the shared-file checker and relevant tool regression tests. Do not regenerate teaching pages or assets merely to synchronize tools. The template remains uninitialized with empty subjects and no tracked learner references.

## 1.9.0 - 2026-09-27

* Added direct visual-evidence checks, optional conversion diagnostics, notebook-first image ordering, shared reviewer evidence and learning-value selection of teacher images. Original teaching files receive visible links; dated source filenames no longer imply completed ingest.
* Added curriculum-aware scope and bounded reference navigation, selective SVG/raster visuals with actual-image descriptions, bounded ingest-time infographic generation and printable A4 study notes. Existing precise diagrams remain valid; no blanket replacement or automatic paid batch is implied.
* Added optional media environment placeholders and standard-library curriculum tools with synthetic regression tests. The public template includes no private source collections, family plans or media-trial evidence.
* **Migration**: merge these shared rule changes with local school rules rather than replacing local profiles or teaching pages. Copy `tools/curriculum.py`, `tools/test_curriculum.py`, `references/curriculum/README.md` and the updated source-status guidance. Configure learner-specific requirements and any media access explicitly in `PROFILE.md`; retain existing subject/banner settings. Do not copy another learner's professional package or create empty evidence indexes. No existing notes or assets need rewriting solely to adopt this version.

## 1.8.0 - 2026-09-27

* The tools became a uv project: `pyproject.toml` and `uv.lock` (shared files) list their Python dependencies (Pillow, python-pptx, python-docx), and every tool runs with `uv run tools/<name>.py` - no `pip install` or system packages. New *Tools* rule under *Sources*; all tool commands in `AGENTS.md` now use `uv run`. `.venv/` is gitignored.
* *Teacher materials*: a teacher's material may be uploaded pre-converted - a dated `sources/` directory with the original file, `document.md`, and `figures/`; the conversion stays next to the original (the original is authoritative and hashed). When a book's `figures/` are missing, the description is only a guide and a doubtful reading needs *Requesting a page*.
* **Migration**: copy `AGENTS.md`, `pyproject.toml`, and `uv.lock`; add `.venv/` to `.gitignore`; make sure `uv` is installed where the agent runs. In agent prompts and scheduled jobs, replace `python3 tools/...` with `uv run tools/...`.

## 1.7.1 - 2026-09-27

* *Reading a book*: book figures are opened only for a specific check and only when `document.md` describes them; figures without any description or printed text, and image files `document.md` does not reference (barcodes, logos, QR codes, decoration), are never opened.
* **Migration**: copy `AGENTS.md`.

## 1.7.0 - 2026-09-27

* New *Sources* rule: photos are filed with the new shared tool `tools/prepare_photo.py` - same resolution, upright, JPEG quality 90, all metadata (GPS, device, date) removed; the stored copy is the source (read at ingest, checked by the review, hashed). Keeps the repository growing several times slower and strips location data.
* **Migration**: copy `AGENTS.md` and `tools/prepare_photo.py` (needs Pillow; `pillow-heif` optional for iPhone HEIC). Existing photos stay as they are - their hashes are recorded. If an agent's channel prompt says to copy incoming files into `sources/`, change it to file photos with the script.

## 1.6.1 - 2026-09-27

* *Teacher materials*: images from material to learn may be used where they teach and our own drawing could not replace them (maps, complex diagrams, historical objects and artworks, buildings, sites and rooms, experiment photos, cross-sections); never decorative, never from the textbook or background material. They go to `wiki/assets/orai/` with the *class-image caption*; for maps, objects, artworks and places a freely licensed image (Wikimedia Commons) is preferred.
* **Migration**: copy `AGENTS.md`; add the *class-image caption* key to the *Wording* table in `PROFILE.md` (translated).

## 1.6.0 - 2026-09-27

* New *Teacher materials* rule under *Sources*: material a teacher shares (pptx, pdf, docx, photo of a handout) is either *to learn* - a source like the notebook, its content on the topic pages with lesson lines and footnotes, no label - or *background* - a reference with its map, labeled with the new *background label*. The student names the kind with one word when sending; if it is missing, the LLM asks before ingesting, even under automatic ingest, and offers its own guess. The notebook itself is always material to learn.
* **Migration**: copy `AGENTS.md`; add the *background label* and *teacher-material words* keys to the *Wording* table in `PROFILE.md` (translated); add the background label to the *legend* section of the root index. If an agent's channel prompt says that every file sent is a source, add: "except teacher materials - follow the Teacher materials rule of AGENTS.md (ask before ingesting when the kind is not given)".

## 1.5.0 - 2026-09-26

* New *Reading a book* rule under *References*: a converted book is never loaded whole; its generated `index.md` maps every lesson and printed page to a line range of `document.md` and points to the book's own contents, indexes, and answer key, and only the needed lines are opened. New shared tool `tools/book_index.py` builds the map from the page anchors and the book's own table of contents (README lesson table as fallback).
* **Migration**: copy `AGENTS.md`, `references/README.md`, and `tools/book_index.py`; run `python3 tools/book_index.py references/<subject>/<book-id>` for every converted book (a README without an offset line needs `--offset N`, or add "printed-page offset: N" to it); check a few lesson ranges against the book; commit the `index.md` files. Index-only books need nothing.

## 1.4.0 - 2026-09-26

* *References*: new **index-only books** - a book that may not be converted (e.g. the publisher forbids processing it with AI) gets only a hand-made index in its `README.md` (table of contents and subject index: numbers and titles, no text); textbook lines come from it, with the new *index-based note* when the section is chosen by topic. New **Requesting a page** rule: when the notes cannot be understood or checked without a page of an unconverted book, the LLM names the exact page and asks for a photo; the photo is not a source - used only for the check, never stored in the repository, its chat message deleted afterwards; what comes over gets the *textbook label*.
* **Migration**: copy `AGENTS.md`; add the *index-based note* key to the *Wording* table in `PROFILE.md` (translated). If a book-specific local decision already covers this, keep only its book-specific facts in `PROFILE.md` or the book's reference `README.md`. If an agent's channel or system prompt says that every file sent is a source, add the exception for requested pages (point it at *Requesting a page* in `AGENTS.md`).

## 1.3.0 - 2026-09-26

* Topic pages now show what was taught in class and what only the textbook adds: textbook-only content gets the new *textbook label* (`📗`, a `> [!NOTE]` callout or inline, also in the *in short* box and chapter summaries); a mere confirmation or page reference stays a footnote. New *When was it taught* rule: every topic-page section built from notebook content opens with the *lesson line* (`🗓️` + the lesson date), and the page follows the order of the lessons.
* **Migration**: copy `AGENTS.md`; add the *textbook label* and *lesson line* keys to the *Wording* table in `PROFILE.md` (translated into the wiki language); add 📗 and 🗓️ to the *legend* section of the root index; then go through every topic page and chapter summary: label every textbook-only statement (sections, tables, *in short* bullets, quiz answers), and add lesson lines to the notebook-based sections (dates from the lesson-notes pages and the *lessons* tables).

## 1.2.0 - 2026-09-26

* *Source summary* update semantics clarified: write-once applies to the source's content; a wrong or incomplete *reading* (misread number, skipped line, inferred unit) is fixed in place, and the fix is recorded only in `log.md` and git.
* New content rule *Pages show the current state, not their history*: no remarks about earlier versions, correction appendices, or review rounds on wiki pages.
* New *Reading handwritten sources* rule (transcribe first, zoom, keep the notebook's exact form, uncertain readings to open questions) and a mandatory *Self-check* at the end of every ingest or correction (two-way coverage ledger, provenance on every surface, formulas, drawings, links). The Ingest workflow gained the self-check as a step.
* **Migration**: copy `AGENTS.md`; then search the wiki for correction appendices and history remarks (e.g. "korábban", "korábbi", "helyesbít", "previously", "corrected") and fold their content into the main text of the page, removing the remarks; the history stays in `log.md`. Record the version in `PROFILE.md`.

## 1.1.0 - 2026-09-26

* The wiki-specific sections moved out of `AGENTS.md` into a new `PROFILE.md`: *Setup*, *Standing authorizations*, *Wording*, plus new *Template* and *Local decisions* sections. `AGENTS.md` is now the same in every wiki; bootstrap fills `PROFILE.md` instead of editing `AGENTS.md`. `CLAUDE.md` imports both files.
* New rule *Template updates*: updating is opt-in, only on the user's instruction; local changes to shared files are shown and never overwritten silently.
* **Migration** (for a wiki bootstrapped from 1.0.0): create `PROFILE.md` from the template's, move the filled-in *Setup*, *Standing authorizations*, and *Wording* sections from the wiki's `AGENTS.md` into it (keeping their content), record the version; then replace `AGENTS.md` and `CLAUDE.md` with the template's.

## 1.0.0 - 2026-09-26

* First version of the template.
