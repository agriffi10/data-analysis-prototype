# Spec: Restore — Glacier Retrieval, the Wait Loop, Copy-Back & Terminals

**ID:** SPEC-171
**Status:** Completed
**Last Updated:** 2026-08-10
**Depends On:** SPEC-170 (the restore contract, the lookup and the guard), SPEC-169 (the archive layout and the receipt), SPEC-160 (`cpcommon.transfer`)

## Overview

SPEC-170 stops the moment it knows a restore is legal and unobstructed. This spec is the part that
takes hours: ask S3 to bring every archived object back out of Glacier, wait for it, copy it to where
it came from, delete the archive, and rewrite the receipt to say what happened.

The asynchrony is not an implementation choice — it is the storage class. An object in `GLACIER` is
not readable, and **a `CopyObject` whose source is in `GLACIER` fails with `InvalidObjectState`**;
it must be restored to a temporary readable copy first, which takes 3–5 hours at the Standard
retrieval tier. So the machine grows a `Wait`/poll loop, the user gets told at the start rather than
at the end, and the run is measured in hours rather than the seconds every other plane takes.

Two rules follow from that and shape everything below. **Retrieval is billed and cannot be
cancelled**, so nothing initiates it that the guard has not already cleared. And **the temporary
restored copy expires**, so the copy-back has a deadline: the availability window is a named constant
generous enough that a slow copy cannot outlive the thing it is copying.

## Scope

### In Scope

- **initiate-restore**: `RestoreObject` across every archived object, the retrieval tier and the
  availability window, and tolerance of the already-restored and already-in-progress responses.
- The **`Wait`/poll loop**: bounded iterations, a poll that samples rather than heads everything, and
  the timeout terminal.
- **copy-back**: the Distributed Map that copies the archive into the space at `STANDARD`.
- The **partial-restore rule** and what the user is told when it fires.
- **delete-archived**: removing the archive prefix and its manifest on full success only.
- The **receipt rewrite** — the restore fields the user specified.
- Terminal states, `TimeoutSeconds`, and the execution-role IAM for retrieval and copy-back.

### Out of Scope

- Any UI and the notification producer — SPEC-172. This spec fixes the outcomes and their wording;
  that spec delivers them.
- Expedited retrieval and provisioned capacity. The tier is a named constant with Standard as its
  value; buying provisioned capacity units is not something this portal does.
- Resuming a timed-out restore. A restore that exceeds its bound is a terminal failure and is
  re-submitted; because the archive is untouched on failure, re-submission is always safe.
- Notifying the user at the moment retrieval *completes*, separately from the restore completing.
  One start notification and one terminal notification, both in SPEC-172.
- S3 Event Notifications (`s3:ObjectRestore:Completed`) as the completion signal — see FR-002.

---

## Functional Requirements

### FR-001: Initiating retrieval

#### Description:

`RestoreObject` on every object in the restore plan. This is the point of no return: it is billed,
it cannot be cancelled, and it is why SPEC-170's guard runs first.

#### Acceptance Criteria:

- [ ] `RestoreObject` is issued for every object in `restore-plan.json`, with
      `GlacierJobParameters.Tier` from `arcommon.config.RESTORE_TIER` and `Days` from
      `RESTORE_AVAILABILITY_DAYS`.
- [ ] `RESTORE_TIER` is `"Standard"` (3–5 hours). A comment records the alternatives: `Expedited`
      (1–5 minutes) is per-request and subject to capacity, `Bulk` (5–12 hours) is cheaper but
      doubles the worst-case wait for a user sitting in a portal.
- [ ] `RESTORE_AVAILABILITY_DAYS` is generous relative to the copy-back — the restored copy must
      outlive the copy that reads it. A comment records the failure mode if it does not: the
      copy-back begins succeeding and then starts failing `InvalidObjectState` partway through, which
      presents as a partial restore with no obvious cause.
- [ ] A `RestoreAlreadyInProgress` (HTTP 409) response is **tolerated, not raised** — the object is
      already being retrieved, which is the desired state. A redriven execution must not fail on it.
- [ ] A `RestoreObject` against an object whose retrieval has already completed returns success and
      is billed as a `GET`; it is likewise tolerated.
- [ ] Retrieval requests are issued through a bounded worker pool, and the verb is chunked so that an
      archive larger than one Lambda invocation can process is driven by the same Distributed Map
      mechanism the copy uses, over the same plan — not by a single verb with a longer timeout.
- [ ] A genuine failure on any object is a terminal failure. Nothing is copied and the archive is
      untouched, so the user re-submits.
- [ ] A test asserts there is no ASL path to this state from SPEC-170's `destination_occupied`,
      `archive_not_found` or `archive_incomplete` branches.

### FR-002: The wait loop

#### Description:

Poll until every object reports retrieval complete, or give up.

#### Acceptance Criteria:

