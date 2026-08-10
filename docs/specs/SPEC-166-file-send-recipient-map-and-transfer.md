# Spec: Send Files — Recipient Guard, Distributed-Map Transfer & Terminal States

**ID:** SPEC-166
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-165 (copy plan + destination layout), SPEC-160 (`cpcommon.transfer` — manifest, batch copy, result attribution), SPEC-164 (validated recipients), SPEC-091 (the conflict-guard precedent)

## Overview

Everything up to here decides *what* moves; this spec moves it. The shape is the one SPEC-160
established for table share, reused rather than re-derived: a fast inline `Map` guards each
recipient's destination, a manifest of `(recipient × object)` items is written to the admin bucket,
a **top-level Distributed Map** copies them in bounded parallel batches, and a collector attributes
failures back to individual recipients. One recipient's conflict or copy failure never touches
another's.

This is the spec that makes the feature real: after it, a send that reaches the plane actually
delivers files. It is still silent — the user hears nothing until SPEC-167.

## Scope

### In Scope

- **check-target-absent** per recipient, in an inline `Map` with a per-item `Catch`: a non-empty
  destination prefix is a per-recipient `conflict`, never an overwrite.
- **build-transfer-manifest** over the copy plan × accepted recipients, through
  `cpcommon.transfer.manifest`.
- The **Distributed Map** transfer state, configured exactly as SPEC-160's — JSONL reader,
  `ItemBatcher`, `DISTRIBUTED`/`STANDARD` processor, bounded `MaxConcurrency`,
  `ToleratedFailurePercentage: 100`, `ResultWriter` to the admin bucket.
- **collect-transfer-results**: per-recipient attribution from the exported `FAILED_n.json`.
- **Terminal states**: a per-recipient outcome list (`ok` / `conflict` / `unknown_user` /
  `unknown_space` / `copy_failed`) and the whole-request terminal, in the shape SPEC-167's
  notifications consume.
- Execution-role IAM: read the source in both data buckets, write **only** under
  `*/shared_files/*` in both, plus the Distributed Map's own `states:` and `ResultWriter` grants.
- A machine `TimeoutSeconds`, and admin-bucket lifecycle expiry for `file-send/` artifacts.

### Out of Scope

- Notifications and UI — SPEC-167.
- Re-implementing the transfer engine. If something is missing from `cpcommon.transfer`, it is added
  **there** and table share gets it too; a forked copy in `fscommon` is a spec failure.
- Rolling back a partial delivery. Copied objects stay; the recipient is told what arrived.
- Resuming or redriving a failed Map Run.
- Merging into an existing destination. A non-empty target is a conflict, full stop.

---

## Functional Requirements

### FR-001: The conflict guard

#### Description:

No send ever overwrites anything.

#### Acceptance Criteria:

- [ ] For each recipient, a **non-empty** `{targetRoot}shared_files/{sender}/` destination for any
      selected item name is a `conflict` for that recipient — no object is copied for it.
- [ ] The guard is per **item name**, so a second send of `notes.txt` conflicts while a first send of
      `reports/` to the same recipient would not have.
- [ ] Recipients annotated invalid upstream (`unknown_user`, `unknown_space`) short-circuit here to
      their terminal reason without any S3 call.
- [ ] The inline `Map` keeps a per-item `Catch`; one recipient's failure never aborts a sibling.
- [ ] A conflict names the colliding item in the recorded reason, so SPEC-167 can tell the sender
      *which* file already existed.

### FR-002: Manifest and transfer

#### Acceptance Criteria:

- [ ] `build-transfer-manifest` writes JSONL to
      `{admin_bucket}/file-send/{requestId}/transfer-manifest.jsonl`, one line per
      `(accepted recipient × planned object)`, each carrying the destination computed by
      `fscommon.paths.destination_key` — the manifest builder does not build keys itself.
- [ ] Rejected recipients contribute **zero** lines.
- [ ] The Distributed Map is declared at the **top level** — a test asserts the rendered ASL nests no
      Distributed Map inside another `Map`.
- [ ] Its reader, batcher, processor mode, concurrency bound, tolerated-failure setting and
      `ResultWriter` match SPEC-160's constants, taken from `cpcommon.transfer.config` rather than
      re-declared.
