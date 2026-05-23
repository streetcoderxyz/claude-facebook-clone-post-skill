#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Download all photos in a Facebook post's album by FBID list.

Given a comma-separated list of FBIDs and the set ID (pcb.XXXX), navigate to each
photo's permalink, scrape the high-res image src (from the rendered DOM, after
waiting for it to load), and fetch the image via the browser session.

Usage:
    uv run download_fb_album.py <output_dir> <set_id> <fbid1,fbid2,...>

Saves each image as <output_dir>/post-N/source-image.jpg.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OPENCLAW = "/opt/homebrew/bin/openclaw"
SCRIPT_DIR = Path(__file__).resolve().parent
DOWNLOAD_SCRIPT = SCRIPT_DIR / "download_image_via_browser.py"


def openclaw(args: list[str], timeout_ms: int = 60_000) -> str:
    env = os.environ.copy()
    env["OPENCLAW_TIMEOUT"] = str(timeout_ms)
    out = subprocess.run([OPENCLAW] + args, env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def evaluate(fn: str, timeout_ms: int = 60_000) -> str:
    return openclaw(["browser", "evaluate", "--fn", fn], timeout_ms)


def unwrap(s: str) -> str:
    if s.startswith('"') and s.endswith('"'):
        return json.loads(s)
    return s


GRAB_BIG_IMG = r"""
() => {
  var url = location.href;
  var m = url.match(/fbid=(\d+)/);
  var fbid = m ? m[1] : null;
  var big = null;
  document.querySelectorAll("img").forEach(function(img) {
    if (img.src.indexOf("scontent") === -1 && img.src.indexOf("fbcdn") === -1) return;
    if (img.naturalWidth < 1000) return;
    if (!big || img.naturalWidth * img.naturalHeight > big.w * big.h) {
      big = {src: img.src, w: img.naturalWidth, h: img.naturalHeight};
    }
  });
  return JSON.stringify({fbid: fbid, big: big});
}
"""


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: download_fb_album.py <output_dir> <set_id> <fbid1,fbid2,...>", file=sys.stderr)
        return 2
    out_dir = Path(sys.argv[1])
    set_id = sys.argv[2]
    fbids = [f.strip() for f in sys.argv[3].split(",") if f.strip()]
    print(f"Downloading {len(fbids)} photos to {out_dir}/")

    results = []
    for i, fbid in enumerate(fbids, start=1):
        slot_dir = out_dir / f"post-{i}"
        slot_dir.mkdir(parents=True, exist_ok=True)
        photo_url = f"https://www.facebook.com/photo/?fbid={fbid}&set={set_id}"
        print(f"\n[{i}/{len(fbids)}] fbid={fbid}")

        # Navigate
        openclaw(["browser", "open", photo_url])
        # Wait for the high-res image to load (poll up to ~12s)
        big_src = None
        for attempt in range(8):
            time.sleep(1.5)
            raw = unwrap(evaluate(GRAB_BIG_IMG))
            data = json.loads(raw)
            if data.get("fbid") == fbid and data.get("big") and data["big"].get("w", 0) >= 1500:
                big_src = data["big"]["src"]
                print(f"  loaded w={data['big']['w']} h={data['big']['h']} (attempt {attempt+1})")
                break
        if not big_src:
            print(f"  WARN: no high-res image after wait; trying anyway with last seen")
            if data.get("big"):
                big_src = data["big"]["src"]
        if not big_src:
            print(f"  SKIP: no image found")
            results.append({"slot": i, "fbid": fbid, "status": "no_image"})
            continue

        # Save the URL + fbid
        (slot_dir / "source-image-url.txt").write_text(big_src, encoding="utf-8")
        (slot_dir / "source-fbid.txt").write_text(fbid, encoding="utf-8")

        # Download via the existing helper
        out_jpeg = slot_dir / "source-image.jpg"
        rc = subprocess.run(
            ["uv", "run", str(SCRIPT_DIR / "download_image_via_browser.py"), big_src, str(out_jpeg)],
            capture_output=True, text=True
        )
        if rc.returncode != 0:
            print(f"  download FAILED: {rc.stderr[:200]}")
            results.append({"slot": i, "fbid": fbid, "status": "download_failed"})
            continue
        size = out_jpeg.stat().st_size
        print(f"  OK {out_jpeg.name} size={size}")
        results.append({"slot": i, "fbid": fbid, "status": "ok", "path": str(out_jpeg), "size": size})

    (out_dir / "album-manifest.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nManifest: {out_dir}/album-manifest.json")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"Downloaded {ok}/{len(fbids)}")
    return 0 if ok == len(fbids) else 1


if __name__ == "__main__":
    sys.exit(main())
