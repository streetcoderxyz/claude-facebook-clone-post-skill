# facebook-clone-post

Clones Facebook posts by scraping caption + image, then regenerating both via ChatGPT (caption rewritten in Vietnamese, image redrawn using the source as style reference). Saves locally for manual upload.

See `SKILL.md` for the full workflow.

## Quick example

```
/facebook-clone-post https://www.facebook.com/ydgr.net/posts/pfbid0KGTKi5JF...,https://www.facebook.com/ydgr.net/posts/pfbid0AbcD...
```

Output → `/tmp/fb-clone/<timestamp>/post-{1,2}/{source,new}-{caption.txt,image.jpg}`.

## Inputs

- `SOURCE_URLS` (required) — comma-separated FB post URLs
- `STYLE_HINT` (optional, defaults to ydgr.net infographic look)
- `HIDE_PRODUCT_LABELS` (optional, default `true` — white dots over brand labels)
- `CAPTION_TONE` (optional)

## Prereqs

- Brave logged in to Facebook + ChatGPT
- `openclaw browser status` → running

## Related skills

- `facebook-share-to-groups` — share existing posts as-is (no regeneration)
- `facebook-post-to-groups` — post original content to groups
- `wordpress-generate-missing-images` — sibling skill, source of shared helper scripts
