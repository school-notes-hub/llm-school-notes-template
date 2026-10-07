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


def pdf_layout(pdf: Path, timeout_s: float = 120) -> list[dict]:
    """Per page: {size: (w, h) pt, rot, images: [(width, height, x_ppi, y_ppi)]} from
    `pdfinfo` and `pdfimages -list` (masks and soft masks are not images of their own)."""
    count = pdf_page_count(pdf, timeout_s)
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", str(count), str(pdf)], capture_output=True,
                          text=True, timeout=timeout_s, check=True).stdout
    pages = [{"size": None, "rot": 0, "images": []} for _ in range(count)]
    for m in re.finditer(r"^Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+) pts", info, re.M):
        pages[int(m[1]) - 1]["size"] = (float(m[2]), float(m[3]))
    for m in re.finditer(r"^Page\s+(\d+) rot:\s+(\d+)", info, re.M):
        pages[int(m[1]) - 1]["rot"] = int(m[2]) % 360
    listing = subprocess.run(["pdfimages", "-list", str(pdf)], capture_output=True, text=True,
                             timeout=timeout_s, check=True).stdout
    for line in listing.splitlines()[2:]:
        f = line.split()
        if len(f) >= 14 and f[2] == "image":
            pages[int(f[0]) - 1]["images"].append((int(f[3]), int(f[4]), float(f[12]), float(f[13])))
    return pages


def full_page_image(page: dict) -> bool:
    """One image that covers the whole unrotated page (its placed size equals the page size
    within 2 %): `pdfimages` takes it out unchanged, no rendering. Anything else is rendered,
    because `pdfimages` knows nothing of page rotation or cropping."""
    if page["rot"] or len(page["images"]) != 1 or not page["size"]:
        return False
    width, height, x_ppi, y_ppi = page["images"][0]
    if not x_ppi or not y_ppi:
        return False
    placed = (width / x_ppi * 72, height / y_ppi * 72)
    return all(abs(a - b) <= 0.02 * b for a, b in zip(placed, page["size"]))


def pdf_pages(pdf: Path, out_dir: Path, max_side_px: int, timeout_s: float = 900) -> tuple[list[Path], dict]:
    """Every page as an image, in page order, and what was done ({extracted, rendered,
    seconds}). A full-page single image is taken out with `pdfimages`; any other page is
    rendered with `pdftoppm -scale-to <1.25 × max_side_px>` (the target size decides, never a
    DPI: the later downscale is at most 1.25×). One lossy step follows later."""
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = pdf_layout(pdf)
    scale = str(round(1.25 * max_side_px))
    pages, extracted = [], 0
    for number, page in enumerate(layout, start=1):
        prefix = out_dir / f"page-{number:04d}"
        if full_page_image(page):
            subprocess.run(["pdfimages", "-f", str(number), "-l", str(number), "-j", "-png", str(pdf), str(prefix)],
                           capture_output=True, timeout=timeout_s, check=True)
            found = sorted(out_dir.glob(f"page-{number:04d}-*"))
            if len(found) == 1:
                pages.append(found[0])
                extracted += 1
                continue
            for extra in found:
                extra.unlink()
        subprocess.run(["pdftoppm", "-f", str(number), "-l", str(number), "-singlefile", "-scale-to", scale,
                        "-png", str(pdf), str(prefix)], capture_output=True, timeout=timeout_s, check=True)
        pages.append(prefix.with_suffix(".png"))
    if len(pages) != len(layout) or not all(p.is_file() for p in pages):
        raise ValueError(f"{pdf.name}: {len(pages)} page images for {len(layout)} pages")
    return pages, {"pages": len(layout), "extracted": extracted, "rendered": len(layout) - extracted,
                   "seconds": round(time.monotonic() - started, 2)}
