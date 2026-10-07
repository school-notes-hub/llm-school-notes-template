# School notes wiki - profile

> **Not initialized yet.** This wiki has not been set up. Ask the LLM agent to initialize it: it follows the *Bootstrap* workflow in [Wiki workflows](instructions/wiki-workflows.md), asks the setup questions, fills in this file, retitles it, and deletes this notice.

This file holds everything that belongs to **this** wiki; the rules shared by every wiki made from the template are routed through [AGENTS.md](AGENTS.md), which refers to the sections below by name. The subjects and the banner labels live in [tools/subjects.json](tools/subjects.json); reference-index wording lives in `tools/book-index.json`.

# Template

* **Template repository**: https://github.com/dlaszlo/llm-school-notes-template (or the fork this wiki was made from).
* **Template version**: `1.22.7`.
* **Template commit**: `<exact template commit recorded at bootstrap and every template update>`.

Updates are optional and happen only when the user asks (see *Template updates* in [Wiki workflows](instructions/wiki-workflows.md)).

# Setup

*Filled in at bootstrap; each fact has exactly one home here.*

* **Student**: `<first name>` - the wiki is titled after the student's first name (e.g. "Anna's notes"), which is the only personal name the wiki may contain.
* **Grade and school year**: `<grade>` in `<school year>`.
* **Wiki language**: `<language>` (see the *Language* rule in [Wiki structure](instructions/wiki-structure.md) and the *Wording* table below).
* **Audience**: `<who reads the wiki>` - by default the student, the family, classmates the student shares it with, and anyone on the public site. None of them sees the notebook, teacher material or textbook. The personal-data audience test is applied against this readership, and every explanation is written at the level of its youngest main reader (see *Plain language*).
* **Notebook recognition**: `<which notebook belongs to which subject, as the user confirms it, e.g. "the plain spiral notebook is Science">`.
* **Standing authorizations**: the defaults in *Standing authorizations* below, as confirmed (or narrowed) by the user at bootstrap.

# Standing authorizations

The template's defaults, meant to make everyday use as automatic as possible. Bootstrap shows them to the user, who may confirm, narrow, or drop each one; record the outcome here with the date.

* **Raw sources stay unredacted**: raw sources such as exercise-book photos may stay in `sources/` unredacted even when they show grades, names, or similar personal data - no per-ingest confirmation is needed; the data still never reaches `wiki/`.
* **Automatic ingest**: ingest dropped notes (photos, files, voice notes) right away without a discussion step - pick the subject from the content or the user's word, apply the curation rule, add diagrams where they fit, then commit, push, and bring the result into `main` (fast-forward) without asking again, then delete any working branch that is fully merged into `main`, locally and on the remote; report afterwards what was done, which readings are uncertain, and what stays open. Ask first only when a real decision is the user's: an unclear subject, a secret, or data that fails the audience test.
* **Duplicate check**: before filing, compare each new file's sha256 with every `content_sha256` already recorded in `wiki/` (and search the wiki for the topic) - the user often is not sure whether a page was sent before; an identical file is not ingested again, just reported.
* **Illustrations**: a few colorful drawings per the *Illustrations* rule are part of the ingest routine.
* **Synthesis pages**: see *Synthesis pages - standing authorization* in [Wiki workflows](instructions/wiki-workflows.md).

# Wording

Every reader-facing string the rules prescribe lives here, in the wiki language - the rules refer to them by the key in the first column. The template ships with English and Hungarian; at bootstrap, keep the column of the wiki language (translate the English one for any other language) and delete the other.

