# Spec: Table Share — Recipient Map + Copy (check-target-absent + copy-objects)

**ID:** SPEC-091
**Status:** Completed
**Last Updated:** 2026-07-04
**Depends On:** SPEC-090 (copy plan + cloned definition), SPEC-089 (validated recipients)

> **Read `docs/table-share-architecture.md` §5, §9 first.**

## Overview

Implement the recipient fan-out: a Step Function **`Map`** over the validated recipients, each item running **check-target-absent** then **copy-objects**, with a **per-item `Catch`** so one recipient's failure never aborts the others. `check-target-absent` guards the conflict rule (fail that recipient if the name already exists, or the target prefix is non-empty); `copy-objects` performs the parallel, layout-preserving, server-side S3 copy into `{recipient-base}/shared_tables/{tableName}/`.

## Scope

### In Scope

- The SFN **`Map`** over `recipients` (bounded concurrency), per-item state sequence `check-target-absent → copy-objects → create-table` (create-table lands in SPEC-092), with a per-item `Catch` → recorded per-recipient failure.
- Per-recipient **destination resolution**: `user` → `s3://<user-space-bucket>/{name}/shared_tables/{tableName}/`; `space` → `s3://dat-prod-shared-space/{name}/shared_tables/{tableName}/`.
- **check-target-absent**: Glue `GetTable(recipientDB, tableName)` → conflict if it exists; **also** treat a **non-empty** target prefix as a conflict; the recipients annotated invalid by SPEC-089 (unknown user/space) short-circuit here to their terminal failure.
- **copy-objects**: server-side `CopyObject` of every planned object to `{dest}/{relKey}`, **parallelized** with bounded concurrency; **multipart copy** (`UploadPartCopy`) for objects > 5 GiB; layout (flat + `key=value/`) preserved.
- **Idempotency**: a retried copy re-copies harmlessly; because the conflict check precedes copy, an existing recipient table's data is never clobbered.
- Per-recipient **terminal reasons** recorded on the item (`ok` / `conflict` / `unknown_target` / `copy_failed`) for SPEC-092's summary + SPEC-094's notifications.
- Execution-role grants for this step: S3 `ListBucket`/`GetObject` on source locations, S3 `PutObject`/multipart on any `{...}/shared_tables/...` target in both buckets, Glue `GetTable` on recipient DBs.

### Out of Scope

- Creating the recipient table (DDL) — SPEC-092 (the third Map state).
- Notifications — SPEC-094.
- S3 Batch Operations — deferred; v1 copies per-object (caps from SPEC-090 bound the work).

> **Superseded by SPEC-160 (2026-08-10):** S3 Batch Operations is **rejected, not deferred**. Its
> Copy operation cannot rewrite a key (`TargetKeyPrefix` prepends the *full* source key), it caps
> objects at 5 GB where `UploadPartCopy` already handles more, and one job writes to one destination
> bucket while recipients span two. The scale path is a top-level **Step Functions Distributed Map**
> over a flat `(recipient × object)` manifest. Full entry: `decisions/` → *Table Share*.

- Rolling back a partial copy on a later create failure — the copied objects remain; a retry/overwrite is a future concern (documented).

---

## Functional Requirements

### FR-001: Recipient Map with per-item isolation

#### Acceptance Criteria:

- [ ] The `Map` runs each recipient independently with bounded concurrency; a per-item `Catch` records that recipient's failure and **does not** stop siblings.
- [ ] A request with N recipients yields N per-item outcomes (each `ok` or a specific failure reason).
- [ ] Recipients marked invalid upstream (SPEC-089) surface as `unknown_target` without attempting a copy.

### FR-002: Conflict guard (check-target-absent)

#### Acceptance Criteria:

- [ ] If `tableName` already exists in the recipient DB (Glue `GetTable` succeeds), that recipient fails with `conflict` (no copy, no overwrite).
- [ ] If the recipient `shared_tables/{tableName}/` prefix is **non-empty**, that recipient fails with `conflict` (guards leftover data from a prior partial run).
- [ ] Sharing into the **source** DB under the **same** name self-conflicts (fails `conflict`); a **different** name in the source DB is allowed.

### FR-003: Parallel, layout-preserving copy

#### Acceptance Criteria:

- [ ] Every planned object is server-side-copied to `{dest}/{relKey}`, preserving the relative layout (flat files and `key=value/` partition dirs both land correctly).
- [ ] Objects > 5 GiB are copied via multipart `UploadPartCopy`; smaller objects via single `CopyObject`.
- [ ] The copy is parallelized with a bounded worker pool; a transient S3 error retries (SFN/boto retry) before the item is marked `copy_failed`.
- [ ] No object data passes through the Lambda (server-side copy only).

---

## Data Model

```python
# per Map item (recipient) — carries the SPEC-090 plan + this recipient
{
  "recipient": { "kind": "user"|"space", "name": "...", "database": "...", "destBucket": "...", "destPrefix": "..." },
  "plan": { "tableDefinition": {...}, "objects": [...], "partitioned": bool },
  "outcome": { "status": "ok"|"conflict"|"unknown_target"|"copy_failed", "reason": "..." }  # set as it progresses
}
# tscommon.copy.copy_prefix(srcBucket, objects, destBucket, destPrefix, concurrency) — multipart-aware
```

## Implementation Phases

### Phase 1: Map + destination resolution + check-target-absent

- SFN `Map` (bounded concurrency, per-item Catch); resolve dest per kind; conflict guard (Glue GetTable + non-empty-prefix check); short-circuit invalid recipients.

### Phase 2: copy-objects (parallel + multipart)

- `tscommon.copy.copy_prefix` with bounded concurrency + multipart for large objects; per-recipient outcome recording; execution-role S3/Glue grants.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`tscommon.copy`, the Map/verb states).
