# school-notes2 – the `sn` command line

The local, interactive tool of School Notes (plan: `school-notes-ops/docs/v2/helyi/terv-helyi-pipeline.md`).
The owner's Claude Code or Codex session is the controller; the writer and the reviewer are agents in that
session. This package does only the mechanical work: Drive, sources, paid image generation, figure insertion,
machine blocks, indexes, checks, the public build and the release, and the podcast episodes' sound and release. It never writes notes text and never decides
in anyone's name. No VM, scheduler, queue, task folder, container, MCP or mail (removed in 0.2.0; the history
is in git, tag `archiv/main-elotte` and the `archiv/<branch>` tags).

## Commands

`~/.local/bin/sn` runs `school-notes` from a tagged release worktree
(`~/.local/share/school-notes/release/current`). Each command is one module under `local/`.

| Command | What it does | Code |
|---|---|---|
| `sn fetch <t> [--apply]` | Drive inbox list; `--apply`: download → place in the working copy with its source manifest `sn-fetch.json` (a page known by its hash is listed, not stored again; a PDF page is rendered to 1.25 × the target size, no DPI) → move on Drive → delete the download; resumable | `local/fetch.py` |
| `sn book <t> <subject> <code> [<source>] [--offset N]` | a converted textbook into `references/`, README table, map | `local/book.py` |
| `sn check <t> <page…>` | page check, read-only (`check_files(fix=False)`) | `local/check.py` |
| `sn gen <t> <id> [--note f]`, `--settle`, `--grant` | one paid image generation through the host ledger | `local/gen.py` |
| `sn close <t> --subject s --snapshot [--only id,…]` | before the reviewer (and before the confirmation pass): the candidate preflight (STOP on a problem), then `keys.json` and `diff.patch` into the hand-over folder | `local/close.py` |
| `sn close <t> [--subject a,b] [--check]` | hand-overs in `.school-notes/out/<subject>/` (`handoff.py`) → STOP checks (writer guard, preflight, snapshot keys, `adatok.json`) → insertion and renewals (`figure_close.py`) → machine data: lesson-log keys, stamps, evidence records, figure requests, draft notice, banner and 📎 blocks (`machine_data.py`) → STOP on invalidated verdicts → indexes, `public.json`, content check → each hand-over read at the start whose subject succeeded (no STOP, no `sn done` problem on its pages, in a full close a snapshot) moved to `.school-notes/done/<pass id>/` (never deleted; `--check` moves nothing); never deletes a figure verdict | `local/close.py` |
| `sn done <t>` | is the content finished (exit 0/1); the facts it counts are in `local/places.py`, the writer guard in `local/guard.py` | `local/done.py` |
| `sn publish <t> [--reviewed] [--build-only DIR]` | clean tree + `sn done` 0 → push main → build → public gate → gh-pages → live check; a failed build step names the renderer's error line and keeps its log at `state/<t>/publish-render.log` | `local/publish.py`, `site/build.py` |
| `sn podcast <t> <subject> <page> --snapshot` | the podcast script's checks (`podcast/script.py`; STOP on a problem), then `keys.json` into `.school-notes/out/podcast/<subject>/<page>/` | `local/podcast.py` |
| `sn podcast <t> <subject> <page>` | the reviewer's accept for exactly the snapshot, its `key` included, and no hand-edited machine part on the pages it writes (else STOP) → budget for the whole episode → Gemini speech per scene and the blind name check through OpenRouter (cached, ledger, retries) → the approved mix into a 64 kbit/s mono MP3 → MP3, receipt, the page's player block, the Podcast page, `public.json` → Drive `Podcast/<Tantárgy> – <lapcím>.mp3` | `local/podcast.py` |
| `sn podcast <t> <subject> <page> --names-only` | a released episode's name check counted again with this tool from the podcast cache only (the receipt's scene hashes, the script with the receipt's `script_sha256` among the hand-over's `adas*.json`, the stored Whisper transcripts and blind answers): nothing is sent or paid, only the receipt's `names` change, under the podcast lock; a name whose call is missing from the cache keeps its earlier result in the v2 form with a note (nothing countable, or a hand-edited receipt: STOP, nothing written); `--fill-missing` sends the missing calls first through the paid path (ledger, budget, the reservation shown first) | `local/podcast_names.py`, `podcast/names.py`, `podcast/align.py` |
| `sn podcast <t> <subject> <page> --retire` | a released episode off the wiki (renamed or deleted topic page): its `podcast` blocks, MP3, receipt (recorded as the tool's deletion), the Podcast page with the last episode; the Drive copy stays | `local/podcast.py` |

Keys come only from `school-notes-ops/.env` at run time (`local/keys.py`); git runs over HTTPS with `gh`'s
token in git's environment (`git/run.py` `HttpsToken`); each command writes one line to `logs/school-notes.log`
(`sn check` too), and the library steps that take time – git network operations, site build, PDF render, gh-pages
push, live check, paid image generation attempts, paid podcast calls – one small line each with `seconds`, also on failure with its
`error_class` (`local/common.py` `STEPS`). The web footnote's form is `wiki/web_footnote.py`.

## Folders

| Folder | Responsibility |
|---|---|
| `cli.py`, `local/` | the commands; `local/common.py` builds the learner's working copy, git, image settings and Drive client from the configuration; `local/tool_writes.py` records what the tool wrote since the last commit (the writer guard accepts exactly that) |
| `config.py` | reads `~/.config/school-notes/config.toml`; a key it does not read is ignored with one warning line |
| `drive/` | listing, download, move to `Feldolgozva`, the podcast's upload to `Podcast/` (`upload.py`) (built on `tools/drive_media.py`) |
| `sources/` | natural order, photo and PDF preparation, names, duplicates, subject cards, placing a package, the source manifest |
| `evidence/` | the page evidence records `docs/evidence/pages/…` |
| `images/` | wrapper of `tools/learning_image.py`: monthly budget, shared lock, generation, settle, grant |
| `podcast/` | the podcast hand-over and its review key, the OpenRouter calls, its budget, ledger and cache, B-mode speech, the blind name check, the mix |
| `figures/` | commissions, the candidate preflight, the verdict key of a figure's content, insertion from an accept, licences, figure requests, the pending queue |
| `wiki/` | page check, frontmatter, machine blocks (banner, 📎 lesson log), indexes, decisions overview, `public.json`, rights, the podcast receipts, player block and Podcast page (`podcast.py`) |
| `site/` | public build from a commit (`packages/study-site`) and the `gh-pages` release |
| `git/` | the only Git caller (`run.py`) and three remote helpers (`repos.py`) |
| `state/` | error classes, safe file access inside a repo (`safefs.py`), private atomic writes (`files.py`) |
| `log/` | the JSONL log |
| `schemas/` | the JSON Schema of every contract the commands read or write |

## Rules the code keeps

* Every list the tool writes or prints has a total, content-derived order; every learner is handled the same way.
* Finished notes work, sources, evidence and decisions are never deleted; a STOP lists and changes nothing.
* `tests/test_import_graph.py` fails if anything reachable from `cli.py` or `local/` imports a removed
  VM module (`flows`, `mcp`, `llm`, `notify`, `repair`, `state.phase`, `state.lock`).

Tests: `uv run --group dev pytest` in this folder.
