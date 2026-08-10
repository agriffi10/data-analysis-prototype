# Spec: Table Share at Scale — Transfer Manifest & Distributed-Map Copy

**ID:** SPEC-160
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-090 (copy plan + cloned definition), SPEC-091 (recipient Map, `tscommon.copy`), SPEC-092 (create-table + terminal states), SPEC-152 (`NotifyFailure` on every plane), SPEC-156 (`cpcommon` owns the algorithm)

## Overview

Sharing a table today copies every object inside **one** `copy-objects` Lambda invocation per
recipient, bounded by that function's 900-second timeout — which is why `SHARE_MAX_OBJECTS` is 1000
and `SHARE_MAX_TOTAL_BYTES` is 20 GiB. Real tables break that: a user with several hundred Parquet
or CSV part files, or a table over 20 GiB, cannot be shared at all, and gets a "too large for v1"
refusal.

This spec replaces the copy stage with a **Step Functions Distributed Map** over a flat transfer
manifest in the admin bucket. Copying stops being one Lambda's problem and becomes a fan-out of
bounded child workflow executions, each copying a batch of objects through the *existing*
`tscommon.copy` code. The user-visible outcome is unchanged — the same push, the same per-recipient
conflict rules, the same notifications — but the ceiling moves from "what fits in 15 minutes" to
"what fits in the manifest".

The copy engine lands in **`cpcommon`**, not in `tscommon`: SPEC-164→167's file-send plane is the
second caller, and SPEC-156 already settled that the algorithm belongs to `cpcommon` while a domain
layer owns its wording.

## Scope

### In Scope

- A new **`build-transfer-manifest`** verb: given SPEC-090's copy plan and the recipients that
  passed `check-target-absent`, write a **JSON Lines** manifest of `(recipient × object)` transfer
  items to `{admin_bucket}/table-share/{hash}/transfer-manifest.jsonl`.
- A **top-level Distributed Map** state over that manifest — `ItemReader` `InputType: JSONL`,
  `ItemBatcher`, `ItemProcessor` in `DISTRIBUTED` mode with **`STANDARD`** child executions,
  bounded `MaxConcurrency`, `ToleratedFailurePercentage: 100`, and a `ResultWriter` exporting to
  `{admin_bucket}/table-share/{hash}/results/`.
- **`copy-objects` rewritten as a batch verb**: it receives a batch of transfer items and copies
  each with the existing `tscommon.copy` logic (server-side `CopyObject`, multipart `UploadPartCopy`
  above 5 GiB, bounded worker pool). It no longer resolves destinations or reads the copy plan.
- A new **`collect-transfer-results`** verb: read the Map Run's `manifest.json` → `FAILED_n.json`
  and attribute every failed item back to **its recipient**, so per-recipient isolation survives the
  restructure.
- **Machine restructure**: the existing inline recipient `Map` splits into a *guard* Map
  (`check-target-absent` only) before the transfer, and a *finish* Map (`create-table`) after it.
- The shared engine in **`cpcommon.transfer`** (manifest writer, batch copier, result reader), with
  `tscommon` keeping only the table-share wording and key layout.
- Execution-role IAM for the Distributed Map: `states:StartExecution` on the machine itself,
  `states:DescribeExecution`/`states:StopExecution` on its executions, manifest `GetObject`, and
  the `ResultWriter` object actions on the results prefix.

### Out of Scope

- **Raising or retiring the caps** — SPEC-161. This spec changes the *mechanism*; the existing
  `SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES` values stay in force so the change is provably
  behaviour-neutral before the ceiling moves.
- The inline `tableDefinition` and `SHARE_MAX_DEFINITION_BYTES` — SPEC-161.
- **S3 Batch Operations.** Evaluated and rejected: `TargetKeyPrefix` prepends to the *full source
  key*, so a Copy job cannot produce `bob/shared_tables/sales/year=2024/…` from
  `alice/tables/sales/year=2024/…`; it also caps objects at 5 GB, where today's path already handles
  more. Recorded as the deferred escape hatch since SPEC-090; this spec closes that deferral with a
  different mechanism and `architecture.md`'s *Deferred / Future Scope* line must be updated.
- Changing what a recipient receives — layout, cloned definition, conflict rules and notification
  wording are all unchanged.
- Retrying or redriving a failed Map Run. A failed item fails its recipient, exactly as a failed
  copy does today.

---

## Functional Requirements

### FR-001: The transfer manifest

#### Description:

A new `build-transfer-manifest` verb reads the SPEC-090 copy plan and the guard Map's output, and
writes one JSONL line per `(recipient, object)` pair to the admin bucket. Recipients the guard
rejected contribute no lines.

#### Acceptance Criteria:

- [ ] For N accepted recipients and M planned objects the manifest holds **N × M** lines, one JSON
      object per line, and the verb emits `{transferManifestKey, itemCount}`.
