# Note formatting and provenance labels

Use the localized strings in [PROFILE.md](../PROFILE.md) and the content rules in the [content rules](content-and-curriculum.md). These examples implement the compact label layout without changing source categories, content authorship or the learning content. Existing pages are migrated only in the authorized scope; a rule update does not trigger a whole-wiki rewrite. Apply to the current user-authorized migration scope; the earlier two-page pilot does not restrict a later explicitly requested subject-wide migration.

## Meaning before styling

| Marker | Meaning |
|---|---|
| 💡 | Explanation of the taught content |
| ➕ | An addition beyond the supplied lesson |
| ⚠️ | A correction, with the reason; the original source claim is quoted in the footnote |
| 📗 | Textbook-only or background material, as specified by the label |
| 🤖 | Machine authorship; combine with the relevant role icon, never a quality or verification badge |

Use the semantic icon and the uniform, model-free machine role: `💡 🤖 gépi magyarázat`, `➕ 🤖 gépi kiegészítés`, `⚠️ 🤖 gépi javítás`. One label follows a continuous passage of the same kind, at a change of content kind, not every paragraph. Exact model and authorship stay in evidence; the correction label stays permanently. Pure notebook or teacher material to learn needs no redundant source label. Preserve citations everywhere, including mixed-source passages.

## Compact textbook label

Use exactly the localized textbook label from PROFILE, in Hungarian `📗 A tankönyv alapján`. Do not append boilerplate such as `(a füzetben nincs)` or `saját megfogalmazás`, or turn the label into an editorial explanation. The root legend explains the source category once. Put precise book/page locations in citations or the existing textbook metadata line, not inside the label. Independently necessary explanation/correction labels retain their scope; exact authorship stays in evidence. Keep pedagogically relevant limits in subject terms in the teaching prose; source observations belong in private footnotes/evidence. This compact wording does not relax independent wording, citation, no-copy or source-verification requirements; apply it consistently to topic pages, recaps, glossary cells, captions and answers.

## Context before the learner needs it

The learner should understand what each passage concerns, why it belongs here and what can be concluded, without reconstructing the editor's thinking. Introduce the necessary concepts and notation before using them. Connect a new step to what has already been explained; make a change of example, convention, source or assumption explicit when it matters. For a diagram, supply the task and how to read unfamiliar marks before expecting a conclusion. An independently usable recap, caption or expanded answer needs its own short bridge when the surrounding context is insufficient. Do not force every passage into a fixed multi-heading template or repeat already established context. Match support to prerequisites established in the reading sequence or explicitly supported by the lesson and profile; age, grade and the existence of an earlier note do not prove understanding. Supply a short local bridge for an essential prerequisite that has not been established. Adapt depth and explanation, never disciplinary accuracy. A prerequisite bridge may revisit simpler earlier material; that does not authorize an unrelated expansion ahead of the lesson. A summary-first layout remains valid: give its unfamiliar symbols or conventions a short local explanation without moving the whole course above the summary.

Use the subject's established terminology consistently; explain it without replacing it with an ambiguous everyday near-synonym. Distinguish the concept from the property being discussed. For example, a scalar torque calculation reads "a forgatónyomaték nagysága = az erő nagysága × az erőkar hossza"; define the moment-arm length as the perpendicular distance to the force's line of action. This is one example of a cross-subject rule, not a physics-only exception. Where meaning depends on a model, analysis convention, historical context, interpretive framework or religious tradition, identify the relevant frame. Examples include word class versus sentence function, author versus narrator, historical event versus a source's account, and a religious teaching versus an interpretation of it. These illustrate the principle; they are not a closed subject list or compulsory caveats for every sentence. Do not infer a learner's personal belief from the subject studied. Keep the relevant convention and conditions visible; do not introduce false precision beyond the evidence.

Use precise referents: "the length of the moment arm" rather than an unexplained "dimension"; "the date of this event" rather than a bare "date". Do not leave a reader wondering whether missing information is a deliberate puzzle. Distinguish:

* **Source omission:** state the missing quantity in subject terms and give the supported completion and basis, or the consequence of what remains unknown. Put the source location in a footnote.
* **Unreadable or incomplete capture:** record the photograph/crop limitation privately; teach only what is supported, and ask a public-safe open question when necessary. A cropped detail is not proof that the original omitted it.
* **Exercise unknown:** name what the learner must determine and the available information. Do not call an intentionally unknown result a source defect.
* **Chosen simplification or optional omission:** explain the relevant modeling limit or scope, without attributing an unverified intention to the source author.

For example: "A feladat nem adja meg az erő nagyságát; a számolásban 80 N szerepel, ezzel számolunk.[^f]" This is an example, not a fact to copy into a lesson. State any remaining limit in subject terms, and keep the exact source observation in the footnote.

