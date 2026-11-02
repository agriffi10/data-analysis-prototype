---
type: Decision
title: "Data-quality runs index + dashboard (SPEC-123)"
description: "The `/data-quality` list reads a per-space `index.json`, never a listing of reports: capped at 200, appended under ETag CAS, completed checks only, and every index failure is logged and swallowed."
---

The `/data-quality` list is backed by a per-space **`index.json`**, not by listing the reports prefix — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives NO chronology, and building rows from the reports themselves costs one GET per row and gets slower the more the feature is used. `assemble-report` appends one small entry (the row's fields and nothing else) under **optimistic ETag CAS** with bounded retry, because checks of DIFFERENT locations run in parallel (the queue serializes only same-location checks **— superseded 2026-09-15: it only starts them in order, so same-location checks run at once too, which the CAS already covers; [the group id entry](../control-planes/a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on.md) —**) — the same lost-update fix SPEC-082 applied to the registry. It was duplicated in `dqcommon` because `casio` sat in a layer the data-quality functions don't attach (**SPEC-125 did NOT merge it** — it folded the shared *client/config/JWT/notify* surface onto `cpcommon` and deliberately left the CAS retry loop domain-side).

> **Superseded (SPEC-156 FR-001, 2026-08-07) — the duplication ONLY.** The loop and the 409 predicate live in `cpcommon.cas`, which every data-quality verb already attaches; `DQ_INDEX_CAS_RETRIES` is gone and the cap is one value (6) for all callers. The twin had drifted before anyone merged it, which is this paragraph's real lesson. Everything below is unchanged and still live.

The index is **capped at 200, oldest dropped first**, and every failure is **logged and swallowed**: the report is the artefact, the index is a convenience, so write order is report → notification → index, most durable to least. The page **aggregates across spaces** (this is "my checks", not "checks in one folder") and one unreadable space is skipped rather than blanking it. It lists **completed checks only**, and the footer line saying failures live in notifications was worded **"usually"** until **SPEC-126** closed the never-started-an-execution hole, then **"always"**; it now carries **no adverb**, the Help guide likewise, because `States.Runtime` and `States.DataLimitExceeded` escape every Catch in the machine and never reach `NotifyFailure` — designed out, not impossible. No new IAM. Detail: `spec-delivery/SPEC-123`.

> **Superseded (2026-09-26) — the row's qualifier ONLY.** The entry carries **`hasIncompleteFigures`**, not `hasApproximateFigures`, and the row's tag reads **`Partly checked`** — also in the link's accessible name, which replaces the tag's text for a screen reader. `hasApproximateFigures` is true on every report, so the old `Sampled` chip sat on every row, told the user nothing, and was false on any check whose bytes were all scanned — every JSON and Parquet check, and any CSV check whose encoding scan read every byte. The incomplete flag is the one the report banner warns on, so the list and the report now agree for every entry written after the change. It still tags every JSON and Parquet row, because the ragged figure is skipped for both and a skip counts as incomplete (SPEC-112's classification, unchanged). An entry written before the change lacks the flag and **reads as partly checked** — fail-safe, since guessing complete would put an unqualified Clean on a run nobody can vouch for; its report may then open on a plain "No issues found", a disagreement that ages out with the 200-entry cap. Everything above is unchanged and still live.

## History

### 2026-09-26

- **Changed:** The row carries `hasIncompleteFigures` and reads `Partly checked`, replacing the always-true `Sampled` qualifier.

### 2026-09-15

- **Changed:** The group id only starts same-location checks in order, so they can run at once; the CAS already covers that.

### 2026-08-07

- **Changed:** The duplicated CAS loop moved to `cpcommon.cas`, with one retry cap for all callers.

### 2026-07-21

- **Settled:** SPEC-123.
