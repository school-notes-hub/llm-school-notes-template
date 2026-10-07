# Technical visual pilot

Optional, reproducible examples for comparing three tools. This directory is not a plugin or an installer. It changes no agent configuration, needs no credentials and is not required for ordinary wiki work. These are demonstrations, not accepted lesson replacements or manufacturing drawings.

**Second series:** [nine more examples](more.md), or open [the new local gallery](more.html).

## View the examples

Open [index.html](index.html) from a local Git checkout in a browser for the complete gallery and playable animation. GitHub displays the HTML source; the previews below work directly in its Markdown viewer.

### Graphviz: organize relationships

![Four aspects of describing a force; these arrows are classification branches, not force vectors.](preview/structure.svg)

The line of action follows from application point and direction; the branches are not independent input quantities. Source: [structure.dot](structure.dot).

### FreeCAD: parameterized geometry

![Twenty-tooth involute gear; module 2 mm, pressure angle 20 degrees.](preview/gear.svg)

Native model construction and checks run with `freecadcmd`, without the GUI or an external addon. The SVG is a sampled preview with 0.01 mm deflection setting; the script also exports editable FCStd and STEP. Source: [gear.py](gear.py).

### POV-Ray: prescribed poses

| -45 degrees | Horizontal | +45 degrees |
|---|---|---|
| ![Start pose](preview/lever-start.png) | ![Middle pose](preview/lever-middle.png) | ![End pose](preview/lever-end.png) |

The rod stays the same length. For the fixed downward force direction, the perpendicular moment arm is largest at the horizontal pose. [Open/download the short MP4](preview/lever.mp4); the local HTML gallery embeds it with playback controls. Source: [lever.pov](lever.pov). This is prescribed motion, not a dynamics solver. No looping playback is assumed.

## Reproduce

Supply already available executables. Do not install all tools merely to use the wiki. Agree on any persistent installation separately. Use a new output directory outside the checkout:

```sh
python3 examples/technical-visuals/measure.py --output /tmp/visual-run-1 --dot /path/to/dot
python3 examples/technical-visuals/measure.py --output /tmp/visual-run-2 --freecad /path/to/freecadcmd
python3 examples/technical-visuals/measure.py --output /tmp/visual-run-3 --povray /path/to/povray --ffmpeg /path/to/ffmpeg
```

For the official extracted Linux AppImage, use `--freecad-app-run /path/to/squashfs-root/AppRun` instead of `--freecad`. Executable flags can be combined in one run. The runner uses Python's standard library, records three process timings per static case, checks outputs and preserves logs. The headless FreeCAD script has no GUI imports; it uses a bundled module that internally imports QtCore, not a running graphical view. User/system FreeCAD configuration for the measurement is placed in the output directory. An installed binary may have other environment-specific runtime requirements.

The supplied scripts execute only the requested programs and write their outputs/configuration/logs to the selected output directory; they do not download packages, copy secrets or publish files. Run only trusted scene/model code. Distributable source belongs in Git; large runtimes and scratch results do not.

## Measured result, 2026-09-28

Host: Ubuntu 26.04 x86_64, Intel Core i5-12500, 12 logical CPUs. Timings are wall-clock measurements with the runtime already extracted and available; they exclude download, extraction, authoring and human review. Three repeated static runs are not a rigorous cold-cache benchmark.

| Work | Measured time | Scope |
|---|---|---|
| Graphviz 14.1.2, DOT to SVG | Median 0.020 s | Five nodes, four edges |
| FreeCAD 1.1.3, full process | Median 0.327 s | Model, analytic checks, FCStd/STEP/SVG export |
| FreeCAD, model construction only | Median 0.101 s | Measured inside the script |
| POV-Ray 3.7.0.10, static image | Median 0.749 s | 960 × 640, quality 9, AA 0.1, two threads |
| POV-Ray, 25 frames | 8.533 s | Same settings, one sequence run |
| FFmpeg, MP4 encoding | 0.173 s | 25 frames at 12 fps, H.264 |

Detailed numbers, source hashes and geometry checks: [timings.json](preview/timings.json). These small cases do not predict large-scene performance. The POV-Ray process timings include startup and per-frame overhead; they are not CPU ray-tracing time alone.

