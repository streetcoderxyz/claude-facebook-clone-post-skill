---
name: facebook-clone-post
description: Clone a Facebook post by scraping its caption and image, then regenerate both via ChatGPT (web) — caption rewritten in Vietnamese, image redrawn in the same infographic style. Saves each cloned post locally as caption + image for manual upload to your group. Designed for medical-infographic pages like ydgr.net. Uses OpenClaw browser automation against a logged-in Brave profile.
---

# Clone Facebook Post (caption + image restyle)

Takes a batch of Facebook post URLs, scrapes each one's caption + main image, then uses ChatGPT to:
1. Rewrite each caption in fresh Vietnamese (same meaning, different wording — avoid plagiarism)
2. Recreate each image in the same infographic style (source image attached as visual reference)

Outputs a folder per source post containing the original caption/image and the regenerated caption/image. You upload to your FB group manually.

## When to use this skill

Use when the user:
- Asks to "clone" or "rephrase" or "restyle" one or more Facebook posts
- Provides FB post URLs from medical-infographic style pages (e.g. ydgr.net)
- Wants caption + image both regenerated, saved locally

Do NOT use for:
- Direct sharing/reposting (no regeneration) — use `facebook-share-to-groups` instead
- Posting original content from scratch to fanpages — use `facebook-post-to-groups` or `chatgpt-create-omini-care-post`
- Cloning to WordPress — use `wordpress-create-post-from-source`

## Prerequisites

1. `openclaw browser status` → `running: true`. If not: `openclaw browser start && sleep 4`
2. Brave profile must be logged in to **both Facebook AND ChatGPT**. Login walls → **stop and notify**, never automate login.
3. `OPENCLAW_TIMEOUT=60000` prefix on every `openclaw browser` command (or 120000 for heavy ops). See cross-cutting rules from `wordpress-generate-missing-images` skill — same gateway behavior applies here.

## Helper Scripts

