# Optional local visual tools

This is the installation and execution entry point for deterministic visuals. The [selection guide](technical-visuals.md) determines what to draw; installed programs do not decide the teaching task. The visual tool code stays in this Git checkout. No agent-specific program or globally installed skill is needed.

## Installation proposal and boundaries

Agree on persistent installations for the target machine before running them. Ordinary note tools do not require the optional plotting group or external renderers. The commands below are independently selectable; installing one tool does not install all the others.

| Component | Purpose | Installation route |
|---|---|---|
| Matplotlib + NumPy | Quantitative and custom authored plots | `uv sync --locked --group visuals` in the checkout; versions and distribution hashes are in `uv.lock`. No system Python changes. |
| Graphviz | Graph layout and some PlantUML diagrams | OS package manager; inspect its proposed dependency changes first. |
| PlantUML | Text-authored formal and other diagrams | Official versioned JAR, verified digest, outside Git; existing compatible Java runtime. |
| FreeCAD | Headless parametric models, sections and projections | Official versioned distribution outside Git; record the version/digest and entry point. No addon is assumed. |
| POV-Ray | CPU scene rendering | OS package manager; inspect the proposed changes first. |
| FFmpeg | Encoding authorized animation frames | Optional existing executable or separately agreed installation. Static rendering does not need it. |

SciPy is a problem-specific computation option, not a mandatory plotting dependency. Spyder is an IDE and unnecessary for automation. Mermaid, TikZ and other methods remain valid choices: verify the actual viewer/rendering path when using them. The base command below does not silently install an absent backend.

## Python environment

```sh
uv sync --locked --group visuals
uv run --locked --group visuals python -c 'import matplotlib, numpy; print(matplotlib.__version__, numpy.__version__)'
```

Always include `--group visuals` for plotting commands so `uv` can select the optional environment. Ordinary note commands keep their usual dependency set. On a supported Python version, `uv.lock` selects its compatible versions; different Python versions may select different branches. Record the Python version too. To remove the optional plotting packages from this checkout environment, use `uv sync --locked`; this does not remove OS packages or external runtimes.

## Concrete Ubuntu workstation proposal (2026-09-28)

This is a proposal until a private deployment receipt records execution. It is not a claim about every Ubuntu version.