- [ ] The loop is `Wait` → `poll-restore` → `Choice`, with the wait interval a named constant and
      the iteration count bounded by `RESTORE_MAX_POLLS`. Exhausting it is the terminal failure
      `restore_timed_out`.
- [ ] `poll-restore` establishes completion by `HeadObject` and reading the **`Restore` header**:
      `ongoing-request="false"` means complete, `ongoing-request="true"` means still working, and the
      header being absent on an object whose storage class is still `GLACIER` means retrieval was
      never requested for it — which is a failure, not a "not yet".
- [ ] That third case has its own test. It is the one that distinguishes a slow restore from a
      dropped one, and treating it as "not yet" would burn every poll iteration before reporting a
      timeout for something that was never going to complete.
- [ ] The poll **samples**: it heads objects in bounded pages and remembers the index it reached, so
      an archive of 200,000 objects does not issue 200,000 heads on every iteration. The loop
      advances only when a page is fully complete.
- [ ] The loop carries state as an **S3 pointer, not an inline list** — the poll's progress record
      lives beside the plan in the admin bucket. A per-object status list in the state payload is the
      256 KB cap failure, whose overflow escapes every `Catch`.
- [ ] The machine carries a top-level **`TimeoutSeconds`** sized above the worst-case retrieval plus
      copy-back. It is a top-level ASL field, not a resource argument — the distinction SPEC-157
      records.
- [ ] `s3:ObjectRestore:Completed` event notifications are **rejected** as the completion signal, and
      the reason is recorded at the loop: they would require per-object bucket notification
      configuration, a correlation store keyed by object to know which run an event belongs to, and a
      second delivery path with its own at-least-once semantics — to replace a poll the plane already
      knows how to write, in a machine that is already waiting hours.

### FR-003: Copy-back

#### Acceptance Criteria:

- [ ] A **top-level** Distributed Map over the restore plan copies each object from the archive
      bucket to its destination key with `StorageClass: "STANDARD"`, through
      `cpcommon.transfer.copy_batch` — the same engine, with the storage class SPEC-169 FR-002 added.
- [ ] The copy is what actually changes the storage class. The restored copy is temporary; without
      the copy the object stays in `GLACIER` and expires back to unreadable. A test asserts the
      destination's storage class is explicitly `STANDARD` and not merely omitted.
- [ ] `ItemProcessor.ProcessorConfig` is `{Mode: DISTRIBUTED, ExecutionType: STANDARD}`,
      `ToleratedFailurePercentage` is 100, and `ResultWriter` exports to
      `{admin_bucket}/archive/{requestId}/restore-results/` — SPEC-160's shape.
- [ ] Object metadata and content type survive the round trip: the archive copy in SPEC-169 and the
      copy-back here both use `MetadataDirective: COPY`, and a test fixtures an object with a custom
      content type and asserts it is identical after archive-then-restore.
- [ ] Folder placeholder objects are restored, so an archived empty folder comes back as an empty
      folder.

### FR-004: The partial-restore rule

#### Description:

Unlike archiving, a partial restore cannot be rolled back to nothing — the user's space now holds
some of their data, and deleting it to make the operation atomic would be destroying the very thing
the restore was for.

#### Acceptance Criteria:

- [ ] A copy-back with any failed item is the terminal failure `restore_incomplete`. **Nothing is
      deleted** — not the copied objects, not the archive.
- [ ] The archive is deliberately kept. It is the only complete copy, and a restore that half
      succeeded and then deleted its own source would be unrecoverable.
- [ ] The failure message states three things: how many objects were restored, that the archive is
      **still intact** and still restorable under the same id, and that re-requesting will report a
      `destination_occupied` conflict against the objects that did land — which the user resolves by
      clearing them. Without that last sentence the obvious next action produces a refusal that reads
      like a new bug.
- [ ] A test drives the branch from a fixtured `ResultWriter` export with one failure and asserts the
      archive-deletion verb was never invoked.

### FR-005: Archive cleanup

#### Acceptance Criteria:

- [ ] On a fully successful copy-back — and only then — the archive prefix is deleted, including
      `_manifest.json`.
- [ ] Deletion uses `DeleteObjects` in batches of 1000, attempts **every page before any raise**, and
      treats a non-empty per-item `Errors` array as a failure — the SPEC-151 discipline, identical to
      SPEC-169 FR-005.
- [ ] A failed cleanup does **not** fail the restore. The user's data is back, which is the outcome
      they asked for; the residue is reported in the structured log and swept by the bucket's 7-year
      lifecycle. The terminal state is success with a `cleanupIncomplete` flag.
- [ ] Cleanup deleting objects still inside the `GLACIER` 90-day minimum storage duration is expected
      and is charged as an early-deletion fee. A comment records it so a future cost investigation
      does not read it as a defect.

### FR-006: The receipt rewrite

#### Acceptance Criteria:

- [ ] The receipt at `{spaceRoot}archive/{archiveId}/receipt.txt` is rewritten — **not deleted** — on
      both the success and the `restore_incomplete` paths, through the single
      `arcommon.receipt.render` writer SPEC-169 established.
- [ ] `Restore requested` becomes the timestamp of the restore request, and `Restored to` becomes the
      destination path on success. On `restore_incomplete` the restore field records the attempt and
      its outcome, so the receipt never claims a restore that did not finish.
- [ ] The receipt survives the archive's deletion and remains the permanent record of what was
      archived and when it came back. Users cannot delete it (SPEC-168 FR-006), so receipts
      accumulate; the delivery doc records that as an accepted consequence of making the two restore
      fields readable at all.
- [ ] A `Restore requested` marker is written when retrieval is **initiated**, not only when it
      completes — the user is waiting hours and the receipt is the only durable place that says a
      restore is in flight.
- [ ] A rewrite that fails does not fail the run once the data has landed. The message ordering is
      most durable to least: data restored → receipt updated → notification.

### FR-007: Execution and state-machine IAM

#### Acceptance Criteria:

- [ ] The execution role gains `s3:RestoreObject` on the archive bucket. It is a **distinct action**
      from `s3:GetObject` and `s3:PutObject`; a role holding both still cannot initiate retrieval.
- [ ] It gains `s3:PutObject` on the two space buckets **unrestricted by prefix within the space
      root**, which is wider than the `*/archive/*` grant SPEC-169 needed for the receipt — a restore
      writes wherever the data came from. The widening is called out explicitly in the delivery doc
      rather than arriving silently in a diff.
- [ ] The state-machine role gains the Distributed Map grants for the copy-back Map:
      `states:StartExecution`, `states:DescribeExecution` on `…:execution:{machineName}:*`,
      `GetObject` on the plan, and `ResultWriter` writes under `{admin_bucket}/archive/*`.
- [ ] An **IAM policy simulation against the deployed role** is run and recorded, each denial paired
      with an `allowed` control — an `implicitDeny` alone cannot distinguish an ungranted action from
      a wrong resource ARN, the trap SPEC-149 and SPEC-157 both recorded.
- [ ] A rendered-policy test asserts no new `Resource: "*"` statement.

---

## Data Model

```python
# The poll progress record  ({admin_bucket}/archive/{requestId}/restore-progress.json)
{ "requestId": "b71d…", "pollCount": 7, "completedThrough": 4000, "objectCount": 1204 }

# Terminal outcomes reaching SPEC-172's producer
#   restored             — objectCount, totalBytes, destination path, cleanupIncomplete?
#   restore_incomplete   — restored count, failed count, "archive is intact, id still valid"
#   restore_timed_out    — polls exhausted, "archive is intact, request again"
```

```python
# lambdas/archive-common/arcommon  (additions)
#   config.py   RESTORE_TIER, RESTORE_AVAILABILITY_DAYS, RESTORE_POLL_SECONDS,
#               RESTORE_MAX_POLLS, RESTORE_POLL_PAGE
#   receipt.py  render(record) — now also renders the two restore fields
#   messages.py restored / restore_incomplete / restore_timed_out
```

## Implementation Phases

### Phase 1: Retrieval

- `initiate-restore` over the plan, the tier and window constants, tolerance of 409 and
  already-restored.

### Phase 2: The wait loop

- `Wait`/`poll-restore`/`Choice`, the paged sampling and its S3-pointer progress record, the
  never-requested detection, `RESTORE_MAX_POLLS` and the machine's `TimeoutSeconds`.

### Phase 3: Copy-back and terminals

- The Distributed Map at `STANDARD`, the collector, the partial-restore branch, `delete-archived`,
  the receipt rewrite, and all terminal states.

### Phase 4: Verification

- Unit tests for the 409 tolerance, the absent-`Restore`-header case, the paged poll's progress
  arithmetic, the partial branch, and the `MetadataDirective: COPY` round trip.
- **Live check (owed), and it is the one that cannot be simulated:** restore the archive created by
  SPEC-169's live check, end to end, against real Glacier. Confirm the wait loop actually waits
  (multiple poll iterations in `logs/service=archive/`, hours apart), the objects come back at
  `StorageClass: STANDARD` verified by `head-object`, the content of one file is byte-identical to
  what was archived, the archive prefix is gone, and the receipt shows both restore fields populated.
  Then confirm a **shared-space** archive restores the same way. Nothing that runs in CI exercises a
  real Glacier retrieval — the tier's latency, the `Restore` header's exact format and the
  `InvalidObjectState` boundary are all only observable here.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, complete the `architecture.md` → *Control Planes → Archive* section, a
  `decisions/` entry (retrieval as the point of no return, polling over event notifications, the
  partial-restore asymmetry with archiving's commit gate, the receipt surviving), and one Key
  Decisions line. The user-facing surface lands in SPEC-172, so the Help sweep happens there.