Local (in this skill's `scripts/`):

| Script | Purpose |
|--------|---------|
| `scrape_fb_post.py` | Extract caption + image URLs from the currently-open FB post tab. Writes `source-caption.txt`, `source-image-url.txt`, `source-meta.json`. |
| `download_image_via_browser.py` | Fetch an image URL via the browser session (so FB CDN cookies/referer work), save as JPEG. |
| `attach_image_to_chatgpt.py` | Attach a local image to the ChatGPT composer's `#upload-files` input via base64 streaming + React-aware `change` dispatch. Used in Phase 3 step 2. |
| `overlay_logo_on_clone.py` | Auto-detect the dashed logo placeholder in the generated infographic and composite the Omini logo inside it. Outputs `new-image-logo.jpg`. Used in Phase 3.5. |

Shared (reuse from `~/.claude/skills/wordpress-generate-missing-images/scripts/` via absolute paths):

| Script | Purpose |
|--------|---------|
| `fetch_chatgpt_image.py` | Download a ChatGPT-generated image (filter `file_` prefix + naturalWidth ≥ 1000). Same usage as in WP skill. |
| `transfer_b64_from_browser.py` | Transfer a base64 string from a browser variable to disk. |
| `delete_chatgpt_thread.py` | Soft-delete the current ChatGPT thread. |
| `run_js.py` | Execute a `.js` file via openclaw without shell-escape pain. |

Run with `uv run <full-path>.py ...`.

---

## Configurable Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| **SOURCE_URLS** | Yes | — | Comma-or-newline-separated FB post URLs to clone |
| **OUT_DIR** | No | `/tmp/fb-clone/<timestamp>` | Where to write cloned packages |
| **STYLE_HINT** | No | `ydgr.net infographic, top title, 2-3 side sections with icons, products with white-circle dotted labels` | Style description sent to ChatGPT as part of the image-regen prompt |
| **HIDE_PRODUCT_LABELS** | No | `true` | If `true`, append "phủ chấm tròn trắng lên nhãn sản phẩm" to image prompts |
| **CAPTION_TONE** | No | `informational, friendly, 1st-person Vietnamese, end with soft CTA` | Tone for rewritten captions |

---

## Workflow

### Phase 0 — Setup

1. Parse SOURCE_URLS. Validate each looks like a FB post URL (contains `facebook.com` and either `/posts/` or `/permalink/` or `pfbid`).
2. Decide `OUT_DIR` and `BATCH_ID = OUT_DIR's basename`. Create base dir.
3. Verify browser:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser status
   ```

   If `running: false` → `openclaw browser start && sleep 4`.

### Phase 1 — Scrape Source Posts (one tool call per URL — NO Bash loops)

For each URL `i` (1-indexed):

1. Navigate:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser open "<SOURCE_URL_i>"
   sleep 5
   ```

2. **Verify not a login wall.** If `document.title` contains "Log in to Facebook" or the URL redirects to `/login` → **STOP**, notify user.

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn "() => { return JSON.stringify({title: document.title, url: location.href}); }"
   ```

3. **Dismiss any "See more" truncation** so the full caption is in DOM:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn '() => { var btns = Array.from(document.querySelectorAll("div[role=button]")).filter(function(b){ var t = (b.textContent||"").trim().toLowerCase(); return t === "see more" || t === "xem thêm"; }); btns.forEach(function(b){ b.click(); }); return btns.length; }'
   sleep 2
   ```

4. **Scrape:**

   ```bash
   uv run ~/.claude/skills/facebook-clone-post/scripts/scrape_fb_post.py <OUT_DIR> post-<i>
   ```

   Output: `OK caption_len=... image_count=... best_src=...`. The script writes `source-caption.txt`, `source-image-url.txt`, `source-meta.json` under `<OUT_DIR>/post-<i>/`.

   If `caption_len < 40` or `image_count == 0` → flag this slot as `INCOMPLETE` in the final summary; **do not** abort the whole batch.

5. **Download the source image** (used as ChatGPT style reference later):

   ```bash
   URL=$(cat <OUT_DIR>/post-<i>/source-image-url.txt) && \
   uv run ~/.claude/skills/facebook-clone-post/scripts/download_image_via_browser.py "$URL" <OUT_DIR>/post-<i>/source-image.jpg
   ```

Repeat for every URL. **No Bash for-loops** — one tool call per URL.

### Phase 2 — Open ChatGPT and Rewrite Captions (batched)

The captions are short Vietnamese text — rewrite them all in a single ChatGPT message to save round-trips.

1. Open ChatGPT:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser open "https://chatgpt.com" && sleep 5
   ```

   Verify not login. Find composer ref:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser snapshot --interactive --compact 2>&1 | grep -iE "textbox.*ChatGPT" | head -1
   ```

2. Build a single prompt that lists all source captions and asks for rewrites. Use the **Write tool** (not bash echo) for Vietnamese content:

   ```
   Tôi cần viết lại {N} caption Facebook bằng tiếng Việt. Yêu cầu:
   - Cùng chủ đề và thông tin chính, nhưng dùng câu chữ khác hẳn (tránh trùng lặp với bản gốc).
   - Tông giọng: <CAPTION_TONE>.
   - Giữ độ dài tương đương bản gốc (±20%).
   - Mỗi caption tách rõ bằng dòng "---POST <số>---".
   - Cuối mỗi caption thêm 1 dòng CTA mềm (ví dụ: "Lưu lại để dùng khi cần nhé!").

   Trả về đúng định dạng:
   ---POST 1---
   <caption mới>
   ---POST 2---
   <caption mới>
   ...

   Caption gốc:

   ---SOURCE 1---
   <source-caption-1>
   ---SOURCE 2---
   <source-caption-2>
   ...
   ```

   Write this to `<OUT_DIR>/_caption-prompt.txt`. Then fill + send:

   ```bash
   P=$(cat <OUT_DIR>/_caption-prompt.txt) && OPENCLAW_TIMEOUT=60000 openclaw browser fill --fields "[{\"ref\":\"<composer_ref>\",\"value\":$(printf '%s' "$P" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}]"
   ```

3. Re-snapshot, click `Send prompt`, then wait:

   ```bash
   # Monitor — wait for stop-button to disappear
   until OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn "() => { var s = document.querySelector('button[data-testid=\"stop-button\"]'); return s ? 'gen' : 'done'; }" 2>/dev/null | grep -q "done"; do sleep 4; done; echo "CAPTIONS_DONE"
   ```

4. **Extract the response text** and split into per-post files:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn '() => { var msgs = document.querySelectorAll("[data-message-author-role=assistant]"); return msgs.length ? msgs[msgs.length-1].innerText : "NO_RESPONSE"; }'
   ```

   Save the raw response to `<OUT_DIR>/_caption-response.txt`, then parse with `awk`/`python3` to split on `---POST N---` markers and write each chunk to `<OUT_DIR>/post-<i>/new-caption.txt`.

   ```bash
   python3 - <<'PY'
   import re, pathlib, sys
   base = pathlib.Path("<OUT_DIR>")
   raw = (base / "_caption-response.txt").read_text(encoding="utf-8")
   parts = re.split(r"---POST\s+(\d+)---", raw)
   for i in range(1, len(parts), 2):
       idx = int(parts[i])
       body = parts[i+1].strip().split("---SOURCE")[0].strip()
       (base / f"post-{idx}" / "new-caption.txt").write_text(body, encoding="utf-8")
       print(f"post-{idx}: {len(body)} chars")
   PY
   ```

   Sanity check: every source post should now have a `new-caption.txt`. Flag any missing slots.

### Phase 3 — Regenerate Each Image (one ChatGPT message per post, source image attached)

ChatGPT's image-gen treats an attached image as a strong style reference. We attach the source image and prompt for a redrawn infographic on the same topic.

> **Critical:** ChatGPT image-gen does NOT preserve attached people, products, or text verbatim — it interprets the *style* (layout, color palette, icon vocabulary). Real brand bottles in the source will come out as generic bottles. Real photos of patients will come out as illustrated characters. This is desirable for a clone — we're not laundering copyrighted artwork.

For each post `i` (one set of tool calls per post — NO bash loop):

1. **Re-snapshot ChatGPT** to find the composer textbox ref:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser snapshot --interactive --compact 2>&1 | grep -iE "textbox.*ChatGPT|Send prompt" | head -3
   ```

2. **Attach the source image via the `attach_image_to_chatgpt.py` helper.** OpenClaw's `upload --element` arms the next file chooser but ChatGPT's React handler doesn't see the resulting `change` event reliably, so the bundled helper streams the file as base64, constructs a `File` in-page, sets `input.files`, and dispatches `change` itself. **Always use the helper — do not call `openclaw browser upload` directly for ChatGPT.**

   ```bash
   uv run ~/.claude/skills/facebook-clone-post/scripts/attach_image_to_chatgpt.py \
     <OUT_DIR>/post-<i>/source-image.jpg
   ```

   Expected output ends with `OK assigned 1 file(s)`.

   **Verify attachment** by counting `<img>` elements inside the composer form:

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn '() => { var ta = document.querySelector("#prompt-textarea, [contenteditable=true]"); var form = ta && ta.closest("form"); var imgs = form ? form.querySelectorAll("img").length : 0; var dlg = document.querySelector("[role=dialog], [role=alertdialog]"); return JSON.stringify({form_imgs: imgs, dialog: dlg ? dlg.innerText.slice(0,200) : null}); }'
   ```

   Interpret `form_imgs`:
   - `>=1` → attached. (If exactly 1 and no dialog → ready to send. If `>1` → duplicate from a prior retry, click the last X to remove extras: see Error recovery.)
   - `0` with `dialog: "You've already uploaded this file..."` → ChatGPT dedups by **content hash across sessions**. The file is NOT in the composer. Recover:
     1. Re-encode the source to break the hash, then re-attach:
        ```bash
        sips -s format jpeg -s formatOptions 92 \
          <OUT_DIR>/post-<i>/source-image.jpg \
          --out /tmp/openclaw/uploads/source-post-<i>-v2.jpg
        OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn '() => { var b = document.querySelector("[role=dialog] button"); if (b) b.click(); return "ok"; }'
        uv run ~/.claude/skills/facebook-clone-post/scripts/attach_image_to_chatgpt.py \
          /tmp/openclaw/uploads/source-post-<i>-v2.jpg
        ```
     2. Re-verify. If it STILL dedups, treat the slot as INCOMPLETE and move on.
   - `0` with no dialog → helper failure. Re-run the helper once; if still 0, flag INCOMPLETE.

3. **Build the image prompt** and write it via the Write tool:

   ```
   Hãy tạo lại ảnh infographic dựa trên ảnh tôi đính kèm làm tham chiếu phong cách. Yêu cầu:
   - Tỉ lệ 1:1 (vuông) hoặc 4:5, kích thước tối thiểu 1024px.
   - Cùng bố cục, palette màu, kiểu icon và typography như ảnh đính kèm.
   - Chủ đề: <CHỦ_ĐỀ_TỪ_CAPTION_MỚI>.
   - Tất cả văn bản trong ảnh PHẢI là tiếng Việt chính xác, có dấu, không lỗi chính tả.
   - <STYLE_HINT>
   - HIDE_PRODUCT_LABELS=true: phủ chấm tròn trắng lên mọi nhãn hiệu/logo sản phẩm để giấu thương hiệu.
   - KHÔNG sao chép nguyên văn text từ ảnh gốc — viết lại các tiêu đề/bullet bằng từ ngữ khác.
   - KHÔNG có khuôn mặt người thật, KHÔNG có ảnh y khoa thật — chỉ minh hoạ vector phẳng.
   - Header trên cùng: dải xanh nhạt. Ở GÓC TRÊN BÊN TRÁI vẽ một khung dạng nét đứt (dashed border) màu xanh nhạt, kích thước khoảng 200×100 px, để chừa chỗ dán logo sau bằng chương trình — KHÔNG vẽ logo hay text nào bên trong khung này.
   ```

   The "dashed rectangle in top-left" instruction is what Phase 3.5's overlay step targets. If you change/omit it, the overlay will silently fall back to a corner stamp (`--fallback-corner top-left`). Pass `--fallback-corner none` if you want a hard failure instead.

   ChatGPT ignores this instruction ~30% of the time even when present, so the fallback is a normal outcome — not an error.

   Topic extraction: pull the first 1-2 lines or H1-equivalent from `new-caption.txt`.

4. **Fill + send the prompt.** Use the Vietnamese-safe fill pattern from Phase 2, then trigger send via JS (clicking the snapshot `ref` for "Send prompt" frequently no-ops — the React handler is bound to the testid-tagged button):

   ```bash
   OPENCLAW_TIMEOUT=120000 openclaw browser evaluate --fn '() => { var b = Array.from(document.querySelectorAll("button")).find(function(b){ return b.getAttribute("data-testid")==="send-button" || (b.getAttribute("aria-label")||"")==="Send prompt"; }); if (!b) return "no_send"; if (b.disabled) return "send_disabled"; b.click(); return "clicked"; }'
   sleep 4
   # Confirm send actually happened — URL transitions from /?model=... to /c/<uuid>
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn '() => JSON.stringify({url: location.href, userMsgs: document.querySelectorAll("[data-message-author-role=user]").length})'
   ```

   If `url` is still the root chat path or `userMsgs === 0` → re-click via JS once more. If still nothing, the composer is in a broken state — re-fill prompt + retry.

5. **Wait for image generation.** The stop button briefly disappears between "thinking" and "rendering" phases, so a bare `until ... done` loop exits prematurely. Also, after several posts in the same thread the raw `imgs.length` keeps climbing as duplicates accumulate (each generated image renders 3 times in the conversation), so an absolute count is unreliable. The robust signal is the count of **unique `file_` ids** ≥ 1000 px wide:

   ```bash
   # Before sending, capture baseline unique-fid count for this thread:
   #   BASELINE_FIDS=$(... | unique file_ids count after the source was attached)
   # Then wait for one more unique fid to appear AND stop-button gone:
   TARGET=$((BASELINE_FIDS + 1))
   until OPENCLAW_TIMEOUT=120000 openclaw browser evaluate --fn "() => { var s = document.querySelector('button[data-testid=\"stop-button\"]'); var imgs = Array.from(document.querySelectorAll('img[src*=\"file_\"]')).filter(function(i){return i.naturalWidth >= 1000;}); var fids = [...new Set(imgs.map(function(i){ var m = i.src.match(/file_[a-f0-9]+/); return m ? m[0] : ''; }).filter(Boolean))]; return (!s && fids.length >= $TARGET) ? 'done' : 'gen'; }" 2>/dev/null | grep -q "done"; do sleep 15; done; echo "IMAGE_DONE"
   ```

   Practical pattern for an N-post batch: after attaching post i's source, the unique-fid count is `2*(i-1) + 1` (each prior post contributed source + gen, plus this post's source). Wait for `2*i`. So for post 2 wait for 4, post 3 wait for 6, etc.

   **Long-running waits**: the `until` loop in the foreground will hit Bash's run-too-long block. Spawn it with `run_in_background: true` and let the harness notify on completion — do NOT chain `sleep 25 && until ...` to "preheat" the wait.

6. **Refusal check** (same as WP skill):

   ```bash
   OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn "() => { var msgs = document.querySelectorAll('[data-message-author-role=assistant]'); var last = msgs[msgs.length-1].textContent.toLowerCase(); return last.indexOf('violate our content policies') !== -1 ? 'REFUSED' : 'ok'; }"
   ```

   On REFUSED: retry with a safer prompt (no real people, no medical procedures). See `wordpress-generate-missing-images` skill's "Safe pivots" list.

7. **Download the generated image.** Multiple `file_` images are in the thread now (every prior post's source + generation, plus this post's source). The newest one is what you want. Snapshot all unique file_ids in order, pick the last as the new one, pass the rest to `--skip-ids`:

   ```bash
   FIDS=$(OPENCLAW_TIMEOUT=60000 openclaw browser evaluate --fn "() => { var imgs = Array.from(document.querySelectorAll('img[src*=\"file_\"]')).filter(function(i){return i.naturalWidth >= 1000;}); var fids = [...new Set(imgs.map(function(i){ var m = i.src.match(/file_[a-f0-9]+/); return m ? m[0] : ''; }).filter(Boolean))]; return fids.join(','); }" 2>&1 | tail -1 | tr -d '"')
   NEW=$(echo "$FIDS" | tr ',' '\n' | tail -1)
   SKIP=$(echo "$FIDS" | sed "s/,$NEW\$//")
   uv run ~/.claude/skills/wordpress-generate-missing-images/scripts/fetch_chatgpt_image.py \
     <OUT_DIR>/post-<i> 1 --skip-ids "$SKIP"
   mv <OUT_DIR>/post-<i>/image-1.jpg <OUT_DIR>/post-<i>/new-image.jpg
   ```

   The DOM serializes images in conversation order, so the last unique file_id is always the most recent generation. No need to manually track `PREV_FIDS` across iterations — recompute the list from the DOM each time.

   Note: the script also writes `image-1-full.png` (the full-res PNG before JPEG re-encode). **Keep this file** — Phase 3.5's logo overlay uses it as the highest-quality canvas.

8. **Verify with Read tool** (visual check before moving on).

Repeat for every post. **No bash for-loops.**

#### Multi-post session bookkeeping

When N posts go through the same ChatGPT thread, the page accumulates `file_` images: every prior post's source + every prior post's generated output. Two consequences:

1. **Wait condition can't use absolute counts** — see Phase 3 step 5. Always recompute the unique-fid count from the DOM, don't hardcode `>= 2`.
2. **`--skip-ids` grows each post** — never paste a stale skip-list from a previous post. The Phase 3 step 7 snippet recomputes the list from the DOM each iteration, which is the right pattern.

If a single thread accumulates more than ~12-15 posts, ChatGPT performance degrades (slower responses, occasional UI lag). For batches > 12 posts, split across multiple threads by deleting the thread mid-batch (Phase 5 instructions) and starting fresh.

### Phase 3.5 — Overlay the Omini logo

The image prompt instructs ChatGPT to draw a dashed rectangle top-left as a logo placeholder (so the model doesn't try to render the brand mark and mangle it). This step paints the real logo into that placeholder.

For each post (one tool call per post — NO bash loop):

```bash
uv run ~/.claude/skills/facebook-clone-post/scripts/overlay_logo_on_clone.py \
  <OUT_DIR>/post-<i> --debug
```

Output:
```
OK <OUT_DIR>/post-<i>/new-image-logo.jpg placeholder=(x,y,w,h) logo=(w,h) pos=(x,y)
```
…or `placeholder=FALLBACK corner=top-left ...` when the detector couldn't find a dashed placeholder (the script's default is to corner-stamp instead of failing — see `--fallback-corner`).

The script:
- Uses `image-1-full.png` (1254×1254 ChatGPT original) as canvas when present; falls back to `new-image.jpg`. **Always overlay on the full-res PNG, never on a downscaled JPEG.**
- Auto-detects the dashed placeholder by blue-channel dominance + connected components (handles both pale periwinkle and saturated medium-blue dashes ChatGPT alternates between).
- Renders the logo SVG large, tight-crops to the visible glyph bbox (the SVG has internal transparent padding that would otherwise make the logo look tiny), then scales-to-fit inside the placeholder with `--pad 10`.
- **Caps the rendered logo at `--max-width-pct` of the image width** (default 0.15 = 15%). If ChatGPT drew an oversized placeholder, the logo won't grow to fill it — it stays a tasteful brand mark, centered inside.
- **Keeps the dashed border visible** as a frame — it doesn't paint over it. Logo is centered inside.

Useful overrides:
- `--max-width-pct 0.12` — slightly smaller logo if 15% feels too big for your design.
- `--fallback-corner top-right|bottom-left|...` — different corner if your prompt reserves a different spot.
- `--fallback-corner none` — fail instead of falling back. Use only when a missing logo is a hard error (e.g. ad approvals).
- `--src <path>` — overlay on a specific source file instead of the auto-pick.

Failure modes:
- Exit 2 `SRC_MISSING` → no `image-1-full.png` and no `new-image.jpg` in the post dir. Upstream step failed; flag INCOMPLETE.
- Exit 2 `PLACEHOLDER_NOT_FOUND` → only happens with `--fallback-corner none`. With the default, this becomes a `placeholder=FALLBACK` output instead.

Verify the result with Read tool, then move to the next post.

### Phase 4 — Write Manifest + Summary

Write `<OUT_DIR>/manifest.json`:

```json
{
  "batch_id": "<BATCH_ID>",
  "created": "<ISO_TIMESTAMP>",
  "posts": [
    {
      "slot": 1,
      "source_url": "...",
      "source_caption_path": "post-1/source-caption.txt",
      "source_image_path": "post-1/source-image.jpg",
      "new_caption_path": "post-1/new-caption.txt",
      "new_image_path": "post-1/new-image.jpg",
      "new_image_logo_path": "post-1/new-image-logo.jpg",
      "status": "ok" | "incomplete:<reason>"
    }
  ]
}
```

Then print to console for each post:

```
post-1 OK
  source: <OUT_DIR>/post-1/source-image.jpg + source-caption.txt
  cloned: <OUT_DIR>/post-1/new-image.jpg + new-caption.txt
```

### Phase 5 — Cleanup

1. **Remove per-post intermediate artifacts.** The `fetch_chatgpt_image.py` pipeline produces ~5 MB of intermediate files per post that aren't needed after Phase 3.5. Keep `image-1-full.png` (highest-quality clean canvas, useful for re-overlay) and drop the rest:

   ```bash
   # For each post directory
   find <OUT_DIR> -maxdepth 2 \( \
       -name 'image-1-resized.png' -o \
       -name 'raw_b64_*.txt' -o \
       -name 'new-image.OLD.jpg' \
     \) -delete
   ```

   Keep per post: `source-image.jpg`, `source-*.txt`, `prompt.txt` (if you saved one), `image-1-full.png` (clean canvas), `new-image.jpg` (clean JPEG), `new-image-logo.jpg` (final deliverable), `new-caption.txt`.

2. Switch to ChatGPT tab and delete the thread (one thread per batch):

   ```bash
   uv run ~/.claude/skills/wordpress-generate-missing-images/scripts/delete_chatgpt_thread.py --current
   ```

3. Close stale tabs (FB post tabs, ChatGPT tab, OpenClaw extension tabs). Aim for ≤ 3 tabs.

4. Do **NOT** delete files in `/tmp/openclaw/uploads/` — they're harmless and may already be referenced.

### Phase 6 — Summary Report

```
Done!

Batch: <BATCH_ID>
Posts cloned: <ok_count> / <total>
Output: <OUT_DIR>/

Per-post:
  post-1: OK  → <OUT_DIR>/post-1/{new-caption.txt, new-image-logo.jpg}
  post-2: INCOMPLETE (caption_too_short)
  post-3: OK  → <OUT_DIR>/post-3/{...}

To upload to your FB group manually:
  1. Open the group composer
  2. Attach <new-image-logo.jpg>  (or new-image.jpg if you don't want the logo)
  3. Paste contents of <new-caption.txt>
  4. Post
```

---

## Rules

1. **All `openclaw browser` commands prefixed with `OPENCLAW_TIMEOUT=60000`** (120000 for ChatGPT image gen).
2. **No Bash for-loops** — one tool call per source URL or per post.
3. **Use `fill --fields '[{"ref":"eXX","value":"..."}]'` for Vietnamese text.** Never `type`. Never bash heredoc into the composer.
4. **Use Write tool for any prompt with diacritics** — then read into a Bash var with `cat | python3 json.dumps`.
5. **Re-snapshot after every action that changes DOM** — ChatGPT composer ref changes after every send.
6. **Never automate login.** Login walls (FB or ChatGPT) → stop, notify user.
7. **One ChatGPT session per batch** — all rewrites + all image gens in the same conversation, so the model accumulates context about your style preferences.
8. **Generate all images sequentially, fully waiting each time.** Never send a new prompt while `stop-button` is present — the request silently fails.
9. **Filter ChatGPT images by `file_` prefix + naturalWidth ≥ 1000** (the shared `fetch_chatgpt_image.py` does this — don't loosen it). **Always pass `--skip-ids <source_file_id>` when downloading clones** — the attached source image is also `file_`-prefixed and would otherwise be picked first.
10. **HIDE_PRODUCT_LABELS defaults to true** — keeps brand names off the regenerated image, safer for ad/regulatory.
11. **Source captions and images stay in the output dir.** Don't auto-delete — the user may want to compare/audit.
12. **The skill never posts to FB itself** — it only stages files. Posting is a manual step (by user choice; see also `facebook-post-to-groups` if they later want automation).
13. **Delete the ChatGPT thread in Phase 5** — same hygiene rule as the WP skill (one delete per batch).
14. **Use `attach_image_to_chatgpt.py` for ChatGPT file attachment** — never plain `openclaw browser upload`. ChatGPT's React handler ignores upload-armed file choosers; the helper does the React-aware DataTransfer dance.
15. **Always send via JS `data-testid="send-button"` click**, not the snapshot ref. The ref click frequently no-ops on the composer because the React onClick isn't bound to the OS click event.
16. **Overlay the logo on `image-1-full.png`, not on the JPEG.** The PNG is the actual ChatGPT output at native resolution; the JPEG is a downscaled re-encode. Overlaying on the JPEG bakes in compression artifacts under the logo.
17. **Recompute the unique-file-id list from the DOM every post, never cache it.** When N posts share a ChatGPT thread, the page accumulates source + generated images for each prior post. A stale `PREV_FIDS` cache means `fetch_chatgpt_image.py` picks an old image; absolute count thresholds (`imgs.length >= 2`) silently break after post 1.
18. **Cap the rendered logo with `--max-width-pct` (default 0.15).** ChatGPT sometimes draws a placeholder taking 30%+ of image width. Filling it with logo produces a billboard. The cap keeps the brand mark proportional even when the placeholder isn't.
19. **Background-spawn the wait loop, don't preheat with `sleep`.** Bash blocks `sleep N && until ...`. Use `run_in_background: true` and let the harness notify on completion.

---

## Error recovery

| Symptom | Action |
|---|---|
| FB redirects to /login | STOP. Notify user to log in to Facebook manually in Brave. |
| ChatGPT login page | STOP. Notify user. |
| `scrape_fb_post.py` returns `caption_len < 40` | Page likely showed a placeholder/short preview. Try waiting another 5s and re-scraping; if still short, flag `INCOMPLETE`. |
| `scrape_fb_post.py` returns `image_count: 0` | Maybe a video-only post. Skip and flag. |
| `attach_image_to_chatgpt.py` ends with `OK assigned 1 file(s)` but `form_imgs === 0` | Likely the React change handler didn't fire on the first send. Re-run the helper once. If still 0, check for the "already uploaded" dialog (see next row). |
| Dialog `"You've already uploaded this file. Try uploading something new."` after attach | ChatGPT dedups by **content hash across sessions**, not by filename. Renaming the file does NOT help. Re-encode the JPEG with `sips -s format jpeg -s formatOptions 92 <src> --out <new>` to break the hash, dismiss the dialog, then re-attach the re-encoded file. |
| Composer shows 2+ attachments after a single attach | A prior retry left a duplicate. Remove all but one via JS: find small (~20px) `<button>` with `<svg>` inside the composer form and click the last one until `form.querySelectorAll("img").length === 1`. |
| Clicking the snapshot ref for "Send prompt" doesn't actually send | Common — the ref click bypasses React. Use the JS pattern in Phase 3 step 5 (`document.querySelector('button[data-testid="send-button"]').click()`). Verify by checking that `location.href` transitions to `/c/<uuid>`. |
| `until ... done` exits immediately when generation hasn't started | The stop-button disappears briefly between phases. Use the stronger wait condition in Phase 3 step 6 (require both `!stop && img[src*="file_"].length >= 2`). |
| `fetch_chatgpt_image.py` picks the attached SOURCE image instead of the generation | The source is also `file_`-prefixed and ≥ 2048px so it passes the filter. Always pass `--skip-ids <source_file_id>` — see Phase 3 step 8 for how to grab the source's file_id from the composer. |
| `overlay_logo_on_clone.py` exits with `PLACEHOLDER_NOT_FOUND` | Only happens with `--fallback-corner none`. With the default `top-left` fallback, the script corner-stamps the logo instead — no action needed for most workflows. If you do need a placeholder, re-prompt: "Vẽ thêm một khung dạng nét đứt ở góc trên bên trái, kích thước khoảng 200×100 px, để dán logo sau." |
| Overlay output shows `placeholder=FALLBACK` instead of measured coords | ChatGPT didn't draw a dashed rectangle this time. The logo was corner-stamped at `--max-width-pct` size. Acceptable in most cases; re-prompt only if you need the placeholder framing. |
| Logo looks **too big** dominating the design | The ChatGPT-drawn placeholder was oversized. Re-run overlay with `--max-width-pct 0.12` (or lower) to cap the logo regardless of placeholder size. |
| Logo looks **too small** inside a large empty dashed box | Detection missed the actual placeholder and fell back to corner. Check `--debug` output: if it says `placeholder=FALLBACK` but you can see a placeholder in the image, the dash color is outside the detector's blue-dominance range — file a bug with the image so the color filter can be widened. |
| Logo landed on top of a section header (e.g. "1. Triệu chứng" pill) | Stale detector — pull the latest skill version. The current detector rejects candidates whose bottom edge sits below 15% of image height, which fixes this. |
| ChatGPT REFUSED on image | Retry with safer concept (no people, no medical photos). Pivots listed in WP skill. |
| ChatGPT picks wrong image on download | Pass `--skip-ids <prev_file_ids>` to `fetch_chatgpt_image.py`, or `--pick N` to select specific image. |
| Gateway timeout | Bump `OPENCLAW_TIMEOUT=120000`. If repeated, restart gateway only (not `browser stop` — that logs out FB + ChatGPT). |
| Caption rewrite response malformed (missing `---POST N---` markers) | Re-prompt ChatGPT with "Bạn quên định dạng — hãy gửi lại đúng định dạng `---POST N---`." Re-extract. |

---

## What NOT to do

- **Don't repost the source image verbatim.** The whole point is restyling — if the user wants raw mirroring, use `facebook-share-to-groups` instead.
- **Don't bash for-loop over URLs.** One tool call per URL.
- **Don't run `openclaw browser stop` mid-flow** — it logs out FB + ChatGPT.
- **Don't `type` Vietnamese.** Use `fill --fields`.
- **Don't try to auto-post to a group from this skill** — the user explicitly chose manual upload. If they ask later, hand off to `facebook-post-to-groups`.
- **Don't write the caption/prompts via bash heredoc** — Vietnamese diacritics get mangled. Always Write tool.
- **Don't loosen the `file_` + naturalWidth ≥ 1000 image filter** — you'll grab the ChatGPT avatar icon instead of the generation.
- **Don't skip the ChatGPT thread deletion** in Phase 5 — sidebar pollution adds up fast.

---

## Future hooks (not implemented yet)

- Auto-post to a chosen FB group via the `facebook-post-to-groups` skill (set `POST_AFTER_GENERATION=true`).
- Add per-post WP cross-publish (using `wordpress-create-post-from-source`).
- Caption A/B variants (ask ChatGPT for 2 versions per post and let user pick).