Keep necessary subject-matter limits beside the relevant diagram, not printed on it. Retain symbols, intentionally unknown quantities and uncertainty indicators that carry subject meaning. Redraw a notebook drawing as the same drawing in the same role, correct; only meaning-bearing layout is binding. Correct unambiguous errors with the lasting correction label, and ask about genuinely uncertain elements. There is no "notebook reconstruction" label or reference to the notebook in the figure. Exact source wording and the change record stay in private footnotes/evidence; the topic page teaches the supported result.

**Reading-order check:** read the finished passage as a learner who has the stated prerequisites but has not seen the source or the editing conversation. At each new statement, symbol, visual or result, check: can I name what this refers to, understand why it appears, follow the reasoning so far, and distinguish given facts, derived results and remaining unknowns? Can I understand the main point without following a link merely to obtain a missing prerequisite? Repair the first confusing point where it occurs, not only in a later FAQ. This is a semantic review, not a keyword lint or a claim that every reader has understood the page. Apply it to teaching prose, summaries, captions, diagrams and expanded answers, including the subject-matter clarification of an uncertain reading. Report an imprecise term, ambiguous referent, missing condition, unsupported source completion or prerequisite introduced too late when it could change understanding. For each finding give **exact location and quoted passage → ambiguity or missing bridge → likely learner misunderstanding → smallest supported correction**. Distinguish a confirmed error, unresolved source reading and optional improvement; an explicitly stated valid convention is not an error merely because another convention is familiar. Check the source/evidence before alleging an omission. Apply *Reading handwritten sources* in [Wiki workflows](wiki-workflows.md) as well: use the whole relevant topic, calculations, units, diagrams, parallel source passages and disciplinary knowledge to resolve a suspected typo. An unambiguous supported resolution is a labeled correction/completion; several plausible readings remain an uncertainty, not a fabricated certainty. This applies to the first notebook in a new subject as well as ongoing corrections and reviews. Do not mechanically replace every short expression once its meaning is unambiguous.

## A block and its small footer

```markdown
> [!TIP]
> Az állatok is kommunikálnak. A kutya a farkcsóválással jelez.<br /><sub>💡 🤖 gépi magyarázat</sub>

<br />

> [!NOTE]
> A tankönyv megértése alapján, saját szavakkal készített, pontos forráshellyel jelölt kiegészítés.<br /><sub>📗 A tankönyv alapján</sub>
```

Keep GitHub's generated TIP/NOTE/WARNING heading; do not repeat it with a large manual heading. The model-free role appears once, in the small footer after the content. A multiline list or table gets one footer after the block, separated by a quoted blank line where Markdown needs it. For a simple paragraph, keep the `<br /><sub>...</sub>` suffix on the same Markdown source line as the text; a separate quoted line can produce a second break in GitHub. Do not introduce an empty paragraph between a simple sentence and its label. Never collapse different source categories into one footer that falsely applies to the whole block. Split passages when needed. A list item, recap bullet or table cell can end with its own `<br /><sub>...</sub>` label.

## Metadata and breathing room

Use a small metadata line. When lesson date and textbook location apply to the same section and are adjacent, combine them in lesson-first order with a middle dot; do not move a date across unrelated material simply to combine labels.

```markdown
<sub>🗓️ Óra: 2026-09-11 · 🔖 Tankönyv: 1. lecke, 12-13. oldal.</sub>
```

The `🔖 Tankönyv:` line either gives an identified lesson and page, or states that the learner's textbook does not cover the topic, naming the book by its grade (`🔖 Tankönyv: a 9. évfolyamos tankönyv ezt a témát nem tárgyalja.`); the latter is an established fact and spares the learner a search. When neither is established, leave the line out; a placeholder such as "a kapcsolódó lecke még nincs azonosítva" tells the learner nothing. The gap goes to the private evidence record, or to the open questions when the learner can help. The check warns about a 🔖 line without any lesson or page number (a digit, or a Roman numeral with "fejezet"/"lecke"), and the next fix run makes such a page an item.

Use one standalone `<br />` between substantial sections or adjacent callout blocks where needed for the agreed spacious layout. Avoid stacked breaks and a break immediately after a heading. Place a passage's label before the larger gap so it remains visibly attached to that passage. Do not shrink teaching prose, use custom CSS/colors or replace searchable labels with badge images. Rendered size and theme remain the viewer's choice.

## Expandable self-tests