- [ ] With `itemCount: 0` the Map is skipped by a `Choice` guarded with **`IsPresent` before the
      numeric test** — a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default`
      does not cover it.
- [ ] Objects above 5 GiB still transfer (the batch copier's multipart path); no object data passes
      through a Lambda.

### FR-003: Attribution and terminal states

#### Acceptance Criteria:

- [ ] `collect-transfer-results` reads the Map Run's `manifest.json` → `FAILED_n.json` (and
      `PENDING_n.json` when present) and marks a recipient `copy_failed` if **any** of its items
      failed, `ok` only if none did.
- [ ] Earlier terminals (`conflict`, `unknown_*`) are never overwritten by attribution.
- [ ] The whole-request terminal reports every recipient exactly once, with counts — never a list of
      failed keys (bounding the state, matching `bounded_detail`).
- [ ] An unreadable or absent results manifest is a **whole-request** failure with a clear reason,
      not a silent success.
- [ ] A request where every recipient conflicts reaches the terminal with no child execution started.

### FR-004: Execution-role IAM

#### Acceptance Criteria:

- [ ] `s3:GetObject` on both data buckets for the source read; `s3:PutObject`,
      `s3:AbortMultipartUpload` and `s3:ListMultipartUploadParts` scoped to `*/shared_files/*` in
      both — the role can write **nowhere else** in a user's prefix.
- [ ] An explicit `s3:DeleteObject` **Deny** on both data buckets and the admin bucket: this plane
      never deletes anything, and the Deny makes that structural rather than behavioural.
- [ ] `states:StartExecution` on this machine, `states:DescribeExecution`/`StopExecution` on its
      executions, manifest `GetObject`, and the `ResultWriter` object actions on
      `{admin_bucket}/file-send/*`.
- [ ] No new `Resource: "*"`; the SPEC-139 plan scan's IAM findings do not grow.
- [ ] The grants are verified by **policy simulation against the deployed role** — each expected
      allow paired with an expected deny, and each `implicitDeny` paired with an `allowed` control,
      because an `implicitDeny` alone cannot distinguish an ungranted action from a wrong ARN
      (SPEC-149/157's lesson).

### FR-005: Bounded runs and artifact expiry

#### Acceptance Criteria:

- [ ] The state machine declares a **top-level** `TimeoutSeconds`; a run that exceeds it fails with
      `States.Timeout` and reaches `NotifyFailure`.
- [ ] An admin-bucket lifecycle rule expires objects under `file-send/`, prefix-scoped so `logs/`,
      `locks/` and `table-share/` are demonstrably unaffected.
- [ ] The retention period exceeds `TimeoutSeconds` by a stated margin, so no live run's manifest
      expires underneath it.

---

## Data Model

```python
# One manifest line
{ "recipient": "bob", "kind": "user",
  "srcBucket": "dat-prod-user-space", "srcKey": "alice/reports/2026/q1.csv",
  "destBucket": "dat-prod-user-space", "destKey": "bob/shared_files/alice/reports/2026/q1.csv" }

# Terminal summary (input to SPEC-167's notifications)
{
  "requestId": "9f2c…",
  "sender": "alice",
  "itemNames": ["reports", "notes.txt"],
  "objectCount": 2413,
  "recipients": [
    { "kind": "user",  "name": "bob",     "status": "ok" },
    { "kind": "space", "name": "finance", "status": "failed",
      "reason": "conflict", "detail": "notes.txt" },
    { "kind": "user",  "name": "carol",   "status": "failed",
      "reason": "copy_failed", "failedItems": 7 }
  ]
}
```

## Implementation Phases

### Phase 1: The guard

- `check-target-absent` per recipient, the short-circuit for upstream-invalid recipients, the inline
  `Map` with its `Catch` and `ResultPath`.

### Phase 2: Manifest + Distributed Map

- `build-transfer-manifest` over `cpcommon.transfer`; the Map state, the `IsPresent`-guarded
  `Choice`, and the batch copier wiring.

### Phase 3: Attribution, terminals, IAM, bounds

- `collect-transfer-results`; the terminal summary shape; role grants + the policy simulation;
  `TimeoutSeconds` and the lifecycle rule.

### Phase 4: Verification

- Unit + ASL-shape tests (no nested Distributed Map, `NotifyFailure` present, empty-manifest path).
- **Live check (owed):** send a folder of several hundred objects plus one loose file to two
  recipients — one a user, one a shared space — where a third recipient already holds a colliding
  item name. Confirm: both good recipients receive every object at
  `shared_files/{sender}/…`, the third is `conflict` with the item named, nothing was overwritten,
  and `logs/service=file-send/` carries the run. **Nothing that runs offline proves the cross-bucket
  write actually lands** — the `*/shared_files/*` scoping is only demonstrated by a real copy.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, component-inventory rows, the `architecture.md` *Send Files* section
  filled in, a `decisions.md` entry for the conflict-not-overwrite rule and the shared transfer
  engine, and one Key Decisions line.