| Key | English | Magyar |
|---|---|---|
| wiki title | `<Name>'s notes` | `<Név> jegyzetei` |
| back link | `[⬅️ Back to the home page](../index.md)` | `[⬅️ Vissza a kezdőlapra](../index.md)` |
| subjects (root index) | `# 📚 Subjects` | `# 📚 Tantárgyak` |
| legend (root index) | `# 🔎 Legend` | `# 🔎 Jelmagyarázat` |
| lesson-line legend (root index) | `* 🗓️ **Lesson**: which lesson taught the part; without an exact date `~` marks it, and pointing at it shows the period.` | `* 🗓️ **Óra**: melyik órán tanultátok az adott részt; ha nincs pontos dátum, `~` jelzi, az időszakot az egér rávitelekor látod.` |
| catch-up | `# 📝 To catch up` | `# 📝 Pótolandó` |
| homework | `# 📌 Homework` - columns `Deadline \| Task \| Status`, values `open` / `✅ done` | `# 📌 Házi feladat` - oszlopok `Határidő \| Feladat \| Állapot`, értékek `nyitott` / `✅ kész` |
| chapter | `# 📘 Grade <grade>: <chapter>` | `# 📘 <grade>. évfolyam: <chapter>` |
| lessons | `# 🗓️ Lessons` | `# 🗓️ Órák` |
| review | `# 🔁 Review` | `# 🔁 Ismétlés` |
| notes | `# 📝 Notes` | `# 📝 Jegyzetek` |
| undated lesson | `~late Sept` (the range in the tooltip, `Undated lesson: Sept 23 – Oct 4`) | `~szept. vége` (az időszak a súgóban: `Dátum nélküli óra: szept. 23. – okt. 4.`; részben olvasható dátumnál `Bizonytalan dátum: …`) |
| uncertain date | `~` before the approximate day (the part of the month when both bounds fall in it, else the month, else the part of the month of the lower bound); its range and reason only in the tooltip (hover; a tap on a phone): `Undated lesson: Sept 23 – Oct 4`, a partly legible date `Uncertain date: Sept 10–19`; never visible text; paper prints the approximate day without `~` and range | `~` a közelítő nap előtt (a hónaprész, ha mindkét határ abba esik, különben a hónap, különben az alsó határ hónaprésze); az időszak és az ok csak a súgóban (egérrel rámutatva, telefonon koppintva): `Dátum nélküli óra: szept. 23. – okt. 4.`, részben olvasható dátumnál `Bizonytalan dátum: szept. 10–19.`; sosem látható szövegként; papíron a közelítő nap `~` és időszak nélkül |
| where we are | `# 📍 Where we are` | `# 📍 Itt tartunk` |
| current chapter | `**Now:** <chapter> <date item>` | `**Most:** <fejezet> <dátum>` |
| latest lesson | `**Latest:** <lesson> <date item> · <topics>` | `**Legutóbb:** <óra> <dátum> · <témakörök>` |
| earlier chapters | `**Before:** <chapter> <date item> → …` | `**Előtte:** <fejezet> <dátum> → …` |
| lesson order | `So far, in this order, newest first:` | `Eddig ebben a sorrendben vettük, a legújabb elöl:` |
| lesson date | a quiet date item after the important information (small clock, small grey text): `Oct 4`, outside the school year `2025 Oct 4`, an undated lesson `~late Sept` | csendes dátum a fontos információ után (kis óra, kis szürke szöveg): `okt. 4.`, a tanéven kívül `2025. okt. 4.`, dátum nélküli óra `~szept. vége`; ISO dátum soha, teljes dátum `2026. 10. 04.` |
| chapter span | `early Sept – early Oct`, one or two dated lessons `Sept 3–10`; the current chapter `since late Sept` | `szept. eleje – okt. eleje`, egy-két datált óránál `szept. 3–10.`, egy hónapon belül `szept. eleje–közepe`; a mostani fejezet `szept. vége óta` (eleje 1-10., közepe 11-20., vége 21-) |
| textbook line | `🔖 Textbook: <lesson>, pages <pages>` | `🔖 Tankönyv: <lecke>, <oldalak>. oldal` |
| index-based note | `(from the table of contents)` | `(a tartalomjegyzék alapján)` |
| in short | `⚡ **In short**` | `⚡ **Röviden**` |
| summary title / file | `Summary: <chapter>` / `summary-<chapter-slug>.md` | `Összefoglaló: <chapter>` / `osszefoglalo-<chapter-slug>.md` |
| details link | `➡️ Details: [<title>](<page>.md)` | `➡️ Részletesen: [<title>](<page>.md)` |
| terms | `# 📖 Terms` | `# 📖 Fogalmak` |
| test yourself | `# 🧠 Test yourself` | `# 🧠 Kérdezd ki magad` |
| test yourself intro | `*Our own questions (not from the notebook) - try to answer from memory first, then open the answer.*` | `*Saját kérdések (nem a füzetből) - előbb próbáld fejből, aztán nyisd le a választ.*` |
| explanation label | `💡 🤖 machine explanation` | `💡 🤖 gépi magyarázat` |
| addition label | `➕ 🤖 machine addition` | `➕ 🤖 gépi kiegészítés` |
| textbook label | `📗 Based on the textbook` | `📗 A tankönyv alapján` |
| background label | `📗 From background material` | `📗 Háttéranyagból` |
| teacher-material words | *to learn* / *background* | `tanulni` / `olvasnivaló` |
| lesson-log heading | `# What we learned in this lesson` | `# Mit tanultunk ezen az órán` |
| lesson-log source line | `📎 Notebook: <lesson dates> · Teacher material: <name>; <name>` | `📎 Füzet: <óradátumok> · Tanári anyag: <név>; <név>` |
| undated source lesson | `undated lesson` | `dátum nélküli óra` |
| notebook correction request | `Correct this in your notebook too: <correct statements>.` | `Javítsd a füzetedben is: <helyes állítások>.` |
| lesson line | `🗓️ Lesson: <date>` | `🗓️ Óra: <dátum>` |
| correction label | `⚠️ 🤖 machine correction` | `⚠️ 🤖 gépi javítás` |
| unknown-author label | `<role icon> 🤖 machine <role>` | `<szerepikon> 🤖 gépi <szerep>` |
| machine-authorship legend | `🤖 marks a machine-authored explanation, addition or correction. It is not a verification mark.` | `A 🤖 gépi magyarázatot, kiegészítést vagy javítást jelöl. Nem hitelesítési jel.` |
| catch-up notice | `**Catch-up material** - copy this into your notebook too (or learn it), and say when you are done.` | `**Pótolandó anyag** - írd be ezt a füzetedbe is (vagy tanuld meg), és szólj, ha megvan.` |
| synthesis notice | `*This page was put together by the LLM (not from the notebook).*` | `*Ezt az oldalt az LLM állította össze (nem a füzetből).*` |
| in words | `in words:` | `szövegesen:` |
| conventional headings | `# Open questions`, `# Examples`, `# Schema`, `# Computation` | `# Nyitott kérdések`, `# Példák`, `# Séma`, `# Számítás` |

The banner labels (page kinds and the "Header" alt-text prefix) live in `tools/subjects.json` and are translated there at bootstrap.

# Local decisions

Decisions that concern this wiki only, each with its date (e.g. a house rule for a subject, an exception the user asked for). A rule change here that should apply to other wikis too is proposed to the template separately - that is the user's call.

# Learning scope and curriculum

Fill this section only with user-confirmed settings when relevant; do not infer a closed subject list, examination target, ability or personal beliefs from supplied documents.

* **Declared training and professional package**: `<if supplied; otherwise unknown>`.
* **Current lesson and learning goals**: `<the notebook, teacher material or explicit request sets the immediate core>`.
* **Requirements and applicability**: `<installed reference IDs and versions; distinguish declared training from verified cohort/examination applicability>`.
* **Depth**: accessible explanation and application first; advanced material only with a concrete learning reason and prerequisite bridge. Related cultural enrichment remains brief and optional.
* **Media settings**: `<available tools, chosen models, private delivery destination and explicitly configured spending caps; empty means not configured>`.

Keep actual credentials outside tracked files. The shared learning, image-checking, media and printable-note rules are linked from `AGENTS.md`; a role name does not establish live tool access.
