"""Local rendering through study-site, with no model or network access."""

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..state import safefs


@dataclass(frozen=True)
class Renderer:
    study_site: Path
    browser: Path
    scratch: Path
    node: str = "node"
    timeout_s: int = 120

    def __call__(self, kind: str, data: bytes, figure_id: str) -> bytes:
        if kind not in ("svg", "mermaid"):
            return png(data)
        # A tool-owned directory; no source code from the writer is executed here.
        self.scratch.mkdir(parents=True, exist_ok=True)
        source, target = f"{figure_id}.{kind}", f"{figure_id}.png"
        safefs.write_bytes(self.scratch, source, data)
        safefs.unlink(self.scratch, target)
        proc = subprocess.run([self.node, str(self.study_site / "figure-render.mjs"), kind,
                               str(self.scratch / source), str(self.scratch / target),
                               str(self.browser), figure_id], capture_output=True,
                              timeout=self.timeout_s)
        if proc.returncode:
            raise ValueError("figure rendering failed: " + proc.stderr.decode(errors="replace")[-1000:])
        return png(safefs.read_bytes(self.scratch, target))


def png(data: bytes, width: int | None = None, crop: list[int] | None = None) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if crop:
            if crop[2] > image.width or crop[3] > image.height:
                raise ValueError("source crop exceeds image bounds")
            image = image.crop(tuple(crop))
        if width and image.width > width:
            image = image.resize((width, max(1, round(image.height * width / image.width))),
                                 Image.Resampling.LANCZOS)
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()
