"""Uniform source images (plan 4.2): photos and PDF pages become ≤ max_side JPEGs."""

import re
import subprocess
import time
from pathlib import Path

from .toolload import load_tool


def prepare_image(src: Path, dst: Path, max_side_px: int, quality: int,
                  tools_dir: Path | None = None) -> str:
    """tools/prepare_photo.prepare: upright, downscaled only, no metadata; returns the SHA-256."""
    _, digest = load_tool("prepare_photo", tools_dir).prepare(src, dst, max_side_px, quality)
    return digest


def pdf_page_count(pdf: Path, timeout_s: float = 120) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=timeout_s,
                         check=True).stdout
    match = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not match:
        raise ValueError(f"pdfinfo gave no page count for {pdf.name}")
    return int(match.group(1))


def pdf_pages(pdf: Path, out_dir: Path, max_side_px: int, timeout_s: float = 900) -> tuple[list[Path], dict]:
    """Every page rendered to PNG, in page order, and {pages, seconds}. `pdftoppm -scale-to
    <1.25 × max_side_px>`: the target size decides, never a DPI, so a scanner's giant page size
    costs no more than a normal one and the later downscale is at most 1.25×. Every page is
    rendered (text, vector overlays, clipping and the image's own rotation included); one lossy
    step follows later."""
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-scale-to", str(round(1.25 * max_side_px)), "-png", str(pdf), str(out_dir / "page")],
                   capture_output=True, timeout=timeout_s, check=True)
    pages = sorted(out_dir.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    count = pdf_page_count(pdf)
    if len(pages) != count:
        raise ValueError(f"pdftoppm rendered {len(pages)} pages of {pdf.name}")
    return pages, {"pages": count, "seconds": round(time.monotonic() - started, 2)}
