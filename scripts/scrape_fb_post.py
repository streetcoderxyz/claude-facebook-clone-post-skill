#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Scrape a single Facebook post (caption + image URLs) using the openclaw browser
already navigated to the post URL.

Approach: try multiple selectors (FB layout changes often) and pick the longest
plausible caption text + collect image candidates from <img> tags whose src is on
scontent.* CDN. Returns JSON to stdout.

Usage (after `openclaw browser open <fb_post_url>`):
    uv run scrape_fb_post.py <output_dir> <slot_id>

Writes <output_dir>/<slot_id>/source-caption.txt and source-image-url.txt.
Image bytes themselves are fetched separately (see download_image_via_browser.py).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

OPENCLAW = "/opt/homebrew/bin/openclaw"
TIMEOUT_MS = "60000"

EXTRACT_JS = r"""
() => {
  // Caption candidates: FB labels caption containers differently across surfaces.
  // We try a few selectors, take the longest non-trivial text.
  var captionSels = [
    "[data-ad-preview=\"message\"]",
    "[data-ad-comet-preview=\"message\"]",
    "div[data-testid=\"post_message\"]",
    "div[dir=\"auto\"]"
  ];
  var bestCaption = "";
  captionSels.forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(el) {
      var t = (el.innerText || el.textContent || "").trim();
      // Filter UI strings (Like, Comment, Share) by length and content.
      if (t.length > bestCaption.length && t.length > 40 && t.indexOf("·") !== 0) {
        bestCaption = t;
      }
    });
  });

  // Image candidates: FB photo posts use scontent.* CDN. Filter by URL substring,
  // by minimum natural size, and dedupe.
  var seen = {};
  var imgs = [];
  document.querySelectorAll("img").forEach(function(img) {
    var src = img.src || "";
    if (src.indexOf("scontent") === -1 && src.indexOf("fbcdn") === -1) return;
    if (img.naturalWidth < 400) return;
    var key = src.split("?")[0];
    if (seen[key]) return;
    seen[key] = 1;
    imgs.push({ src: src, w: img.naturalWidth, h: img.naturalHeight, alt: img.alt || "" });
  });
  imgs.sort(function(a, b) { return (b.w * b.h) - (a.w * a.h); });
  return JSON.stringify({ caption: bestCaption, images: imgs.slice(0, 5), title: document.title });
}
"""


def run_evaluate(fn: str) -> str:
    env = os.environ.copy()
    env["OPENCLAW_TIMEOUT"] = TIMEOUT_MS
    out = subprocess.run(
        [OPENCLAW, "browser", "evaluate", "--fn", fn],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: scrape_fb_post.py <output_dir> <slot_id>", file=sys.stderr)
        return 2
    out_dir = Path(sys.argv[1]) / sys.argv[2]
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = run_evaluate(EXTRACT_JS)
    # openclaw wraps the return value in JSON quotes; unwrap if needed
    if raw.startswith('"') and raw.endswith('"'):
        raw = json.loads(raw)
    data = json.loads(raw)

    caption = data.get("caption") or ""
    images = data.get("images") or []
    if not caption:
        print("WARN: no caption found", file=sys.stderr)
    if not images:
        print("ERR: no images found on page", file=sys.stderr)
        return 1

    (out_dir / "source-caption.txt").write_text(caption, encoding="utf-8")
    (out_dir / "source-image-url.txt").write_text(images[0]["src"], encoding="utf-8")
    (out_dir / "source-meta.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OK caption_len={len(caption)} image_count={len(images)} best_src={images[0]['src'][:100]}")
    print(f"  saved to {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
