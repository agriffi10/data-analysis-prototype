---
type: Decision
title: "Static-asset caching = three prefix-scoped sync passes (SPEC-141)"
description: "The three S3 sync passes no longer run because the image is the file set. Two findings stand: `--exclude` protects destination keys from `--delete`, and when some users see a broken app after a deploy, reach for the origin's headers, not an invalidation."
---

> **RETIRED by SPEC-202 (2026-09-02).** Nothing below runs any more: `deploy-app.yml`, the three
> sync passes, the `/*` invalidation and the static bucket are all deleted, and the image IS the
> file set — no reconciliation, no orphan class, and an honest 404 under `/assets/` instead of a
> stale chunk. The entry stays because two of its findings outlived their mechanism and are the
> reason it is worth reading: **`--exclude` PROTECTS destination keys from `--delete`** (so a pass
> excluding a prefix can never reconcile it — read against the CLI's own `dst_patterns`, after this
> repo stated it backwards in three places at once), and **the bug was the browser cache, not the
> CDN** (reach for the origin object's headers, not an invalidation, when some users see a broken
> app after a deploy). *(Its predecessor marker, SPEC-194's, said the two paths would "retire
> outright with the distribution" — this is that.)*


`deploy-app.yml` uploads `dist/` in **three passes**: hashed assets under `assets/` as `public, max-age=31536000, immutable`, then the shell and root files as `no-cache`, then a repeat of the assets pass carrying the **one** `--delete`. Four things make that shape non-negotiable. **(1) The bug was the BROWSER cache, not the CDN.** The deploy already invalidates `/*`, so CloudFront never served a stale shell; with no `Cache-Control` anywhere, browsers applied **heuristic freshness** to `index.html`, and `--delete` had already removed the hashed bundle that shell referenced — **a white screen, not stale content**, on exactly the users whose cache was warm, and unreproducible with devtools caching disabled. Reach for the origin object's headers, not an invalidation, when the symptom is "some users see a broken app after a deploy." **(2) `--exclude` PROTECTS destination keys from `--delete` — it does not endanger them.** The CLI filters the reverse (destination) generator with the same patterns re-rooted at the destination (`awscli/customizations/s3/filters.py` builds `dst_patterns` beside `patterns`; `subcommands.py` gives `rev_generator` its own filter), so an excluded object is never a deletion candidate. The consequence: **a pass that excludes a prefix can never reconcile it** — `--delete --exclude 'assets/*'` keeps every stale chunk forever. Scope passes by **prefix** (`dist/assets/` → `s3://…/assets/`) so each owns a disjoint key set. (*Corrected 2026-08-04 by the SPEC-141 review, which read the CLI source: the original entry, the workflow comment, and SPEC-141:108-109 itself all stated this backwards — claiming an excluded `index.html` would be deleted. The implementation was never affected; only the reason was wrong.*) **(3) No file may be uploaded by two passes.** `sync` compares size and mtime, and a fresh CI checkout makes every local mtime newer than the bucket's — the first deploy re-uploaded all 108 assets on a byte-identical build, confirming a second pass over the same files would overwrite the immutable header with that pass's `--cache-control`. **(4) Deletions therefore live on their own pass, and the surviving orphan class is a SPEC CHOICE rather than a CLI constraint.** `--delete` scoped to `assets/` leaves stale **root-level** objects behind (harmless, unreferenced, removable by hand). Adding `--delete` to the shell pass **would** reconcile those — `--exclude` protects every asset key from that same deletion (verified against the CLI's `dst_patterns`), and the assets pass still reconciles chunks, so nothing would be retained. What forbids it is SPEC-141's AC "exactly one sync pass carries `--delete`", **written on the same mistaken reading of `--exclude` corrected in (2)**. Revisit the AC deliberately if the manual cleanup becomes annoying; the cost to weigh is that a root-scoped `--delete` removes anything in the bucket not produced by `dist/` (nothing else writes it today). `icons.svg` is the first such orphan. The residual race is **accepted and documented**: a tab already open that lazy-imports after the delete pass still 404s inside `Suspense` — **both** lazy routes are exposed, `/query` (which loads Monaco beneath it) and `/connections`, so a fix must not be scoped to Monaco; closing it needs retained bundles behind an S3 lifecycle rule. Rule of thumb for the whole area: **a content-hashed URL is immutable, a stable URL must revalidate**, and prefer a path prefix over an extension list — `dist/assets/` carries a `.ttf` that a js/css rule would miss. Full account: `docs/spec-delivery/SPEC-141-cache-control-headers.md`.

## History

### 2026-09-02

- **Changed:** SPEC-202 retired the sync passes, the `/*` invalidation, `deploy-app.yml` and the static bucket.

### 2026-08-04

- **Settled:** SPEC-141.
- **Changed:** The SPEC-141 review corrected the reading of `--exclude`, which had been stated backwards: it protects destination keys from `--delete`.
