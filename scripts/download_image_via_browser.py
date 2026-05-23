#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Download an image URL via the currently-active browser tab's `fetch()`
(so FB CDN cookies and Referer are correct), transfer base64 to disk,
and decode. Single-shot transfer with chunk fallback.

Usage:
    uv run download_image_via_browser.py <image_url> <output_jpeg_path>
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OPENCLAW = "/opt/homebrew/bin/openclaw"
CHUNK = 500_000


def evaluate(fn: str, timeout_ms: int = 120_000) -> str:
    env = os.environ.copy()
    env["OPENCLAW_TIMEOUT"] = str(timeout_ms)
    out = subprocess.run(
        [OPENCLAW, "browser", "evaluate", "--fn", fn],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def unwrap(s: str) -> str:
    if s.startswith('"') and s.endswith('"'):
        return json.loads(s)
    return s


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: download_image_via_browser.py <image_url> <output_jpeg_path>", file=sys.stderr)
        return 2
    url = sys.argv[1]
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) fetch into window._fbdl_b64
    fetch_fn = (
        "() => { return new Promise(function(resolve){ fetch("
        + json.dumps(url)
        + ").then(function(r){return r.blob();}).then(function(blob){ var fr = new FileReader(); fr.onloadend = function(){ var b64 = fr.result.split(\",\")[1]; window._fbdl_b64 = b64; resolve(\"OK len=\" + b64.length + \" type=\" + blob.type); }; fr.readAsDataURL(blob); }).catch(function(e){ resolve(\"ERR \" + e.message); }); }); }"
    )
    result = unwrap(evaluate(fetch_fn))
    if not result.startswith("OK"):
        print(f"fetch failed: {result}", file=sys.stderr)
        return 1
    m = re.search(r"len=(\d+)", result)
    if not m:
        print(f"unexpected fetch output: {result}", file=sys.stderr)
        return 1
    b64len = int(m.group(1))
    print(f"Fetched b64len={b64len} {result}")

    # 2) transfer single-shot (FB images are usually small)
    transfer_fn = "() => { return window._fbdl_b64 || \"\"; }"
    raw = unwrap(evaluate(transfer_fn))
    if len(raw) != b64len:
        # chunk fallback
        print(f"single-shot mismatch (got {len(raw)} of {b64len}); chunking", file=sys.stderr)
        parts = []
        cursor = 0
        while cursor < b64len:
            end = min(cursor + CHUNK, b64len)
            chunk_fn = f"() => {{ return window._fbdl_b64.substring({cursor}, {end}); }}"
            piece = unwrap(evaluate(chunk_fn))
            parts.append(piece)
            cursor = end
        raw = "".join(parts)
        if len(raw) != b64len:
            print(f"chunked transfer mismatch ({len(raw)} of {b64len})", file=sys.stderr)
            return 1

    # 3) decode + write
    img_bytes = base64.b64decode(raw)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    # Convert to jpeg via sips for consistency
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", tmp_path, "--out", str(out_path)], check=True, capture_output=True)
    else:
        Path(tmp_path).rename(out_path)
        tmp_path = None
    if tmp_path:
        Path(tmp_path).unlink(missing_ok=True)

    size = out_path.stat().st_size
    print(f"OK saved {out_path} size={size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