Footprint in this local test: Graphviz/POV-Ray and the missing dependencies downloaded as 11 Ubuntu packages totalled about 2.07 MiB and occupied about 5.8 MiB after extraction, relying on libraries already present. FreeCAD's official 1.1.3 AppImage was 782.77 MiB and its extracted runtime about 3.1 GiB. Keeping both requires about 3.9 GiB. This is not a full clean-machine dependency estimate.

### Runtime preparation used for this experiment

This records the disposable local experiment, not a persistent installation recommendation. All downloads were extracted into a scratch directory; no system package installation was performed and no agent runtime was modified.

* FreeCAD: official `FreeCAD_1.1.3-Linux-x86_64-py311.AppImage` from the linked release; SHA-256 `3a853eb69ee595f779f2255dbf80a765926981d8ff68903cefee4dfb03a8f5ef`, matched to the official asset digest before execution. `chmod +x` followed by `--appimage-extract` in the scratch directory produced `squashfs-root/`. Its `AppRun freecadcmd` entry point provided the bundled environment. No addon was added.
* Ubuntu packages: an `apt-get -s --no-install-recommends install povray graphviz` dry run identified missing dependencies. `apt-get download` retrieved `graphviz libcdt6 libcgraph8 libgvc7 libgvplugin-gd8 libgvplugin-pango8 libgvpr2 libpathplan4 libsdl1.2debian libxdot4 povray`; each was extracted with `dpkg-deb -x` into the same scratch runtime directory. Graphviz libraries were version `14.1.2-1ubuntu1`, SDL `1.2.72-1`, POV-Ray `1:3.7.0.10-3build7`.
* The command-local `LD_LIBRARY_PATH` pointed at the extracted `usr/lib/x86_64-linux-gnu`; `GVBINDIR` pointed at its `graphviz` subdirectory. Running the extracted `dot -c` created its local plugin cache. These variables were not added to shell profiles. The extracted POV-Ray had no normal system configuration and reported disabled I/O restrictions; only the inspected repository-owned scene was executed.
* FFmpeg was already present and used the explicit software encoder `libx264`. No GPU encoder was requested. A browser was used only for gallery/preview QA, not for CAD construction or POV-Ray rendering.

For another machine, first inspect that machine's package/dependency availability and agree on installation. Do not copy the scratch runtime as an undocumented deployment. After closing the programs and preserving wanted outputs, this experiment is removable by deleting its chosen scratch directory; no installed package or service needs removal.

## What was checked, and what was not

* Graphviz: the four intended edges survive into the exported SVG. Visual layout and arrow interpretation still need direct inspection; automatic layout does not validate the subject matter.
* FreeCAD: valid closed outline and solid, expected root/tip radii, forty intersections at each of three radii, and tooth-flank angles compared with the independent involute formula. Maximum sampled angular discrepancy was below 0.00001 rad. This checks this parameter set, not all gear profiles. No contact pair, undercut behavior, load, manufacturing tolerance, thread or wall notation was validated. The [built-in gear documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_InvoluteGear.md) explicitly describes profile limitations.
* POV-Ray: all 25 emitted poses checked for angle progression, unit rod length and horizontal projection. The final rendered states require visual review too. There is no physical dynamics simulation or contact validation. Selected screenshots cannot prove arbitrary intermediate behavior; the numerical checks cover only the named invariants.

Choosing a hatch or constructing a helix does not establish an applicable wall notation or thread specification. For each lesson, identify the meaningful detail, its source/convention, the appropriate numeric/structural checks, then inspect the final view. An attractive generated raster may supplement a precise diagram but does not replace its checked geometry.

Human acceptance is separate from these checks. The user accepted the first three previews on 2026-09-28, while noting that the first POV-Ray example is planar, and subsequently accepted the nine samples in the second series too. New execution examples remain separate from that acceptance. Silence does not mean a sample was viewed or accepted.

The [repository runner examples](runner.md) add Matplotlib and PlantUML and demonstrate the persistent installation path.

## References

* [FreeCAD release 1.1.3](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.3) and [built-in workbenches](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Workbenches.md).
* [Graphviz output formats](https://graphviz.org/docs/outputs/).
* [POV-Ray animation clock and subset handling](https://wiki.povray.org/content/Reference:Animation_Options).

POV-Ray 3.7 uses CPU rendering; the pilot fixes two worker threads and disables its display window. No GPU is needed for this scene. On another machine, compare the same revision and settings before estimating its throughput. See the [official CPU benchmark guidance](https://www.povray.org/download/benchmark.php).
