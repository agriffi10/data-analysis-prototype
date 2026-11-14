---
type: Decision
title: "The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)"
description: "**The image IS the file set** — no reconciliation pass, no orphan class, and an honest 404 under `/_next/`, which the Next.js server gives only through its `%5Fnext` route, because the optional catch-all answers any unmatched path 200 with the shell. The S3 path it replaced deployed in three prefix-scoped passes, and its one finding that outlives it: **`--exclude` PROTECTS keys from `--delete`**, so a pass excluding a prefix can never reconcile it."
---

The S3 delivery path needed three prefix-scoped sync passes, because one pass cannot both write a single `--cache-control` and reconcile deletions, and its single `--delete` was scoped to the hashed-asset prefix, leaving an accepted orphan class of stale **root-level** objects removable only by hand. **A container has neither problem.** The image *is* the file set: nothing to reconcile, no key surviving a build, no pass ordering. Both the `--delete` pass and the orphan class cease to exist, a settled decision retired by shipping rather than by argument.

**One improvement, and one residual that changes shape for the worse.** Under `/_next/` the server answers an **honest 404** for a missing hashed chunk, where the distribution returned `index.html` as `text/html` to a module-script request, which failed the MIME check anyway, more confusingly, and with no way to tell "removed" from "never existed". On the Next.js server that 404 is not free: the optional catch-all would answer the missing chunk with the app shell under a 200, so `src/app/%5Fnext/[...rest]/route.ts` answers any `/_next/` path that matched no built file with a plain-text 404, and the image's behaviour matrix asserts it. At the root the 200-with-`text/html` trap is **preserved deliberately and pinned by the matrix**, so a later change to the fallback is visible rather than silent; it remains the reason a removal is never verifiable by status code here. The residual: on the S3 origin the bucket held the union of old and new until the delete pass ran, so an open tab lazy-importing a removed chunk had a window. A task serves exactly one image's file set, so during a rolling deployment a browser holding the **old** shell routed to a **new** task 404s immediately and deterministically. The `no-store` shell means a reload recovers, as before. Accepted, and recorded so it is not rediscovered as a container defect.

## History

### 2026-11-13

- **Changed:** SPEC-255 moved the image from nginx to the Next.js server. The hashed assets now live under `/_next/`, and the honest 404 there comes from a route handler, because the optional catch-all answers every unmatched path 200 with the shell. The root-level 200 trap is the catch-all's now, still pinned.

### 2026-08-27

- **Settled:** SPEC-194.
