---
type: Spec
id: SPEC-169
title: "Archive — Source Resolution, Glacier Transfer & Source Deletion"
description: "Adds Archive's expansion, Glacier copy, all-or-nothing verification, source deletion and receipt writing, deleting a user's files only after every object is confirmed copied."
spec_status: Completed
depends_on: [SPEC-168, SPEC-160, SPEC-151, SPEC-157]
arc: archival
arc_order: 2
---

**Dependency notes:** SPEC-168 (the plane, the bucket, `arcommon`, validate-authorize), SPEC-160 (`cpcommon.transfer`), SPEC-151 (the partial-delete discipline), SPEC-157 (execution-name stamping)
## Overview

SPEC-168 proves the actor may archive what they selected. This spec does it: expand the selection
into an object list, copy every object into the archive bucket at `GLACIER`, verify that **every**
object arrived, delete the sources, and write the receipt the user will later paste a UUID from.

The whole spec turns on one rule. **The source is deleted only when every single object has been
confirmed copied.** Archiving is the only operation in this portal that deletes the user's data as a
side effect of a copy, and the failure mode it must never have is "copied 900 of 1000, deleted 1000".
The commit gate is therefore explicit, the collector's verdict is all-or-nothing, and a partial
transfer rolls the archive copy back rather than proceeding.

The second decision worth stating up front is that **the receipt is a report, not a record**. Restore
does not parse it. An archived key carries its own origin — `personal/alice/archive/{uuid}/reports/q1.csv`
came from `alice/reports/q1.csv` — so SPEC-170 reconstructs every destination from a `ListObjectsV2`
over the archive prefix, exactly as SPEC-143 judges a table by its shape rather than by a marker it
also writes. The manifest this spec writes is an integrity check that can only ever fire when
something is already wrong.

## Scope

### In Scope

- **inspect-source**: expand every selected folder, re-check containment on each returned key, tally
  object count and total bytes, enforce the caps, and write the plan as an S3 pointer.
- **build-transfer-manifest**: the JSONL the Distributed Map reads, carrying the destination storage
  class.
- Extending **`cpcommon.transfer`** with a per-item storage class — the archive plane is its third
  caller.
- The **Distributed Map** copy into the archive bucket at `GLACIER`, and the collector that reads the
  `ResultWriter` export.
