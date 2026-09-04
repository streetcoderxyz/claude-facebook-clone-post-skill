#!/usr/bin/env python3
"""Place a (possibly landscape) infographic onto a square Omini-brand canvas
and composite the brand frame on top.

ChatGPT's image tool frequently ignores 1:1 requests and returns 1792x1024.
Cover-cropping that to a square (what frame_image.py does) would slice off the
left and right columns of a comparison infographic. So instead we FIT the art
inside the square, on a brand-tinted background, above the reserved band that
the brand frame's blue bar occupies.

Usage:
    uv run compose_brand_square.py <post_dir> [--size 1440]
    uv run compose_brand_square.py <image.png> --out <out.png>

Reads   <post_dir>/image-1-full.png  (falls back to new-image.jpg / image-1.jpg)
Writes  <post_dir>/new-image-framed.png

Options:
    --size N        Square edge in px (default 1440).
    --frame PATH    Brand frame PNG (default: chatgpt-create-pharmacy-post asset).
    --bar-top F     Fraction of height where the frame's blue bar starts
                    (default 0.81). Art is fitted above this line.
    --margin F      Side margin as a fraction of width (default 0.02).
    --out PATH      Explicit output path.

Output line:
    OK <out> canvas=NxN art=WxH at=(x,y)
"""

import argparse
import os
import sys

from PIL import Image

DEFAULT_FRAME = os.path.expanduser(
    "~/.claude/skills/chatgpt-create-pharmacy-post/assets/frame.png"
)
# Sampled from the Omini brand ground: white fading to pale blue.
BG_TOP = (255, 255, 255)
BG_BOTTOM = (234, 243, 252)


def vertical_gradient(size, top, bottom):
    grad = Image.new("RGB", (1, size), top)
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return grad.resize((size, size), Image.BILINEAR).convert("RGBA")


def pick_source(target):
    if os.path.isfile(target):
        return target
    for name in ("image-1-full.png", "new-image.jpg", "image-1.jpg", "image.png"):
        p = os.path.join(target, name)
        if os.path.isfile(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="post dir or image file")
    ap.add_argument("--size", type=int, default=1440)
    ap.add_argument("--frame", default=DEFAULT_FRAME)
    ap.add_argument("--bar-top", type=float, default=0.81)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--out")
    args = ap.parse_args()

    target = os.path.expanduser(args.target)
    src = pick_source(target)
    if not src:
        print(f"SRC_MISSING {target}", file=sys.stderr)
        sys.exit(2)
    frame_path = os.path.expanduser(args.frame)
    if not os.path.isfile(frame_path):
        print(f"FRAME_MISSING {frame_path}", file=sys.stderr)
        sys.exit(2)

    S = args.size
    canvas = vertical_gradient(S, BG_TOP, BG_BOTTOM)

    art = Image.open(src).convert("RGBA")
    margin = round(S * args.margin)
    avail_w = S - 2 * margin
    avail_h = round(S * args.bar_top) - 2 * margin

    scale = min(avail_w / art.width, avail_h / art.height)
    new_w, new_h = round(art.width * scale), round(art.height * scale)
    art = art.resize((new_w, new_h), Image.LANCZOS)

    x = (S - new_w) // 2
    y = margin + (avail_h - new_h) // 2
    canvas.alpha_composite(art, (x, y))

    frame = Image.open(frame_path).convert("RGBA").resize((S, S), Image.LANCZOS)
    result = Image.alpha_composite(canvas, frame)

    out = args.out
    if not out:
        out = (
            os.path.join(target, "new-image-framed.png")
            if os.path.isdir(target)
            else os.path.splitext(target)[0] + "-framed.png"
        )
    result.convert("RGB").save(out, "PNG")
    print(f"OK {out} canvas={S}x{S} art={new_w}x{new_h} at=({x},{y})")


if __name__ == "__main__":
    main()
