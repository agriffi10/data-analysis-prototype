# Spec: Cache-Control for the SPA Shell and Hashed Assets

**ID:** SPEC-141
**Status:** Completed
**Last Updated:** 2026-08-03
**Depends On:** SPEC-140 (response headers policy — shares `cloudfront.tf` and the deploy path)

## Overview

Nothing the portal serves carries a `Cache-Control` header — not the SPA shell, not the hashed
asset bundles. Browsers therefore fall back to **heuristic freshness**, caching `index.html` for a
duration derived from its `Last-Modified` date, with no instruction from us either way.

That is not merely untidy. The deploy syncs with `--delete`, so old hashed bundles are removed the
moment a new build lands. A returning browser holding a heuristically-cached `index.html` requests
`/assets/index-<oldhash>.js`, which no longer exists, and gets a 404 — **a white screen, not stale
content**, until the user knows to hard-refresh. The failure is silent, affects exactly the users
who visited recently enough to have a warm cache, and cannot be reproduced by anyone testing with
devtools open and caching disabled.

This spec gives every response an explicit caching instruction: hashed assets become permanently
cacheable, and the shell becomes revalidate-always.

**Correction to the premise this work was raised under.** The original framing was that a deploy
could stay invisible for up to 24h via CloudFront's default TTL. That is **wrong** —
`deploy-app.yml:63` already invalidates `/*` on every deploy, so the CDN never serves a stale shell.
The bug is entirely in the **browser** cache, which invalidation cannot reach. Same symptom class,
different mechanism, and a much narrower fix.

## Scope

### In Scope

- `Cache-Control` set at **upload time** in `.github/workflows/deploy-app.yml`, per file class.
- `/assets/*` (content-hashed by Vite) → immutable, one year. The rule must be a **path prefix**,
  never an extension list: `dist/assets/` currently holds ~108 files including a font
  (`codicon-*.ttf`, from Monaco) that a js/css rule would miss.
