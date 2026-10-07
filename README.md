# LLM school notes - wiki template

Photograph your notebook, and an AI agent turns it into clear, curated study pages.

This is a template for a knowledge base (an "LLM wiki") built from one student's school notes. You drop in photos of exercise-book pages, downloaded notes, or voice notes; an LLM agent - [Claude Code](https://code.claude.com/), [Codex](https://developers.openai.com/codex/), or any agent that can read `AGENTS.md` (e.g. Hermes Agent) - files them, reads them, and maintains a wiki: one directory per subject, one page per topic, plus a page per set of lesson notes. The storage format is the [Open Knowledge Format 0.2](SPEC.md): plain markdown with YAML frontmatter, readable on GitHub, in Obsidian, or with `cat`.

The template contains no student identities, school, subjects, textbooks, or notes - everything specific is set up by the LLM on the first run. The shared subject cards (`subject-cards.json`) are generally worded and fit any learner of the subject. The canonical repository is [llm-school-notes-template](https://github.com/school-notes-hub/llm-school-notes-template).

## What the pages look like

* **Faithful and curated at the same time.** A lesson-notes page records exactly what the notebook says. The topic pages teach: they explain terse notes, redo worked problems step by step, fill gaps, and fix errors - every addition visibly marked as *not from the notebook* (colored callouts: 💡 explanation, ➕ addition, ⚠️ correction).
* **Two layers.** Every topic page opens with a ⚡ *In short* box for the evening before a test; chapters get a summary page; the full detail stays on the topic pages.
* **🧠 Test yourself** questions with hidden answers at the end of each topic page.
* **Plain language** at the student's level (ISO 24495-1 principles), phone-friendly tables, LaTeX math, Mermaid diagrams, and colorful header banners (`tools/banner.py`).
* **Catch-up support**: notes copied from a classmate's notebook are marked 🤒 until the student has caught up; homework from the e-diary goes into a 📌 table.
* **Textbook references**: textbooks (converted to text) in `references/` are used to check readings and cite printed page numbers - never copied.

## Learning evidence and optional media

Source images and relevant textbook figures are checked directly, including crop limitations and available conversion metadata. Private evidence records let later reviewers inspect the same material. Selected teacher-material images can support learning; textbook images remain evidence, not copied wiki illustrations. Original teaching files receive visible links in private lesson notes.

Optional [curriculum references](references/curriculum/README.md) guide relevant depth without turning every requirement into homework. Precise diagrams keep editable SVG; useful overview infographics can use a configured image generator, with checked labels/arrows and a factual image-description comment. Printable study notes are a separate A4 PDF output with selectable text and separate self-check answers. These rules do not install bots, grant account access or authorize unlimited generation.

For optional generated banners and infographics, follow the [repository-local setup](instructions/install-learning-images.md). All programs and instructions run from this checkout. No global skill, Hermes installation, Discord account or machine-specific configuration is required. Ordinary notes and SVG diagrams work without paid image generation.

## Getting started

An optional [web and print preview](packages/study-site/README.md) renders the existing Markdown with Astro + Starlight, without changing the notes. It runs from this Git checkout; the initial preview release does not publish private material or install a background service.

1. Click **Use this template** on GitHub and create a **private** repository (notebook photos and textbooks are private working copies - see below). A repository created from a template starts with a clean history.
2. Clone it, install the helper dependencies with `uv sync --locked` (Python 3.10+ and [uv](https://docs.astral.sh/uv/) are needed), and open it in your agent (Claude Code reads `CLAUDE.md`, Codex reads `AGENTS.md`).
3. Say *"Initialize the wiki"*. The agent asks for the student's first name, grade and school year, the wiki language, the audience, and which standing authorizations you want (e.g. automatic ingest and push), then records everything in `PROFILE.md`. English and Hungarian wording ship ready; other languages are translated at bootstrap.
4. Drop notes into `sources/` under any name and ask the agent to ingest them (or let it do so automatically if you allowed that). Subjects appear with the first notes.

Daily use: ask questions (useful answers can be filed back as pages), report homework, and request a lint pass now and then. Read the wiki from `wiki/index.md`.

## Privacy

* `wiki/` never contains grades, test results, names of private individuals (classmates, teachers), opinions about teachers, health or family data, or the name of the school, its town, or the class. The student's first name is the only personal name.
* `sources/` (notebook photos, raw notes) and `references/` (textbooks) are private working copies: never publish them. Public publication needs separate authorization and a filtered derivative of the canonical Markdown; do not publish the raw `wiki/` tree, which may contain restricted assets and source links. Follow [Public version](instructions/sources-and-evidence.md#sources).
* No secrets anywhere - git history is forever.

## Layout

```text
AGENTS.md           Shared rules, page templates, and workflows (same in every wiki).
PROFILE.md          This wiki's own settings: student, language, wording, authorizations.
CHANGELOG.md        Template versions and migration steps.
CLAUDE.md           Thin Claude Code adapter importing AGENTS.md and PROFILE.md.
SPEC.md             Pinned OKF 0.2 specification.
llm-wiki.md         Original idea document, preserved as background.
tools/banner.py     Page-header banners; subjects and labels in tools/subjects.json.
tools/curriculum.py Bounded navigation of an optional private requirements collection.
sources/            Immutable source material (private).
references/         Converted textbooks for checking and citing (private).
wiki/               Knowledge bundle, index, and update log.
```

There is one set of rules plus one profile, so Claude Code and Codex do not maintain conflicting copies. Automatic loading is documented by [OpenAI](https://developers.openai.com/codex/guides/agents-md/) and [Anthropic](https://code.claude.com/docs/en/memory).

## Updating from the template

Updates are opt-in. When you request one, the agent follows [CHANGELOG.md](CHANGELOG.md), preserves local settings and copies the complete set in [shared-files.json](shared-files.json). Shared files are byte-identical across linked wikis on the same release; settings stay in `PROFILE.md`, `tools/subjects.json` and `tools/book-index.json`. Run `uv run tools/check_shared.py --template <template-checkout>` to detect drift. Every linked wiki profile records the canonical template URL, release and commit.

The common [media workflows](instructions/media-workflows.md), [prompts](instructions/media-prompts.md) and [handoff contract](instructions/media-handoff.md) apply to authorized work with locally configured tools. The template remains uninitialized; bootstrap supplies the learner and language settings.

## Credits

* The LLM-wiki pattern is by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), preserved in [llm-wiki.md](llm-wiki.md).
* The OKF specification is from [Google Cloud Platform knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog), pinned in [SPEC.md](SPEC.md).

## System handbook

For optional integrations, start with the [system handbook](instructions/system-guide.md) to learn the architecture, find operating/configuration details, prepare a blog article, or follow the rebuild instructions. It covers Hermes and the bot roles, the wiki, media generation, Drive and scheduled review, with explicit implemented/planned status.