- The **commit gate**: all-or-nothing, with a rollback of the partial archive copy on failure.
- **delete-source**: batched deletion with the per-item `Errors` discipline SPEC-151 established.
- The **manifest** (`_manifest.json`, in the archive bucket) and the **receipt**
  (`archive/{uuid}/receipt.txt`, in the user's space).
- Terminal states and the execution-role IAM for all of the above.

### Out of Scope

- Restore in any form — SPEC-170 and SPEC-171.
- Any UI, and the success/failure notification producer — SPEC-172. This spec's only notification is
  SPEC-152's pre-verb failure path.
- Resuming a partially-failed archive. A failed archive leaves the source intact and is re-submitted
  as a new request with a new UUID.
- Deduplicating against a previous archive of the same folder. Two archives of the same data are two
  archives.
- Archiving a folder that another archive is mid-flight over. FIFO `MessageGroupId` is the space root
  (SPEC-168 FR-004), so two archives from one space serialize; overlapping selections in *different*
  spaces cannot overlap by construction.

  > **SUPERSEDED 2026-09-15.** Two archives from one space do not serialize — the Pipe starts
  > executions `FIRE_AND_FORGET` — so the mid-flight case is reachable. This spec's commit gate is
  > what makes it safe: `docs/decisions/archive-and-restore/`, *The group id orders the STARTS,
  > not the runs*.

---

## Functional Requirements

### FR-001: Source expansion and the caps

#### Description:

Turn the selected files and folders into the exact object list that will be copied, and refuse a
request that is too large before anything moves.

#### Acceptance Criteria:

- [ ] Every `folder` item is expanded recursively through `cpcommon.s3_listing`, paginating fully; a
      truncated listing that is treated as complete is a data-loss bug, so the paginator's
      continuation handling has its own test.
- [ ] Every key returned by `ListObjectsV2` is **re-checked for containment** against the authorized
      source root, not trusted because the request-time check passed. This is SPEC-165's rule for the
      same reason: the request named a folder, the listing named the objects, and only the second one
      is what gets copied.
- [ ] Keys that are folder placeholder objects (a key ending `/` with zero bytes) are carried in the
      plan so that an archived empty folder is restorable, and are counted in the object count but
      contribute zero to the byte total.
- [ ] Overlapping selections are collapsed: selecting `reports/` and `reports/q1.csv` yields
      `reports/q1.csv` exactly once. A duplicated destination key in the plan is a defect with its
      own test.
- [ ] The expanded object count above `ARCHIVE_MAX_OBJECTS`, or the total byte size above
      `ARCHIVE_MAX_BYTES`, is a terminal failure naming the measured value and the cap. Both
      constants live in `arcommon.config` with the reasoning for their values.
- [ ] An empty expansion — every selected folder turned out to hold nothing — is a terminal failure
      `nothing_to_archive`, **not** a success. A receipt claiming zero files archived is worse than a
      refusal, and an empty archive prefix would be indistinguishable from a vanished one at restore
      time.
- [ ] The plan is written to `{admin_bucket}/archive/{requestId}/copy-plan.json` and passed between
      states as an **S3 pointer, never inline** — `States.DataLimitExceeded` escapes every `Catch`
      and is the worst failure mode this plane has (no notification at all).
- [ ] A lifecycle rule expires the `archive/` prefix in the admin bucket, and it carries a
      `filter.prefix` — the admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check fails any
      rule that does not.
- [ ] A test pins the admin-bucket prefix used by the plan to the one named in the execution role's
      IAM grant and in the lifecycle rule, matching `test_the_prefix_matches_what_the_iam_grant_and_lifecycle_rule_use`.

### FR-002: The transfer manifest and the storage class

#### Acceptance Criteria:

- [ ] `build-transfer-manifest` writes **JSON Lines**, one line per object, with the item shape in the
      Data Model below — including a `storageClass` field taken from
      `arcommon.config.ARCHIVE_STORAGE_CLASS`.
- [ ] The manifest is written to
      `{admin_bucket}/archive/{requestId}/{executionName}/transfer-manifest.jsonl` —
      **execution-unique**, not on the bare `{requestId}`, for SPEC-160's reason: two overlapping
      executions of the same request must not clobber each other's manifest.
- [ ] The execution name comes from a **`Pass`-stamped context**, never from reading `$$` in the
      task's own `Parameters` — that wraps the payload, and every notify path reads the request at
      the top level (SPEC-157's recorded trap).
- [ ] `cpcommon.transfer.copy_batch` gains an **optional per-item `storageClass`**, defaulting to
      absent, which maps to `CopyObject`'s `StorageClass` argument. Absent means S3's own default
      (`STANDARD`), so table share and file send are byte-for-byte unaffected — a test asserts the
      existing callers' `CopyObject` arguments are unchanged.
- [ ] The extension lands in `cpcommon`, not `arcommon`. SPEC-156 settled that `cpcommon` owns the
      algorithm and a domain layer owns its wording, and this plane is the engine's **third** caller.
- [ ] Objects above 5 GB go through `UploadPartCopy`, which the engine already does; a test fixtures
      a >5 GB object and asserts the multipart path is taken **and** that the storage class is
      applied to the multipart destination, since it is set on `CreateMultipartUpload` rather than on
      the copy parts.
- [ ] `itemCount: 0` writes no manifest, and the Map is skipped via a `Choice` guarded by
      **`IsPresent` before the numeric test**. FR-001 already makes this unreachable, which is why it
      is specified rather than omitted — an unreachable branch that raises `States.Runtime` when it is
      reached is a worse outcome than a branch that refuses.

### FR-003: The Distributed Map copy

#### Acceptance Criteria:

- [ ] A **top-level** Distributed Map reads the manifest —
      `ItemReader` on `arn:aws:states:::s3:getObject` with `ReaderConfig.InputType: JSONL` — and is
      not nested inside any other `Map`; a test asserts the nesting rule.
- [ ] `ItemProcessor.ProcessorConfig` is `{Mode: DISTRIBUTED, ExecutionType: STANDARD}`. STANDARD,
      not EXPRESS, for SPEC-160's reasons: a batch may hold a multi-GiB object whose multipart copy
      exceeds EXPRESS's 5-minute ceiling, and at-least-once re-execution would recopy the batch.
- [ ] `MaxItemsPerBatch` and `MaxConcurrency` are named constants in `cpcommon.transfer.config`,
      sized to keep child input far below 256 KiB and to bound Lambda concurrency and S3 request
      rates — explicitly not the 10,000 default.
- [ ] `ToleratedFailurePercentage` is **100**, so the Map Run always finishes and the collector can
      see every outcome. A Map that aborts early would leave the commit gate unable to distinguish
      "failed" from "not attempted".
- [ ] `ResultWriter` exports to `{admin_bucket}/archive/{requestId}/results/`, and the collector reads
      it through `cpcommon.transfer.read_failed_items`.
- [ ] The copy is idempotent: re-copying an object that already exists at the destination overwrites
      it with identical bytes, so a retried batch is safe.

### FR-004: The commit gate

#### Description:

The single rule the feature rests on. Nothing is deleted until everything is copied.

#### Acceptance Criteria:

- [ ] `collect-transfer-results` compares the number of **successfully copied** objects against the
      plan's object count. The verdict is boolean: every object copied, or not.
- [ ] Any shortfall — one failed item, or a count mismatch with no reported failures — takes the
      **`rollback` branch**, and `delete-source` is unreachable from it. A test asserts there is no
      path in the ASL from a non-empty failure set to the deletion state.
- [ ] The rollback verb deletes the objects the collector reports as successfully copied, under the
      archive prefix only, using the same per-item `Errors` discipline as FR-005.
- [ ] A rollback that itself fails partially does **not** change the outcome. The source is intact,
      which is the property that matters; the residue is reported in the failure notification and in
      `logs/service=archive/`, and it will be swept by the bucket's 7-year lifecycle. A comment
      records that this residue is billed at the `GLACIER` 90-day minimum.
- [ ] The terminal failure names how many objects were copied, how many failed, and states plainly
      that **nothing was deleted** — SPEC-106 wording, no raw AWS text.
- [ ] A test drives the whole gate from a fixtured `ResultWriter` export containing one failure and
      asserts the source-deletion verb was never invoked.

### FR-005: Source deletion

#### Acceptance Criteria:

- [ ] Deletion goes through `DeleteObjects` in batches of 1000, and **every page is attempted**
      before any raise — the SPEC-151 rule.
- [ ] `DeleteObjects` returns **HTTP 200 with a per-item `Errors` array**; a non-empty `Errors` array
      raises, and a response that is inspected only by status code is the defect SPEC-151 fixed. This
      verb has its own test for it.
- [ ] Counts are reported, never keys — a failure message naming user file paths is a disclosure this
      plane has no reason to make.
- [ ] A partial deletion is a terminal failure, and the archive copy is **kept**. The user's data
      exists in two places, which is recoverable; the alternative — deleting the archive after a
      partial source delete — is not.
- [ ] Deletion is replay-safe: an already-absent key is not an error, so a re-driven execution
      completes.
- [ ] Any selected key that resolves to `DO_NOT_DELETE.txt` was already refused at SPEC-168 FR-005,
      and a defence-in-depth assertion here fails the run rather than issuing a delete the IAM Deny
      would reject mid-batch.

### FR-006: The manifest and the receipt

#### Description:

Two artifacts with two different jobs. The manifest is machine-readable and lives where the user
cannot reach it. The receipt is human-readable and lives where the user will look for it.

#### Acceptance Criteria:

- [ ] `_manifest.json` is written to the **archive bucket** at `{archiveRoot}_manifest.json`, before
      the source is deleted, carrying the request id, timestamps, actor, source root, object count
      and total bytes.
- [ ] It is written **before** `delete-source` and the receipt after it: most durable to least,
      matching the data-quality plane's report → notification → index ordering.
- [ ] The manifest is an **integrity record, not a lookup table**. A test asserts that no restore verb
      requires it to be present — SPEC-170 reconstructs every destination from the archived keys
      themselves. Its only consumers are the count/byte cross-check and human diagnosis.
- [ ] The receipt is written to `{sourceRoot}archive/{requestId}/receipt.txt` as **plain UTF-8 text**,
      by the execution role. It carries, one labelled line each: the time of the request, the request
      id, the original S3 path of the data, the new S3 path of the data, the total size archived
      (human-readable **and** exact bytes), the total number of files archived, whether a restore has
      been requested (`No` at write time), and the restore key (empty at write time).
- [ ] The two restore fields are present from the first write with placeholder values, not added
      later. SPEC-171 rewrites the whole file; a field that only appears after a restore would make
      the receipt's format conditional on its own history.
- [ ] Byte sizes render through the shared formatter's TB ceiling behaviour (SPEC-155 FR-007) so the
      receipt and the file browser never disagree about the same number.
- [ ] The receipt write failing is a **terminal failure** of the run even though the data is safely
      archived, because a user with no receipt has no UUID and therefore no route to a restore. The
      failure message tells them the data is archived and names the request id, so the run is
      recoverable by hand.
- [ ] The receipt is written **after** the source deletion, so a receipt only ever exists for an
      archive that actually completed.

### FR-007: Execution-role IAM

#### Acceptance Criteria:

- [ ] The execution role holds, each scoped to a constructed ARN and none on `Resource: "*"`:
      `GetObject`/`ListBucket`/`DeleteObject` on the two space buckets, `PutObject` on the space
      buckets restricted to `*/archive/*` (the receipt),
      `PutObject`/`GetObject`/`DeleteObject`/`ListBucket` and the multipart actions on the archive
      bucket, and `PutObject`/`GetObject`/`ListBucket` on `{admin_bucket}/archive/*`.
- [ ] Everything Distributed-Map-related — `states:StartExecution` on the machine ARN,
      `states:DescribeExecution` on `…:execution:{machineName}:*`, `GetObject` on the manifest, and
      the `ResultWriter` writes — goes on the **state-machine role**, not the execution role
      (SPEC-160 FR-006).
- [ ] A rendered-policy test asserts no new `Resource: "*"` statement, keeping the SPEC-139 plan
      scan's IAM findings flat.

---

## Data Model

```python
# The copy plan  ({admin_bucket}/archive/{requestId}/copy-plan.json)
{
  "requestId": "9f2c1b8e-…",
  "source":  { "bucket": "dat-prod-user-space", "root": "alice/" },
  "archive": { "bucket": "dat-prod-archive", "root": "personal/alice/archive/9f2c1b8e-…/" },
  "objectCount": 1204,
  "totalBytes": 8_412_339_201,
  "objects": [ { "relKey": "reports/2026/q1.csv", "bytes": 90_112 }, … ]
}

# One manifest line  (transfer-manifest.jsonl)
{ "srcBucket": "dat-prod-user-space", "srcKey":  "alice/reports/2026/q1.csv",
  "destBucket": "dat-prod-archive",   "destKey": "personal/alice/archive/9f2c1b8e-…/reports/2026/q1.csv",
  "storageClass": "GLACIER" }

# _manifest.json  (archive bucket, {archiveRoot}_manifest.json)
{
  "version": 1, "requestId": "9f2c1b8e-…", "archivedAt": "2026-08-10T14:02:11Z",
  "actor": "alice",
  "source": { "bucket": "dat-prod-user-space", "root": "alice/" },
  "objectCount": 1204, "totalBytes": 8_412_339_201,
  "storageClass": "GLACIER"
}
```

```
Requested:        2026-08-10 14:02:11 UTC
Request ID:       9f2c1b8e-…
Original path:    s3://dat-prod-user-space/alice/reports/
Archived path:    s3://dat-prod-archive/personal/alice/archive/9f2c1b8e-…/
Total size:       7.8 GB (8412339201 bytes)
Files archived:   1204
Restore requested: No
Restored to:      —
```

```python
# lambdas/archive-common/arcommon  (additions)
#   plan.py     expand(source_root, items) -> objects        — re-checks containment per key
#   receipt.py  render(record) -> str                        — the .txt above, one writer
#   manifest.py write(archive_root, record)                  — the integrity record
```

## Implementation Phases

### Phase 1: The engine extension

- `cpcommon.transfer.copy_batch` gains the optional per-item storage class, including the
  `CreateMultipartUpload` path; tests assert the existing callers are unchanged.

### Phase 2: inspect-source and the plan

- Expansion, per-key containment re-check, overlap collapse, the caps, the S3-pointer plan, and the
  admin-bucket prefix + lifecycle rule.

### Phase 3: The transfer

- `build-transfer-manifest`, the execution-name `Pass` stamp, the Distributed Map, and
  `collect-transfer-results`.

### Phase 4: The commit gate, deletion and the artifacts

- The all-or-nothing branch and the rollback verb; `delete-source` with the per-item `Errors`
  discipline; `_manifest.json`; the receipt writer.

### Phase 5: Verification

- Unit tests for the commit gate driven from a fixtured `ResultWriter` export, the paginated
  expansion, the `Errors`-array deletion, and the receipt renderer.
- **Live check (owed):** archive a real folder of at least a few hundred objects from a personal
  space. Confirm the objects appear in the archive bucket at `StorageClass: GLACIER` (via
  `head-object`, not by inference), the source is gone, `archive/{uuid}/receipt.txt` reads correctly,
  and the run appears in `logs/service=archive/`. Then archive a folder in a **shared** space and
  confirm the same. Then force a partial failure — archive a folder while a `Deny` is temporarily in
  place on one key — and confirm **the source is still there**. That last one is the check this whole
  spec exists for and cannot be discharged by a unit test.

### Phase 6: Completion ritual

- Delivery doc, INDEX status, extend the `architecture.md` → *Control Planes → Archive* section, a
  `decisions/` entry (the commit gate, the receipt-as-report / self-describing-key decision, the
  storage-class extension on `cpcommon.transfer`), one Key Decisions line, and a
  `component-inventory/` row for the `cpcommon.transfer` extension. No user-facing surface yet — no
  Help change.
