# Learning-image execution: one path for Codex, Hermes and other agents

This is the runnable banner/infographic path. The author reads the relevant [workflow](media-workflows.md), [prompt stage](media-prompts.md), profile and evidence, writes a compact checked plan, then calls `tools/learning_image.py`. The CLI does not decide facts or visually review an image. Its inputs and receipts are portable across roles; no full curriculum corpus or private learner profile goes to the image provider.

In a school-notes run, the [run contract](school-notes-run.md#subject-cards-and-figure-handoff) takes precedence: the writer uses MCP `image_generate`, and only the tool inserts an independently accepted figure. The standalone CLI review/insertion examples below are not the run protocol.

## Install and configure

From the configured repository, run `uv sync --locked`. Python 3.10+, Pillow and Linux `flock` are sufficient. Keep the OpenRouter key in a protected file outside Git or the environment. The selected provider/model is `openai/gpt-image-2.5-sunburst`, fixed in the executor; no silent provider fallback. The [OpenRouter image API](https://openrouter.ai/docs/guides/overview/multimodal/image-generation) returns an inline raster and usage metadata. A missing cost or interrupted response is unresolved, not free.

Start with [repository-local setup](install-learning-images.md). Copy `learning-images.example.json` to `learning-images.json` and configure your own authorized request. This nonsecret, repository-specific policy is tracked in your private wiki; paths are relative to the policy file. Keys and runtime state stay ignored. `--config` also supports explicit legacy absolute policies; there is no global discovery fallback. Example:

```json
{
  "request_id": "authorized-request-id",
  "env_file": ".env",
  "state_dir": ".learning-images-state",
  "max_total_usd": "3.00",
  "reservation_usd": "0.25",
  "max_attempts": 3,
  "learners": {
    "configured-learner": {
      "repo": ".",
      "targets": ["wiki/subject/topic.md"],
      "max_usd": "3.00"
    }
  }
}
```

The whole-request cap includes every image and repair executed with that state, across roles and sessions. The learner cap is an additional bound within the request. Keep an externally configured provider-key ceiling too: a reservation is a conservative local allowance, not a provider guarantee of maximum billing. Do not reset state or choose a new request ID to evade limits. If separate requests run concurrently, deployment-level period/key limits must also constrain their combined spending; this CLI does not claim a cross-account budget service.

## The job file

Store a reviewed job in the learner repository's private `docs/evidence/media/<id>/job.json`. Use a stable ID and one logical page/role; distinct second infographics use `infographic-2`. `sources` includes the target page and the exact supporting files actually relied on, hashed after content editing and before generation. References remain read-only.

```json
{
  "id": "topic-banner-v1",
  "request_id": "authorized-request-id",
  "learner": "configured-learner",
  "target": "wiki/subject/topic.md",
  "role": "banner",
  "sources": [{"path": "wiki/subject/topic.md", "sha256": "actual-sha256"}],
  "plan": {
    "language": "English",
    "goal": "The concrete learner task",
    "scope": "Relative scope-record reference and selected depth",
    "decision_reason": "Why this image helps",
    "context": "The necessary visible introduction",
    "visible_text": ["Exact title", "Exact contextual subtitle"],
    "claims": [{"text": "A checked visual assertion", "source": "Exact evidence location"}],
    "composition": "Reading order and meaningful arrangement",
    "style": "Visual style appropriate to the task",
    "aspect_ratio": "21:9",
    "constraints": "Only the accuracy constraints relevant to this image"
  }
}
```

Conditional plan fields are `relationships`, `sequence`, `comparison`, `metaphor`, `example` and `optional`. Do not fill them merely to satisfy a checklist. The compiler omits source paths, hashes and private scope metadata from the provider prompt. Only `visible_text` is eligible for printed labels: composition, constraints and review instructions must not become image captions. Put every learner-facing contextual sentence into that list explicitly. Banners use 21:9; infographics normally use landscape 3:2 or 4:3, with portrait only when requested. A4 fit preserves aspect ratio and safe margins, without pretending the generated pixel count is 300 dpi.

## Execute, inspect, accept

Commands are identical for an interactive author and a Hermes shell tool. Substitute the trusted policy path and job path:

```sh
uv run tools/learning_image.py --config /private/policy.json validate --job docs/evidence/media/topic-banner-v1/job.json
uv run tools/learning_image.py --config /private/policy.json prompt --job docs/evidence/media/topic-banner-v1/job.json
uv run tools/learning_image.py --config /private/policy.json generate --job docs/evidence/media/topic-banner-v1/job.json
uv run tools/learning_image.py --config /private/policy.json status
```

Read the compiled prompt before paying. `generate` makes ONE request, never automatic retries. A persistent reservation precedes network activity. The JSON result identifies the candidate folder, size, hash, cost and request total. Directly open `image.png` with the agent's image-reading tool, inspect the whole image and relevant details, compare the checked sources and apply the form-specific QA. Use phone and print placement checks, not OCR alone.

Write a review JSON with `verifier`, actual `checked_at`, exact `sha256`, `observed` semantic description, `decision` (`accepted`/`rejected`), `material_defects` (list), and `checks` for `sources`, `context`, `text`, `visual_claims`, `arrows`, `learning_goal`, `phone`, `a4`. Each is `pass` when inspected; only `arrows` may be `not-applicable`. Record actual arrows, limitations, phone zoom needs and A4 placement in additional fields; a checkbox is not evidence by itself.

```sh
uv run tools/learning_image.py --config /private/policy.json review --job docs/evidence/media/topic-banner-v1/job.json --report /private/review.json
```

Acceptance rechecks sources and output hash, copies a versioned final PNG to `wiki/assets/` (banners to `wiki/assets/banner/`), and retains the plan, exact prompt, review and cost receipt in `docs/evidence/media/<id>/`. It never overwrites differing bytes. The author then inserts the accepted image with accurate alt text, scoped source caption and an observed hash-bound `image-description` comment, updates evidence/index and commits. Do all images for a page before editing its embeds; otherwise its source hash changes and the second job correctly stops as stale. The same applies to source-summary pages used by several jobs.

A generated candidate (after the author inspects it) or a recorded review rejection permits a targeted repair with `generate --repair /private/repair.txt` on the SAME job. It regenerates from the checked plan plus the concrete correction; it is not an edit API or a promise to preserve pixels. Each repair needs full-image review. At three attempts use the best acceptable candidate by its hash, or keep a suitable old image/text and record the precise unresolved question. A new filename never resets attempts.

## Recovery, checks and limitations

* Repeating a generated job returns its pending review; repeating an accepted job with still-current sources returns the accepted receipt, without spending. Renaming the job for the same page/role is rejected.
* A provider interruption, malformed result or unknown cost blocks further request spending. `reconcile --job ...` can recover from the exact saved provider response after an interrupted local save, without any network call. If no complete response exists, obtain provider billing/output evidence and resolve the recorded attempt; do not invent a zero cost or retry blindly.
* One lock serializes the ledger and spending; a concurrent process fails clearly. Source versions are checked before generation and acceptance. An out-of-band repository writer must still be coordinated by the caller; the CLI does not lock other agents' git processes.
* No automatic publication, sharing changes, raw-source upload or paid QA call occurs. Small inline wiki images remain in Git; larger standalone media uses the separately configured Drive delivery path.
* The path/target and spending checks are cooperative guardrails. An unrestricted shell user with the key can bypass them. This is not OS isolation or proof that separate Hermes role profiles are deployed.
* Run `uv run python -m unittest discover -s tools -p test_learning_image.py` after executor changes. The synthetic suite exercises retries, unknown charges, bounds, changed sources, path/learner rejection, concurrency and review-hash checks. A live job additionally proves the configured provider path; it does not prove future error-free outputs or Discord routing.

Any agent with repository access and a terminal can follow this guide directly. No installed skill is required. Read AGENTS.md and PROFILE.md from the selected repository, then invoke its checked-in CLI. The default policy is that checkout's learning-images.json, regardless of the current shell directory. The job path is an ordinary command-line path; use the repository directory or an absolute job path.

## State, relocation and compatibility

`status` and `check` are read-only and work without credentials. A missing configuration reports `not-configured`; a missing ledger reports `not-initialized`, never a fresh available balance. `validate` and `prompt` do not create state. For a genuinely new authorized request, explicitly run `uv run tools/learning_image.py init-state`. For resumed work restore the entire existing state tree instead. Initialization refuses a different existing request or artifacts with a missing ledger.

Back up the ledger and attempt artifacts together. Artifact lookup uses `<state_dir>/<job-id>/<attempt-number>`, so a restored complete tree works at a new path. Legacy absolute `folder` values are retained as history, not followed as filesystem authority. New records use relative folder paths. Missing artifacts or unknown charges block recovery rather than granting a fresh attempt. Never change a request ID to evade limits. Keep only one active executor per request.

Do not modify an attempted job to add a language field: its hash must remain stable. Existing jobs without `language` retain Hungarian behavior; new jobs specify their output language. The supported image model remains fixed as documented, independent of unused environment variables.

On code rollback, preserve secrets and spending state. Pre-1.13 executors do not understand newly written relative folder fields; do not run them against new state. A rollback after new attempts requires an explicitly reviewed compatibility migration with a preserved original snapshot, not deletion/reset of records.

## Smaller publication banners

For a generated illustrative banner, prefer a smaller publication encoding when text and details remain readable. After generation run `uv run tools/learning_image.py preview-banner --job <job.json>`. This produces a fixed WebP quality-85 preview in ignored attempt state, with the original resolution and no additional API call. It does not publish or accept the image. Inspect both the generated original and this actual preview, including phone and print placement; fall back to the original PNG if compression harms readability. Never apply this banner choice automatically to exact diagrams or text-heavy infographics.

To publish that inspected preview, add `publication` to the ordinary review JSON: `{"format":"webp","quality":85,"sha256":"PREVIEW_HASH","checked":true,"observed":"What was checked in the compressed image"}`. Acceptance re-encodes from the original, requires the identical preview hash and publishes only the WebP. The receipt's `sha256` still identifies the original candidate; `published_sha256` identifies the actual embedded file. Bind Markdown image-description comments to the published hash. The original and provider response remain in the backed-up, ignored attempt state; they are not added to Git merely to accompany the smaller derivative. Review reports record both hashes. Restore state with the existing procedure, including Pillow/encoder environment when reproducing byte-identical derivatives; a version mismatch needs a fresh encoding review, not a fabricated hash.

Existing committed PNGs are not automatically rewritten or deleted. A separate authorized migration must update links/evidence, inspect the derivatives and preserve restoration evidence. Deleting an old file from the latest commit does not remove it from Git history; history rewriting is not part of compression.

## Lossless infographic publication

For generated infographics, try `uv run tools/learning_image.py preview-infographic --job <job.json>` after generation. It encodes WebP losslessly, preserving dimensions and every decoded RGBA pixel, including transparency. The executor verifies equality before returning `pixel_identical: true`. This is a raster encoding change, not a generative edit or conversion of an editable SVG/model. Compare byte sizes and keep PNG when WebP is not smaller or a required viewer does not support it.

Inspect the actual preview in the relevant viewer, then use the normal review with `publication: {"format":"webp","lossless":true,"sha256":"PREVIEW_HASH","checked":true,"observed":"Actual preview check"}`. Do not set banner quality-85 compression for an infographic. The original image still requires full semantic QA: lossless encoding preserves errors too. The accepted image-description comment must identify the published WebP hash; original hash, prompt, receipt and review remain available. Normal Markdown embeds and direct-image links let any image-capable reviewer inspect it; comments retain the searchable explanation, not a substitute for visual inspection.

The read-only-source encoder `tools.learning_image.infographic_webp` can also serve an explicitly authorized migration of already accepted raster infographics. Record source and derivative paths, hashes, dimensions, pixel equality and sizes; update image/link destinations and comments together, preserving historical review records. Do not invoke generation, reset jobs or rewrite accepted receipts for a format migration. Keep restoration evidence and only remove old files when existing evidence links and references remain resolvable. This does not authorize bulk changes to raw source images or exact diagrams.

## Correcting an image after acceptance

A later review can find an error in an accepted image. Keep the previous `job.json` as immutable evidence and prepare a revised job with the same ID, request, learner, target and role, fresh source hashes and checked corrections. Use `revise --previous-job OLD.json --job REVISED.json --reason "concrete observed error"`, then the ordinary `generate --job REVISED.json --repair repair.txt` and visual review. This does not generate or spend by itself. It requires the existing attempt and spending limits to allow another call; a specific user exception must precede a limit increase.

The ledger preserves the previous job, acceptance, review and all charges. Attempts continue numbering; accepted output receives a revision suffix and never overwrites the previous file. Update the Markdown only after checking the new image. Published evidence includes the revision event. Never edit ledger counters or create a new request just to bypass these limits.