- `index.html`, `favicon.svg`, `icons.svg` → revalidate on every use. (`icons.svg` is referenced by
  **nothing** — no source file or `index.html` mention. Verify, and prefer deleting it from
  `public/` over headering a dead file; if kept, it gets the shell's header.)
- Preserving `--delete` semantics safely across a multi-pass sync.
- Verifying the SPA-fallback path (`custom_error_response` → `/index.html`) carries the shell's
  header and not an asset's.

### Out of Scope

- **A second CloudFront cache behavior.** Considered and rejected: a behavior needs its own
  response headers policy, which would duplicate SPEC-140's entire security header set across two
  resources that can silently drift apart. The browser-facing `Cache-Control` comes from the origin
  object regardless, and `Managed-CachingOptimized` honours origin headers — so the second behavior
  would add a drift hazard while fixing nothing this spec is about.
- **Any Terraform or deploy-role IAM change.** Neither is required; this is a deploy-workflow change.
  If the build later needs a *custom* cache policy, `cloudfront:CreateCachePolicy` /
  `UpdateCachePolicy` / `DeleteCachePolicy` would have to be added first as their own apply
  (the role has only `GetCachePolicy` and `ListCachePolicies` today) — noted so a future spec does
  not trip the self-grant-timing trap.
- **Retaining superseded asset bundles.** See FR-004 — the residual race is documented and accepted,
  not fixed, because fixing it needs object lifecycle management and a retention policy.
- **Narrowing the `/*` invalidation.** With immutable assets, invalidating everything needlessly
  cold-starts the edge cache on each deploy. That is a performance refinement with no correctness
  content, and one invalidation path costs the same as many.
- The three ZAP Informational findings this touches (`Storable and Cacheable Content`,
  `Retrieved from Cache`, `Re-examine Cache-control Directives`). They may or may not clear; they are
  Informational and are **not** the reason for this work. No acceptance criterion depends on them.

---

## Functional Requirements

### FR-001: Hashed assets are immutable

#### Description

Everything under `/assets/` carries a content hash in its filename, so its bytes can never change
under a given URL. It should be cached as aggressively as the spec allows.

#### Acceptance Criteria

- [ ] `curl -sSI https://<domain>/assets/<file>.js` returns
      `cache-control: public, max-age=31536000, immutable`.
- [ ] The same holds for a CSS asset and for a lazily-loaded chunk (e.g. a Monaco worker), not only
      the entry bundle.
- [ ] No file outside `/assets/` receives this header.

### FR-002: The shell always revalidates

#### Description

`index.html` is the one file whose URL is stable while its contents change every deploy. It must
never be served from a browser cache without a revalidation round-trip.

#### Acceptance Criteria

- [ ] `curl -sSI https://<domain>/` returns `cache-control: no-cache` (or an equivalent that forces
      revalidation, e.g. `max-age=0, must-revalidate`).
- [ ] `favicon.svg` and `icons.svg` carry the same — they are **not** content-hashed, so an
      immutable header would pin a stale icon indefinitely.
- [ ] A deep link (`/files`), served as `index.html` via `custom_error_response`, carries the
      **shell's** header, not an asset's.
- [ ] A second request with `If-None-Match` returns `304`, confirming revalidation works rather than
      the header merely disabling caching outright.

### FR-003: The sync cannot delete the shell

#### Description

Splitting one `aws s3 sync` into per-class passes introduces a specific hazard around `--delete`,
which removes destination objects absent from the source.

> **Corrected 2026-08-04 (SPEC-141 review, from the CLI source).** This paragraph originally claimed
> that `--exclude` makes a file *look* absent, so a pass excluding `index.html` while carrying
> `--delete` would delete it. **That is backwards.** `--exclude` **protects** destination keys from
> `--delete`: the CLI filters the reverse (destination) generator with the same patterns re-rooted
> at the destination, so an excluded object is never a deletion candidate. The real constraint is
> the mirror image — **a pass that excludes a prefix can never reconcile it** — which is what forces
> exactly one orphan class to be accepted, and it is the reason the rest of this FR still stands.
> The implementation was never affected; only the stated reason was wrong.

Two further properties of `aws s3 sync` shape the design and must not be discovered mid-build.
**Ordering:** the `/*` invalidation runs only after all passes, so a delete pass that removes old
chunks before the new shell is uploaded widens the 404 window for in-flight users — upload assets
first, then the shell, and reconcile deletions last. **Skip detection:** `sync` compares size and
modification time, and a fresh build changes every file's mtime — so a second pass over
already-uploaded assets will **re-upload them with that pass's `--cache-control`**, silently
overwriting the immutable header. Pass scoping must guarantee no file is touched by two passes.
Because `--exclude`/`--include` also filter the *destination* side of `--delete`, one pass cannot
both be scoped and reconcile the whole bucket; the spec accepts whichever orphan class the chosen
shape leaves (stale root files or stale chunks) and the delivery doc names it.

#### Acceptance Criteria

- [ ] Exactly one sync pass carries `--delete`.
- [ ] The passes run in the stated order — assets before shell, deletions reconciled last — and no
      file is uploaded by more than one pass (the mtime re-upload trap above); verified by checking
      the headers on an asset **after** a full deploy, not after the assets pass alone.
- [ ] The orphan class the chosen pass shape tolerates is named in `deploy-app.yml`'s comment and
      the delivery doc.
- [ ] That pass's excludes are verified to protect, not endanger, the files they name — checked by
      running the deploy and confirming every file in `dist/` is present in the bucket afterwards.
- [ ] A deploy run end-to-end leaves the site loading: shell, assets and icons all resolve 200.

### FR-004: The superseded-chunk race is documented

#### Description

`--delete` plus lazy-loaded route chunks leaves a narrow window: a user with the SPA **already
open** who triggers a lazy import after a deploy has removed the old chunk gets a 404 inside a
`Suspense` boundary. `/query` lazy-loads Monaco, so this path is real.

FR-002 shrinks the window substantially — once the shell revalidates, a reload recovers — but it
does not close it for an already-open tab.

#### Acceptance Criteria

- [ ] The risk is recorded in the delivery doc and as a comment in `deploy-app.yml`, naming the
      lazy routes affected.
- [ ] The record states the fix (retain superseded bundles behind a lifecycle rule) and why it is
      not being done here, so the next reader inherits a decision rather than an oversight.

---

## Interface Contract

No application interface changes. The surface is the HTTP response:

```
GET /                     → cache-control: no-cache
GET /files                → cache-control: no-cache          (index.html via custom_error_response)
GET /favicon.svg          → cache-control: no-cache
GET /assets/index-<h>.js  → cache-control: public, max-age=31536000, immutable
GET /assets/<chunk>-<h>.js→ cache-control: public, max-age=31536000, immutable
```

## Environment Variables

None.

## File & Folder Structure

```
.github/
└── workflows/
    └── deploy-app.yml        # the only file this spec changes
docs/
└── spec-delivery/
    └── SPEC-141-cache-control-headers.md
```

## Implementation Phases

### Phase 1: Split the sync

- Replace the single `aws s3 sync --delete` with per-class passes setting `--cache-control`.
- Order them so exactly one pass owns `--delete` and it cannot remove the shell.
- Comment the `--delete`/`--exclude` interaction at the call site — it is the non-obvious hazard.

### Phase 2: Verify against the deployed site

- Confirm every header in the Interface Contract by `curl`, including the deep-link fallback.
- Confirm `If-None-Match` yields `304` on the shell.
- Confirm the site loads and `/query` mounts Monaco after a fresh deploy.

### Phase 3: Record

- Delivery doc, INDEX row, and the FR-004 note.
- Re-check the three ZAP Informational findings and record what actually happened to them, without
  treating either outcome as a pass/fail condition.