- [ ] Each line carries `recipient`, `kind`, `srcBucket`, `srcKey`, `destBucket`, `destKey`, and
      `destKey` equals `{recipient-base}/shared_tables/{tableName}/{relKey}` — byte-identical to the
      destination SPEC-091's `copy-objects` computes today.
- [ ] Recipients marked `conflict` / `unknown_target` by the guard Map contribute **zero** lines and
      are carried forward unchanged to the terminal summary.
- [ ] When **no** recipient was accepted the verb emits `itemCount: 0` and writes no manifest; the
      machine skips the Distributed Map (see FR-005) and no child execution starts.
- [ ] The manifest is written under the request's existing `{hash}` prefix, beside `copy-plan.json`.

### FR-002: The Distributed Map state

#### Description:

A top-level Distributed Map reads the manifest, batches items, and invokes `copy-objects` per batch.
It is **not** nested inside the recipient Map — the fan-out is over `(recipient × object)` pairs, so
one Map covers every recipient.

#### Acceptance Criteria:

- [ ] The state declares `ItemReader` with `Resource: arn:aws:states:::s3:getObject`,
      `ReaderConfig.InputType: JSONL`, and the bucket/key from `$.transferManifestKey`.
- [ ] `ItemProcessor.ProcessorConfig` is `{Mode: DISTRIBUTED, ExecutionType: STANDARD}`. **STANDARD,
      not EXPRESS**: a batch may contain a multi-GiB object whose multipart copy exceeds EXPRESS's
      5-minute ceiling, and EXPRESS's at-least-once semantics would re-run whole batches.
- [ ] `ItemBatcher.MaxItemsPerBatch` is a named constant sized so a batch's child input stays far
      below the 256 KiB execution-input limit, and so one batch completes inside `copy-objects`'
      timeout.
- [ ] `MaxConcurrency` is a named constant (bounded — **not** the 10,000 default), documented as
      protecting downstream Lambda concurrency and S3 request rates.
- [ ] `ToleratedFailurePercentage` is `100`, so an item failure never fails the Map Run and never
      aborts sibling items; attribution happens in FR-004.
- [ ] `ResultWriter` exports to `{admin_bucket}/table-share/{hash}/results/`, so the state's own
      output is the small `{MapRunArn, ResultWriterDetails}` shape rather than an array that would
      breach the 256 KiB state limit at scale.
- [ ] A test asserts the rendered ASL contains no Distributed Map nested inside another `Map` state.

### FR-003: `copy-objects` as a batch verb

#### Description:

`copy-objects` becomes a pure batch copier over transfer items. Destination resolution, plan
loading and per-recipient knowledge all move upstream.

#### Acceptance Criteria:

- [ ] Given a batch of items, every item is server-side-copied from `srcBucket/srcKey` to
      `destBucket/destKey`; objects > 5 GiB still use multipart `UploadPartCopy`; no object data
      passes through the Lambda.
- [ ] Copies within a batch run on the existing bounded worker pool; a transient/throttle-class
      error still raises `TransientError` so Step Functions retries the batch.
- [ ] A **deterministic** failure on one item does not abort the rest of its batch: the verb returns
      a per-item outcome list and the batch itself succeeds, so one bad key never costs a sibling's
      copy.
- [ ] The verb reads no copy plan, resolves no destinations, and imports nothing recipient-shaped —
      a test asserts it.
- [ ] Re-running an identical batch is harmless (copy is idempotent; the conflict guard has already
      run).

### FR-004: Per-recipient attribution

#### Description:

`collect-transfer-results` reads the Map Run's exported results and turns item-level failures back
into the per-recipient outcomes the rest of the machine already understands.

#### Acceptance Criteria:

- [ ] The verb reads `ResultWriterDetails` → `manifest.json` → every `FAILED_n.json` (and
      `PENDING_n.json` when present) from the results prefix.
- [ ] A recipient with **zero** failed items is `ok` and proceeds to `create-table`; a recipient
      with **one or more** failed items is `copy_failed` and does **not** get a table.
- [ ] Recipients carried through from the guard Map (`conflict`, `unknown_target`) keep their
      original reason — attribution never overwrites an earlier terminal.
- [ ] The emitted summary is the same per-recipient shape SPEC-092's terminal states and SPEC-094's
      notifications consume today; neither is changed by this spec.
