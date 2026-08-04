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

- **Scoped by prefix, not by `--exclude`.** `--exclude` **protects** destination keys from
  `--delete`: the CLI filters the reverse (destination) generator with the same patterns re-rooted
  at the destination (`awscli/customizations/s3/filters.py` builds `dst_patterns` beside `patterns`;
  `subcommands.py` gives `rev_generator` its own filter), so an excluded object is never a deletion
  candidate. The consequence that shapes the passes: **a pass that excludes a prefix can never
  reconcile it**, so `--delete --exclude 'assets/*'` would keep every stale chunk forever. One pass
  therefore cannot both write a single `Cache-Control` value and reconcile the whole bucket, which
  is what forces exactly one orphan class to be accepted.
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

- **The orphan class this tolerates: stale root-level objects.** Scoping the one `--delete` to
  `assets/` means a root file we stop shipping is never removed. The alternative is real and was
  weighed: `sync dist/ s3://…/ --delete --exclude 'assets/*' --cache-control no-cache` reconciles
  root files while *protecting* every asset key. It is not taken because it retains every superseded
  bundle forever, and the spec puts retaining them **out of scope** — bounding that growth needs an
  S3 lifecycle rule and a retention policy. Adopt it only *with* that rule, never instead of it.
  Named at the call site in `deploy-app.yml`.
- **`icons.svg`'s bucket copy is now exactly that orphan.** It still serves 200 with no
  `Cache-Control`. Remove it once, by hand:

  ```
  aws s3 rm s3://<static-bucket>/icons.svg
  ```

- **FR-004's superseded-chunk race is documented, not fixed.** A tab already open that triggers a
  lazy import after pass 3 removed the old chunk still 404s inside a `Suspense` boundary. **Both**
  lazy routes are exposed — `/query` (`App.tsx:17`, which lazy-loads Monaco's `SqlEditor` beneath it,
  SPEC-035) and `/connections` (`App.tsx:20`) — so a future fix must not be scoped to Monaco.
  FR-002 shrinks the window (once the shell revalidates, a reload recovers) but does not close it
  for an open tab. The fix is retaining superseded bundles behind an S3 lifecycle rule, which needs
  object lifecycle management and a retention policy. Recorded as a comment beside the `--delete`
  pass.

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

**Found by the fresh-context review, after merge:** the `--exclude`/`--delete` mechanism was stated
**backwards** in four places (the workflow comment, this doc, the decision register, and the spec
itself, which was the origin). Corrected against the CLI source; the implementation was never
affected. A related gap the review also caught: a **missing `concurrency:` guard** on `Deploy App`.
Two merges in quick succession run two jobs in parallel, and job A's delete pass can remove job B's
freshly-uploaded chunks while B's `index.html` is already live — the same white screen this spec
fixes. Pre-existing in kind, but the three-step split moves the delete decision two steps further
from the upload and widens the window. **Not fixed here** — it is new scope, and `security.yml:20`
shows the house pattern (`concurrency:`) to follow.

**Not covered:** the `--delete` pass's deletion behaviour was not exercised — this build was
byte-identical to the previous one, so there was nothing stale to remove. The next deploy that
changes a bundle hash is the first real test of it. Signed-in `/query` was not re-checked here;
SPEC-140 already exercised it and this change touches no application code.