```markdown
<details><summary>1. Mit állít a tanult anyag?</summary>

<dl><dd>

<br />

Az egyszerű, forráshű válasz itt áll, robotcímke nélkül.

A válaszhoz szükséges külön magyarázat.<br /><sub>💡 🤖 gépi magyarázat</sub>

A forrásban szereplő hiba helyesbítése, az indokával és hivatkozásával.<br /><sub>⚠️ 🤖 gépi javítás</sub>

<br /><br />

</dd></dl>

</details>

<details><summary>2. Mi a következő fogalom jelentése?</summary>

<dl><dd>

<br />

A rövid válasz.

<br /><br />

</dd></dl>

</details>
```

The questions remain compact when closed. The `<dl><dd>` wrapper indents only the opened answer using ordinary HTML, without a code block, visible bullet or quote color. Preserve blank lines so the answer remains Markdown. Exact indentation is viewer-dependent. Within one answer use ordinary paragraphs, not an extra standalone `<br />` between explanation and source passage; use one standalone `<br />` before the first answer paragraph and `<br /><br />` after the last paragraph, inside the wrapper. These boundary spacers are the explicit exception to avoiding stacked breaks elsewhere. Both are inside `<details>`: when closed, neither affects the spacing between questions. A question does not acquire an agent label merely because it was generated. Do not put alert syntax inside the disclosure. Preserve the distinction between the taught answer and a separate optional explanation or correction.

## Numbered open questions

Always number unresolved questions consecutively in Markdown, even if there is only one. Give each a concrete title and enough context to understand the uncertainty without searching the page. Keep the problem, relevant alternatives, their explanation and the recommendation/next step within that same numbered item. Scale detail to need: omit artificial alternatives and unnecessary subheadings, but never omit the context or what would resolve the question. Do not turn an established correction into a choice between equally valid answers. Use explicit `1.`, `2.`, `3.` markers in the file and indent continuation paragraphs by three spaces. This section is separate from self-tests; it records unresolved issues, not quiz answers. Apply the stable anchors and decisions workflow. Each kind of question occurs at most once per page; omit the section when empty. Questions name only content already readable in the public note, and say what to do until answered. A source reference needed to ask is permitted here; source locations go in private footnotes.

```markdown
# Nyitott kérdések

<!-- q: pelda-kerdes -->
1. **A konkrét tisztázandó kérdés?**

   **Kontextus:** melyik témáról, állításról vagy feladatról van szó.

   **Probléma:** mi bizonytalan, miért számít, és mit tudunk biztosan.

   **Lehetőségek:** a valóban szóba jövő változatok, indoklással és következményeikkel, ha vannak ilyenek.

   **Javaslat:** az indokolt következő lépés; milyen válasz vagy bizonyíték oldaná fel a kérdést.

<!-- q: pelda-masik -->
2. **Egy másik, önálló kérdés?** A szükséges kontextus, bizonytalanság és következő lépés röviden is elférhet egy bekezdésben.
```

## Explanatory images and exports

Distinguish **what the content is based on** from **who generated the image**. An agent arranging textbook or teacher facts visually has not thereby added a new explanation. Do not label every generated image with "Codex's explanation" or the equivalent. Keep the maker, image model and prompt in comments/evidence. A visible model-free role label is for a substantive agent-added explanation, addition or correction, attached only to that contribution. This applies equally to prose and images.

Source labels must have a clear scope. Attach a paragraph's small label to that paragraph; a NOTE block can enclose a longer reference-only explanation. For a source-based image, name the relevant content in a short caption when needed: for example, identify the two clauses being compared and which reference supports each. For a mixed-source image, identify the textbook-only part rather than tagging the whole image as textbook-only. Do not leave a generic source label floating between prose and an image, and do not use a machine label to replace factual attribution. References and prose retain the teaching meaning. Licensed teacher images keep their visible credit; source-only photos remain private. Decorative banners need no maker credit; exact model, prompt, cost, hashes and observations stay in comments/evidence. A caption-only correction does not authorize regeneration.

Keep the teaching content and source markers as ordinary text so non-GitHub viewers and future PDF rendering retain their meaning. An export may style the small labels consistently, but cannot remove their meaning or use color alone to distinguish provenance. This document defines Markdown layout, not an implemented PDF pipeline.

## Authorized whole-subject maintenance

An explicit request to update a complete subject (in the owner's `school-notes chat` session) applies these rules to its topic pages, lesson logs, chapter summaries and subject index. Inventory the scope, examine the source/evidence and relevant bounded curriculum passages, then apply semantic corrections and formatting together. Propagate a correction to summaries, quizzes and affected captions. Preserve source evidence privately and redraw required teaching diagrams as the same drawing, correct, with labeled corrections. Select banners and optional visuals by the existing visual workflow. Finish with source coverage, reading-order review, the MCP `check` and `finish`. Do not treat a formatting-only request as authorization for unrelated ingestion or a paid visual batch.