- [ ] Failure counts are reported as **counts and recipient names**, never as a list of failed keys
      (bounding the state, matching `bounded_detail`'s discipline).
- [ ] An unreadable or absent results manifest is a **whole-request** failure with a clear reason,
      not a silent "everything succeeded".

### FR-005: Machine restructure and the empty path

#### Description:

The single recipient `Map` becomes: guard Map → build manifest → Distributed Map → collect results →
finish Map.

#### Acceptance Criteria:

- [ ] The guard Map runs `check-target-absent` **only**, keeps its per-item `Catch`, and one
      recipient's conflict never aborts siblings.
- [ ] The finish Map runs `create-table` only for recipients attributed `ok`.
- [ ] A `Choice` guards the Distributed Map on `itemCount > 0` using **`IsPresent` before the
      numeric test** — a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default`
      does not cover it (settled, #252-adjacent).
- [ ] A request where every recipient conflicts reaches the terminal summary with no child execution
      started and no `States.Runtime`.
- [ ] The machine still carries its `NotifyFailure` state before `Fail` on every failure path
      (SPEC-152); the fleet test still passes with the new states present.

### FR-006: Execution-role IAM

#### Description:

The table-share execution role gains exactly what the Distributed Map needs, scoped to this machine
and this prefix.

#### Acceptance Criteria:

- [ ] `states:StartExecution` is granted on the table-share state machine ARN, and
      `states:DescribeExecution` + `states:StopExecution` on `…:execution:{machineName}:*`.
- [ ] `s3:GetObject` covers the manifest key; `s3:PutObject`, `s3:GetObject`,
      `s3:ListMultipartUploadParts` and `s3:AbortMultipartUpload` cover
      `{admin_bucket}/table-share/*` for the `ResultWriter`.
- [ ] The existing explicit `s3:DeleteObject` **Deny** on both data buckets and the admin bucket is
      unchanged and still renders.
- [ ] No new `Resource: "*"` statement appears; the SPEC-139 plan scan's IAM findings do not grow.
- [ ] The results bucket is in the same account and Region as the state machine (a cross-account or
      cross-Region `ResultWriter` fails the execution with `States.ResultWriterFailed`) — asserted
      by construction, since the admin bucket is a module output of this account's stack.

---

## Data Model

```python
# One line of transfer-manifest.jsonl — the Distributed Map's item
{
  "recipient": "bob",
  "kind": "user",                              # "user" | "space"
  "srcBucket": "dat-prod-user-space",
  "srcKey": "alice/tables/sales/year=2024/part-0.parquet",
  "destBucket": "dat-prod-user-space",
  "destKey": "bob/shared_tables/sales/year=2024/part-0.parquet"
}

# build-transfer-manifest output
{ "transferManifestKey": "table-share/{hash}/transfer-manifest.jsonl", "itemCount": 4200 }

# copy-objects (batch verb) input / output
{ "Items": [ <transfer item>, ... ] }
{ "copied": 100, "failures": [ { "recipient": "bob", "reason": "copy_failed" } ] }

# collect-transfer-results output (unchanged downstream shape)
{ "recipients": [ { "recipient": "bob", "kind": "user", "status": "ok" },
                  { "recipient": "carol", "kind": "space", "status": "failed",
                    "reason": "copy_failed", "failedItems": 3 } ] }
```

```python
# lambdas/control-plane-common/cpcommon
#   transfer/manifest.py   write_manifest(bucket, key, items) -> itemCount   (JSONL)
#   transfer/copy.py       copy_batch(items) -> per-item outcomes            (moved from tscommon.copy)
#   transfer/results.py    read_failed_items(bucket, resultWriterKey) -> [{...}]
#   transfer/config.py     MAX_ITEMS_PER_BATCH, MAP_MAX_CONCURRENCY
```

## Implementation Phases

### Phase 1: The engine on `cpcommon`

- Move `tscommon.copy` to `cpcommon.transfer.copy` as a batch copier; add `transfer.manifest` and
  `transfer.results`; unit-test each against fixtures.
- Leave `tscommon` importing from `cpcommon` so nothing else moves yet.

### Phase 2: Verbs

- `build-transfer-manifest` and `collect-transfer-results` as new single-task Lambdas; rewrite
  `copy-objects` as the batch verb; update the deploy matrix and layer attachment
  (`test_deploy_matrix.py` must stay green — it is the check that catches a missing layer).

### Phase 3: Machine + IAM

- Split the recipient Map, add the Distributed Map state with reader/batcher/writer, the
  `IsPresent`-guarded `Choice`, and the role grants; `tofu validate` + policy render checks.

### Phase 4: Verification

- Unit + ASL-shape tests (no nested Distributed Map, `NotifyFailure` still present, batch sizing).
- **Live check (owed):** share a table of several hundred objects to two recipients where one
  conflicts — confirm the conflicting recipient gets `conflict` with no child execution for it, the
  other receives every object at the correct key, and `logs/service=table-share/` carries the run.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, `component-inventory` rows for `cpcommon.transfer`, a `decisions.md`
  entry (the Distributed Map decision **and** the S3-Batch-Operations rejection with its reason),
  one Key Decisions line, and the `architecture.md` *Table Share* + *Deferred / Future Scope*
  updates.
