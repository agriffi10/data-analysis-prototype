---
type: Decision
title: "The image is the file set, which retires a reconciliation pass and an orphan class (SPEC-194)"
description: "**The image IS the file set** — no reconciliation pass, no orphan class, an honest 404 under `/assets/`. The S3 path it replaced deployed in three prefix-scoped passes, and its one finding that outlives it: **`--exclude` PROTECTS keys from `--delete`**, so a pass excluding a prefix can never reconcile it."
---

The S3 delivery path needs three prefix-scoped sync passes because one pass cannot both write a single `--cache-control` and reconcile deletions, and its single `--delete` is scoped to `assets/` — leaving an accepted orphan class of stale **root-level** objects removable only by hand. **A container has neither problem.** The image *is* the file set: nothing to reconcile, no key surviving a build, no pass ordering. Both the `--delete` pass and the orphan class cease to exist for that path — a settled decision retired by shipping rather than by argument.

**One improvement, and one residual that changes shape for the worse.** Under `/assets/` the container answers an **honest 404** for a missing hashed chunk, where the distribution returned `index.html` as `text/html` to a `<script type="module">` request — which failed the MIME check anyway, more confusingly, and with no way to tell "removed" from "never existed". At the root the 200-with-`text/html` trap is **preserved deliberately and pinned by a test**, so a later change to the fallback is visible rather than silent; it remains the reason a removal is never verifiable by status code here. The residual: on the S3 origin the bucket held the union of old and new until the delete pass ran, so an open tab lazy-importing a removed chunk had a window. A task serves exactly one image's file set, so during a rolling deployment a browser holding the **old** shell routed to a **new** task 404s immediately and deterministically. The `no-cache` shell means a reload recovers, as before. Accepted, and recorded so it is not rediscovered as a container defect.

## History

### 2026-08-27

- **Settled:** SPEC-194.
