#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Attach a local image to the ChatGPT composer's file input by JS injection.

Why JS injection: OpenClaw's `upload --element` + file-chooser interception
doesn't bind to ChatGPT's hidden `<input id="upload-files">` reliably (the
React handler is bound to a synthetic 'change' event that the OS-level
chooser doesn't fire when openclaw intercepts). So we push base64 in chunks,
reconstruct a File in the browser, and dispatch `change` ourselves.

Usage:
    uv run attach_image_to_chatgpt.py <local_file> [--input-id upload-files] [--mime image/jpeg]
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

OPENCLAW = "/opt/homebrew/bin/openclaw"
CHUNK = 280_000  # argv-safe (macOS ARG_MAX is ~256KB-1MB)


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
    args = sys.argv[1:]
    if not args:
        print("Usage: attach_image_to_chatgpt.py <local_file> [--input-id ID] [--mime MIME]", file=sys.stderr)
        return 2
    local_file = Path(args[0])
    input_id = "upload-files"
    mime = "image/jpeg"
    i = 1
    while i < len(args):
        if args[i] == "--input-id":
            input_id = args[i + 1]
            i += 2
        elif args[i] == "--mime":
            mime = args[i + 1]
            i += 2
        else:
            print(f"unknown arg {args[i]}", file=sys.stderr)
            return 2

    data = local_file.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    print(f"local_file={local_file} size={len(data)} b64len={len(b64)}")

    # 1) reset accumulator
    evaluate("() => { window._chatGptUploadBuf = ''; return 'reset'; }")

    # 2) push chunks
    chunks_needed = (len(b64) + CHUNK - 1) // CHUNK
    for n in range(chunks_needed):
        piece = b64[n * CHUNK:(n + 1) * CHUNK]
        fn = "() => { window._chatGptUploadBuf += " + json.dumps(piece) + "; return window._chatGptUploadBuf.length; }"
        ret = unwrap(evaluate(fn))
        print(f"  chunk {n+1}/{chunks_needed} -> accumulator={ret}")

    # 3) verify
    total = unwrap(evaluate("() => { return window._chatGptUploadBuf.length; }"))
    if str(total) != str(len(b64)):
        print(f"size mismatch: expected {len(b64)}, got {total}", file=sys.stderr)
        return 1

    # 4) build File and attach
    inject = (
        "() => { return new Promise(function(resolve) {"
        "  var b64 = window._chatGptUploadBuf;"
        "  var bin = atob(b64);"
        "  var arr = new Uint8Array(bin.length);"
        "  for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);"
        f"  var f = new File([arr], {json.dumps(local_file.name)}, {{ type: {json.dumps(mime)} }});"
        "  var dt = new DataTransfer();"
        "  dt.items.add(f);"
        f"  var inp = document.getElementById({json.dumps(input_id)});"
        "  if (!inp) { resolve('ERR no input ' + " + json.dumps(input_id) + "); return; }"
        "  inp.files = dt.files;"
        "  inp.dispatchEvent(new Event('change', { bubbles: true }));"
        "  window._chatGptUploadBuf = '';"
        "  setTimeout(function(){ resolve('OK assigned ' + inp.files.length + ' file(s)'); }, 300);"
        "}); }"
    )
    ret = unwrap(evaluate(inject))
    print(ret)
    return 0 if str(ret).startswith("OK") else 1


if __name__ == "__main__":
    sys.exit(main())
