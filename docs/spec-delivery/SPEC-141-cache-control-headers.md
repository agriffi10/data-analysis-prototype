# Completed Spec — SPEC-141: Cache-Control for the SPA Shell and Hashed Assets

## What was completed?

- `deploy-app.yml`'s single `aws s3 sync --delete` became **three prefix-scoped passes**: hashed
  assets (`public, max-age=31536000, immutable`), then the shell and root files (`no-cache`), then a
  repeat of the assets pass carrying the one `--delete`.
- `apps/portal/public/icons.svg` deleted — referenced by nothing in `src/`, `index.html` or CSS.
- No Terraform, no IAM, no CloudFront change. One PR: #339.

The bug was **browser** cache, not CDN. The original framing (a deploy invisible for 24h via
CloudFront's default TTL) was wrong: `deploy-app.yml` already invalidates `/*`. With no
`Cache-Control` anywhere, browsers applied heuristic freshness to `index.html`; combined with
`--delete` removing the superseded bundles, a returning browser requested a chunk that no longer
existed — **a white screen, not stale content**.

### The pass shape, and why it is this shape

- **Scoped by prefix, not by `--exclude`.** `--exclude` filters the **destination** side of
  `--delete` too, so an excluded file looks *absent* and gets deleted from the bucket. A pass
  carrying both `--delete` and `--exclude 'assets/*'` would delete `index.html` while leaving every
  stale chunk in place.
- **No file is uploaded by two passes.** `sync` compares size and mtime, and a fresh CI checkout
  makes every local mtime newer than the bucket's — so a second pass over the same files *would*
  re-upload them with that pass's `--cache-control`, silently overwriting the immutable header. The
  first deploy's log confirms the mechanism: pass 1 re-uploaded all 108 assets even though the build
  was byte-identical to the previous one.
- **Order:** assets up before the shell (a new shell never points at a chunk that isn't there yet),
  deletions last, invalidation after all three.
- Pass 3 is byte-for-byte pass 1 plus `--delete`, so if it ever does re-upload a file the header it
  writes is the one that file should have had anyway. It uploaded 0 files on the first run, as
  designed.

### Deliberate deviations

- **The orphan class this tolerates: stale root-level objects.** Because `--exclude` filters
  `--delete`'s destination side, one pass cannot both be scoped and reconcile the whole bucket, and
  the spec requires exactly one `--delete`. Scoping it to `assets/` means a root file we stop
  shipping is never removed. That is the safe half of the trade — the other shape leaves stale
  *chunks*, which is the white-screen bug itself. Named at the call site in `deploy-app.yml`.
- **`icons.svg`'s bucket copy is now exactly that orphan.** It still serves 200 with no
  `Cache-Control`. Remove it once, by hand:

  ```
  aws s3 rm s3://<static-bucket>/icons.svg
  ```

- **FR-004's superseded-chunk race is documented, not fixed.** A tab already open that triggers a
  lazy import after pass 3 removed the old chunk still 404s inside a `Suspense` boundary; `/query`
  (Monaco, SPEC-035) is the real case. FR-002 shrinks the window — once the shell revalidates, a
  reload recovers — but does not close it for an open tab. The fix is retaining superseded bundles
  behind an S3 lifecycle rule, which needs object lifecycle management and a retention policy.
  Recorded as a comment beside the `--delete` pass.

## What changed from earlier specs?

Nothing prior was edited. SPEC-140's response-headers policy is untouched and carries no
`Cache-Control` of its own, so the browser-facing header comes from the origin object as intended.

## Verification

Verified against the deployed site after the merge deploy (run 30896227214), by `curl -I`:

| Request | `cache-control` |
|---|---|
| `/` | `no-cache` |
| `/files` (deep link via `custom_error_response`) | `no-cache` |
| `/favicon.svg` | `no-cache` |
| `/assets/index-<hash>.js`, `.css` | `public, max-age=31536000, immutable` |
| `/assets/QueryPage-<hash>.js` (route chunk) | same |
| `/assets/SqlEditor-*.js`, `editor-*.css`, `editor.api-*.js` (Monaco, lazy) | same |
| `/assets/codicon-<hash>.ttf` | same |

`If-None-Match` against the shell's ETag returns **304**, so the header forces revalidation rather
than merely disabling caching. Nothing outside `/assets/` carries `immutable`.

The `.ttf` is the point of FR-001's "prefix, never an extension list" — `dist/assets/` holds 108
files and an extension rule would have missed the font.

FR-003 is proven by the deploy log rather than inferred: pass 1 uploaded **108** files (all of
`dist/assets/`), pass 2 uploaded exactly **2** (`index.html`, `favicon.svg`), pass 3 uploaded and
deleted **0**. Every file in `dist/` is in the bucket, and no pass deleted anything it should not
have. The site loads with a clean console.

**Not covered:** the `--delete` pass's deletion behaviour was not exercised — this build was
byte-identical to the previous one, so there was nothing stale to remove. The next deploy that
changes a bundle hash is the first real test of it. Signed-in `/query` was not re-checked here;
SPEC-140 already exercised it and this change touches no application code.
