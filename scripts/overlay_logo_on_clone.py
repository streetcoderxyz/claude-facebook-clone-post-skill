#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""
Overlay the Omini logo into the reserved top-left dashed placeholder of a
ChatGPT-generated infographic clone.

The image-gen prompt instructs ChatGPT to draw a dashed rectangle in the
top-left header band as a logo placeholder (so the logo can be pasted by a
program afterwards, instead of being drawn — and possibly mangled — by the
model). This script detects that dashed rectangle by color + connected-
components, renders the Omini logo SVG, tight-crops to the visible glyph
bbox, then scales-to-fit and composites centered inside the placeholder.

Why not use overlay_logo.py (from wordpress-generate-missing-images)?
That helper takes a fixed corner + margin and is great for a uniform corner
stamp. For clone posts, the placeholder position/size varies per image
(ChatGPT renders it where it wants), so we must measure it per-image.

Inputs:
    <post_dir>          Folder containing image-1-full.png (preferred) or
                        new-image.jpg (fallback)
Options:
    --src PATH          Source image override (default: image-1-full.png,
                        falls back to new-image.jpg if missing)
    --logo PATH         Logo SVG/PNG (default: WP skill's assets/Logo.svg)
    --out PATH          Output path (default: <post_dir>/new-image-logo.jpg)
    --pad N             Inner padding inside the placeholder, px (default 10)
    --quality N         JPEG quality (default 92)
    --debug             Print detected placeholder bbox + logo size

Output (stdout, last line):
    OK <out_path> placeholder=(x,y,w,h) logo=(w,h)

Failure modes:
    - No dashed placeholder found → exit 2 with PLACEHOLDER_NOT_FOUND
    - Source image missing → exit 2 with SRC_MISSING
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
import numpy as np
from scipy import ndimage

WP_SKILL_LOGO = Path(
    "/Users/binhquach/.claude/skills/wordpress-generate-missing-images/assets/Logo.svg"
)


def detect_placeholder(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Find the dashed rectangle in the top header band.

    Dashed stroke is light periwinkle blue (~ R 170-205, G 195-225, B 235-252)
    on a slightly lighter header background. Dilate to bridge the dash gaps,
    then take the largest left-side rectangular component.
    """
    arr = np.array(img.convert("RGB"))
    H, W = arr.shape[:2]
    # Restrict to top ~22% of image (header band)
    y_max = int(H * 0.22)
    strip = arr[0:y_max, :]
    r = strip[:, :, 0].astype(int)
    g = strip[:, :, 1].astype(int)
    b = strip[:, :, 2].astype(int)
    mask = (
        (r >= 170) & (r <= 205)
        & (g >= 195) & (g <= 225)
        & (b >= 235) & (b <= 252)
    )
    # Bridge dash gaps
    dilated = ndimage.binary_dilation(
        mask, structure=np.ones((11, 11), int), iterations=2
    )
    labels, n = ndimage.label(dilated)
    best = None
    for i in range(1, n + 1):
        region = (labels == i) & mask
        ys, xs = np.where(region)
        if len(xs) < 80:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        w, h = x1 - x0, y1 - y0
        if w < 100 or h < 40:
            continue
        # Must be on the left half (placeholder convention)
        if x0 > W * 0.5:
            continue
        # Reject if too wide+thin (likely a card border or header strip)
        aspect = w / max(h, 1)
        if aspect > 4.0 or aspect < 1.0:
            continue
        score = len(xs)
        if best is None or score > best[0]:
            best = (score, x0, y0, w, h)
    if best is None:
        return None
    _, x, y, w, h = best
    return x, y, w, h


def render_logo(svg_or_png: Path, target_w: int = 1500) -> Image.Image:
    """Render SVG at high resolution (or load PNG) and tight-crop to glyph bbox."""
    ext = svg_or_png.suffix.lower()
    if ext == ".svg":
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(target_w), str(svg_or_png), "-o", tmp_path],
                check=True,
                capture_output=True,
            )
            logo = Image.open(tmp_path).convert("RGBA").copy()
        finally:
            os.unlink(tmp_path)
    else:
        logo = Image.open(svg_or_png).convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    return logo


def overlay(post_dir: Path, src_override: Path | None, logo_path: Path,
            out_path: Path, pad: int, quality: int, debug: bool) -> int:
    if src_override is not None:
        src = src_override
    else:
        full = post_dir / "image-1-full.png"
        jpg = post_dir / "new-image.jpg"
        src = full if full.exists() else jpg
    if not src.exists():
        print(f"SRC_MISSING {src}", file=sys.stderr)
        return 2

    img = Image.open(src)
    if debug:
        print(f"[debug] src={src} size={img.size}", file=sys.stderr)

    ph = detect_placeholder(img)
    if ph is None:
        print("PLACEHOLDER_NOT_FOUND", file=sys.stderr)
        return 2
    px, py, pw, ph_h = ph
    if debug:
        print(f"[debug] placeholder=(x{px}, y{py}, w{pw}, h{ph_h}) "
              f"aspect={pw/ph_h:.2f}", file=sys.stderr)

    logo = render_logo(logo_path)
    if debug:
        print(f"[debug] logo_tight={logo.size} aspect={logo.width/logo.height:.2f}",
              file=sys.stderr)

    # Scale logo to fit inside placeholder (with inner padding), preserve aspect
    max_w = max(1, pw - 2 * pad)
    max_h = max(1, ph_h - 2 * pad)
    scale = min(max_w / logo.width, max_h / logo.height)
    new_w = max(1, int(logo.width * scale))
    new_h = max(1, int(logo.height * scale))
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # Center inside placeholder (keep dashed border visible)
    lx = px + (pw - logo.width) // 2
    ly = py + (ph_h - logo.height) // 2

    base = img.convert("RGBA")
    base.alpha_composite(logo, (lx, ly))
    base.convert("RGB").save(out_path, "JPEG", quality=quality)
    print(f"OK {out_path} placeholder=({px},{py},{pw},{ph_h}) "
          f"logo=({logo.width},{logo.height}) pos=({lx},{ly})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("post_dir", type=Path)
    p.add_argument("--src", type=Path, default=None)
    p.add_argument("--logo", type=Path, default=WP_SKILL_LOGO)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--pad", type=int, default=10)
    p.add_argument("--quality", type=int, default=92)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    post_dir = args.post_dir.resolve()
    if not post_dir.is_dir():
        print(f"post_dir not a directory: {post_dir}", file=sys.stderr)
        return 2

    out_path = args.out or (post_dir / "new-image-logo.jpg")
    return overlay(
        post_dir=post_dir,
        src_override=args.src,
        logo_path=args.logo,
        out_path=out_path,
        pad=args.pad,
        quality=args.quality,
        debug=args.debug,
    )


if __name__ == "__main__":
    sys.exit(main())