* Graphviz `14.1.2-1ubuntu1`, POV-Ray `1:3.7.0.10-3build7`, plus the dependencies shown by `apt-get -s --no-install-recommends install graphviz povray`. The observed dry run requested 11 new packages, no upgrades/removals. Proposed actual command: `sudo apt-get --no-install-recommends install graphviz=14.1.2-1ubuntu1 povray=1:3.7.0.10-3build7`. The unversioned dry run and versioned install should be compared immediately before execution. Distribution snapshots may be required to reproduce older package versions later; a moving mirror is not an indefinite archive.
* PlantUML `1.2026.8`: [official JAR](https://github.com/plantuml/plantuml/releases/download/v1.2026.8/plantuml.jar), 29,871,497 bytes, SHA-256 `5e1ecfa8ecd32c90b03bbf3b1eb6f020943f98ab0fcf4032be31a0002ee2c462`. Proposed location: `${XDG_DATA_HOME:-$HOME/.local/share}/school-notes-runtimes/plantuml/1.2026.8/plantuml.jar`. Existing OpenJDK 21 is available on the workstation. The older OS PlantUML package is not part of this proposal.
* FreeCAD `1.1.3`: use the official AppImage and verified hash already recorded in the [pilot](../examples/technical-visuals/README.md), extracted under `${XDG_DATA_HOME:-$HOME/.local/share}/school-notes-runtimes/freecad/1.1.3/`. The extracted bundle occupies about 3.1 GiB; retaining its download too takes about 3.9 GiB. Reconstruction downloads/extracts the official artifact and checks its digest first. The workstation reused its verified download, extracting a fresh persistent runtime. No project script or secret is transferred with the runtime.
* Plotting: the repository lock selects Matplotlib `3.11.2` and NumPy `2.5.3` for the current Python 3.14 environment. Lower supported Python versions have separate compatible locked resolutions. Install in this checkout's `.venv` only.

Record actual commands, resulting versions, tests and residual limits in a private deployment receipt. Do not put this workstation's paths into the shared example configuration. On another machine, inspect its OS and existing tools before proposing equivalent installation; do not copy the workstation runtime or invent measured performance.

## Rebuild the external runtimes

Prefer supported packages rather than extracting OS package archives to avoid administrator access. On Ubuntu, inspect `apt-cache policy graphviz povray` and a simulated install, then install with the administrator's approved `sudo apt-get --no-install-recommends install graphviz povray`. Add a compatible headless Java package (for example `openjdk-21-jre-headless`) if Java is absent. These packages may bring graphical libraries even when invoked without a display; do not equate a library dependency with GPU rendering. Record `dpkg-query -W` versions. Different machines can legitimately have different distribution package versions.

For the following Linux x86_64 versions, a separately versioned official JAR/AppImage provides the tested runtime where the OS has an obsolete PlantUML or no FreeCAD candidate. These upstream distributions need no agent modifications. Commands use a fresh version directory; do not overwrite an existing installation blindly. Verify enough disk space first. A checksum mismatch stops installation, never execution with a warning.

```sh
visual_runtime_root="${XDG_DATA_HOME:-$HOME/.local/share}/school-notes-runtimes"
mkdir -p "$visual_runtime_root/plantuml/1.2026.8"
cd "$visual_runtime_root/plantuml/1.2026.8"
curl --fail --location --output plantuml.jar.download https://github.com/plantuml/plantuml/releases/download/v1.2026.8/plantuml.jar
printf '%s\n' '5e1ecfa8ecd32c90b03bbf3b1eb6f020943f98ab0fcf4032be31a0002ee2c462  plantuml.jar.download' | sha256sum --check - && mv plantuml.jar.download plantuml.jar
```

```sh
visual_runtime_root="${XDG_DATA_HOME:-$HOME/.local/share}/school-notes-runtimes"
mkdir -p "$visual_runtime_root/freecad/1.1.3"
cd "$visual_runtime_root/freecad/1.1.3"
curl --fail --location --output FreeCAD.AppImage.download https://github.com/FreeCAD/FreeCAD/releases/download/1.1.3/FreeCAD_1.1.3-Linux-x86_64-py311.AppImage
printf '%s\n' '3a853eb69ee595f779f2255dbf80a765926981d8ff68903cefee4dfb03a8f5ef  FreeCAD.AppImage.download' | sha256sum --check - && mv FreeCAD.AppImage.download FreeCAD.AppImage
```

Only after that checksum passes:

```sh
chmod u+x FreeCAD.AppImage
./FreeCAD.AppImage --appimage-extract > extraction.log
./squashfs-root/AppRun freecadcmd --version
```

Extraction is the AppImage's supported headless execution path without a FUSE mount. Keep the upstream AppRun launcher: it configures its bundled libraries. Do not modify the bundle or borrow libraries from a different machine. If the host lacks a required library, identify it and install the corresponding supported OS package, recording that dependency. No third-party FreeCAD workbench is installed by these steps. Other operating systems/architectures need their own verified upstream artifacts.

## Run a visual

From a Git checkout with the optional Python environment installed:

```sh
uv run --locked --group visuals tools/visual_tools.py status
```

This reads availability only. It imports no renderer and does not install, initialize agent configuration or claim that a diagram is verified. Copy [visual-tools.example.json](../visual-tools.example.json) to ignored `visual-tools.local.json` in this checkout and set actual executable paths. For the Linux bundles above, `plantuml_jar` points at the JAR and `freecad_app_run` at `squashfs-root/AppRun`. Other tools normally resolve from PATH. Relative configuration paths resolve beside the JSON, including a bare JAR filename; `--config <file>` selects another machine-local path file. Credentials do not belong in this file.

```sh
uv run --locked --group visuals tools/visual_tools.py render python examples/technical-visuals/function-plot.py --output .visual-runs/function --expect figure.svg --expect figure.png
uv run --locked --group visuals tools/visual_tools.py render graphviz examples/technical-visuals/structure.dot --output .visual-runs/graph
uv run --locked --group visuals tools/visual_tools.py render plantuml examples/technical-visuals/message-sequence.puml --output .visual-runs/sequence
uv run --locked --group visuals tools/visual_tools.py render plantuml examples/technical-visuals/decision-activity.puml --output .visual-runs/activity
uv run --locked --group visuals tools/visual_tools.py render povray examples/technical-visuals/pipe-cutaway.pov --output .visual-runs/scene
uv run --locked --group visuals tools/visual_tools.py render freecad examples/technical-visuals/plate-model.py --output .visual-runs/plate --expect figure.svg --expect plate.FCStd --expect plate.step --expect checks.json
```

Use a new output directory for every invocation. The runner never overwrites an existing directory. Use `--expect figure.png` for PNG Graphviz/PlantUML exports. Declare additional data/include inputs with repeated `--input <file>` for hashing; this records dependencies, it does not rewrite include paths. Do not pass credentials as inputs. The default timeout is 180 seconds and is configurable up to 3600; POSIX timeout handling terminates the renderer process group. POV-Ray defaults to 1200 x 800, two CPU threads, no display; explicit `--width`, `--height`, `--threads` remain bounded.

Python and FreeCAD source scripts get `VISUAL_OUTPUT_DIR`; write only the planned outputs there. Use source-relative paths for approved inputs. Source must be reviewed code inside this checkout, outside raw `sources/` and `references/`. This is a trusted-code runner, **not a sandbox**: invoked programs inherit OS access, and arbitrary Python can write beyond the requested output directory. Agent role restrictions therefore need actual execution/access controls. PlantUML uses its SANDBOX security profile and no public rendering service; local/remote includes and some advanced facilities may be unavailable. Do not silently weaken that profile to make a diagram work.

Each run produces `render.json`, stderr and usually stdout logs, recording source and driver hashes, declared inputs, executable/JAR identity, Python package versions, elapsed time and artifact hashes. Simple SVG/PNG/PDF structural checks and expected-file checks catch missing output even if a renderer exits zero. They do not prove content, full file integrity or readability. Success is deliberately named `rendered-awaiting-review`; direct visual and subject review remain separate. Preserve accepted source plus relevant evidence, not caches or whole runtime directories, in Git. Private records may contain absolute paths: sanitize before publication.

The five adapters are convenient execution paths, not a list of permitted diagram types. Native commands, Mermaid, SVG, TikZ or another justified renderer remain possible under the selection guide. No automatic paid fallback, image upload, wiki insertion or Git publication happens in this tool. Smoke tests prove only their concrete paths; [examples and review status](../examples/technical-visuals/runner.md) describe those limits.

## Verify a deployment

Run `uv run --locked --group visuals python -m unittest discover -s tools -p test_visual_tools.py`, then the representative render commands above. View their actual output, check the FreeCAD numeric assertions and Matplotlib domain handling, and record runtime versions and timings separately per machine. Keep the `.visual-runs` receipts in the private deployment inventory; one machine's timing must not be inferred from another's. Install own scripts/skills only by Git checkout/pull on the destination, then rebuild its environment. No environment/credential copy is part of this procedure.

## Cleanup

Project code is reverted through Git. A checkout's optional environment can be rebuilt from `uv.lock`. Remove a separately installed PlantUML/FreeCAD version directory only after confirming that no other checkout uses it and retaining any needed models/results. For OS packages, inspect a removal simulation and remove only packages installed for this work that are no longer needed; do not blindly autoremove dependencies or purge pre-existing programs.
