# School Notes video chain

The machine steps of a Manim teaching video, run from the tagged release worktree like `sn`
(`~/.local/share/school-notes/release/current/packages/video/`). The writer agent writes the
narration and the scene code; this chain does the rest without an LLM: speech (TTS per step),
word timing (Whisper per step, number reader), frame plan, render, gate (K1-K13), contact sheets,
final render with opening and closing card, receipt and measurement.

| Path | What it is |
|---|---|
| `video.sh` | the one command: `video.sh <learner> <subject> <page>-<n> [--atadas [--valtozott] \| --vegleges \| --meres \| --kivagat <step>/<obj> \| --takarit]`; runs `video.py` in this tree's `packages/school-notes2` uv environment |
| `manim.sh` | Manim from the separate `manim-env` with its own TinyTeX; puts this folder on `PYTHONPATH`, so scene code imports `from videotar import ...` |
| `video.py`, `lanc/` | the chain: speech, words, render, opening/closing card, measurement |
| `hang.py`, `idoterv.py` | speech helpers and the frame plan |
| `kapu.py`, `tabla.py`, `lapok.py`, `szamnev.py` | the gate, its time table, contact sheets and the number reader ([interface](kapu-interfesz.md)) |
| `videotar/` | the element library for scene code ([API](videotar/API.md)), pinned to Manim 0.22 |

Exit codes: 0 green, 1 red, 2 stopped (input, version, lock, budget, time limit), 3 render crash.
Working folders stay in the learner repository (`.school-notes/out/video/<subject>/<page>-<n>/`),
the Manim cache under `~/.cache/school-notes/video/`, finished videos under `~/jegyzet/video-kesz/`.
Paid calls go through the podcast ledger, cache and budget of `school_notes2`.

## Tests (no paid call)

```sh
cd packages/video
uv run --project ../school-notes2 python -m pytest -q lanc/teszt   # chain, number reader, gate rules; renders the test scenes through video.sh with VIDEO_CSONK=1
videotar-teszt/render.sh                                             # renders the two test scenes (synthetic sound), then the videotar tests in manim-env
kapu-teszt/kapu-teszt.sh [--render]                                  # gate acceptance on the test scenes
```

`VIDEO_CSONK=1` with `--mappa <folder>` replaces TTS and Whisper with the synthetic stub of
`videotar-teszt/szintetikus.py`. Every fixture is synthetic: no learner, page, narration or source
text (the neutrality test of `packages/school-notes2` scans this whole folder).
