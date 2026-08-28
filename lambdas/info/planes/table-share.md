# Table share — control plane

Shares a catalog table with other users: a **one-time snapshot push**, with no consent step and no
sync. The source table's data files are copied into each recipient's `shared_tables/{tableName}/`
and a table is created over them in the recipient's own Glue database.

## The machine

`infra/modules/table-share/state-machine.asl.json.tftpl`

`ValidateAuthorize → InspectSource → GuardRecipients (Map) → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → FinishRecipients (Map) → ShapeSummary`

Three Maps: guard each recipient, move the bytes, then create each recipient's table. `InspectSource`
clones the definition, lists the objects and enforces every cap. The middle Map is a **top-level
Distributed Map** over a `(recipient × object)` JSONL manifest, with batched copy-objects,
`STANDARD` children, `ToleratedFailurePercentage: 100` and a `ResultWriter` export.

One recipient's failure never aborts its siblings — the guard by its per-item `Catch`, the copy by
attribution after the fact. A conflict (the name exists, or the target prefix is non-empty) fails
**that recipient only**, and nothing is overwritten. FIFO `MessageGroupId` is the source
`database.table`, so a heavy copy never overlaps itself.

## What it accepts

**Sources:** flat or projection-partitioned base `EXTERNAL_TABLE`s. Views,
catalog-registered-partition tables, non-external tables and unresolvable `LOCATION`s are rejected;
copying partition metadata is deferred.

**Recipients:** a `user` must exist in the User Pool. A `space` is **any space by name** — the sender
need not be a member, which is deliberate and recorded, because the execution role does the write.
The sender must have access to the **source**: their own database, or active membership of the
source space.

## The fences

- **The share CLONES the source definition, it never re-infers it.** Columns, SerDe, `TableType`,
  partition keys and `TBLPROPERTIES` (projection props included) are reused verbatim with only
  `LOCATION` repointed — format-agnostic, exact schema, no `MSCK`. The recipient's table is the
  sender's table, not a fresh inference over the copied bytes.
- **It pushes without consent.** There is no accept step; the recipient finds the table already there.
- **Every DDL literal goes through `literal()`**, `TBLPROPERTIES` and `LOCATION` included, and the
  escapers split on two axes that are easy to conflate. For *values*: `cpcommon.ddl.literal`
  backslash-escapes (Hive/DDL) while `cpcommon.sql._literal_dml` doubles the quote (Trino/DML). For
  *identifiers*: `sqlDdlIdentifier` and `ddl.quote` are Hive (inner backtick doubled), `sqlIdentifier`
  is Trino. **The wrong one fails silently, as a predicate that never matches** — and a shared
  space's name is format-checked nowhere server-side.
- **A table's `LOCATION` is read recursively**, so the space root is not a data folder.
- **Per-recipient attribution is a verb, not a Map item.** The fan-out is over `(recipient × object)`
  pairs, so `collect-transfer-results` reads the Map Run's export and decides who gets a table:
  **one failed item means no table for that recipient**. It reads **both** `SUCCEEDED_n.json` (a
  batch reports per-item failures and still succeeds) and `FAILED_n`/`PENDING_n` (whole-batch
  failures, attributed from the child's input). A record whose payload Step Functions omitted is
  **unattributable and fails the whole request**, never "no failures found". It is also where a copy
  failure is notified from, because the batch verb has no recipient to name.
- **Notifications:** the sender hears every per-recipient outcome. On success the recipient is told
  too — a user directly, a space through its **owner only**, never its members. Failures notify the
  sender alone.

## Why the copy is a Distributed Map, and not S3 Batch Operations

The copy is a top-level Step Functions Distributed Map over a flat `(recipient × object)` JSONL
manifest in the admin bucket, batched into parallel server-side `CopyObject` (multipart above 5 GiB),
preserving the key layout. It is **not** one Lambda per recipient.

**S3 Batch Operations cannot do this job — do not re-propose it.** Batch Ops cannot rewrite a key:
`TargetKeyPrefix` prepends to the *full* source key, so a job cannot produce
`bob/shared_tables/sales/…` from `alice/tables/sales/…`. It also caps objects at 5 GB, where this
path already handles more through `UploadPartCopy`. The refusal is a property of the API, not a
preference. The copy code itself lives in `cpcommon.transfer`.

## The caps

Every one is a **whole-request terminal in `inspect-source`**, raised before either artifact is
written, and every one is **computed by a test** from the constants rather than asserted as a number.

| constant | value | what sizes it |
|---|---|---|
| `SHARE_MAX_OBJECTS` | 20,000 | `inspect-source`'s listing time (20 `ListObjectsV2` pages) |
| `SHARE_MAX_TOTAL_BYTES` | 1 TiB | **one copy of the source** — says nothing about the transfer |
| `SHARE_MAX_OBJECT_BYTES` | 10 GiB | a batch's **makespan** against `copy-objects`' 900 s |
| `SHARE_MAX_TRANSFER_ITEMS` | 20,000 | `recipients × objects` — the manifest write plus the collector's read-back |
| `SHARE_MAX_TRANSFER_BYTES` | 3 TiB | `recipients × bytes` — the state machine's `TimeoutSeconds` |
| `SHARE_MAX_RECIPIENTS` | 50 | the inline Map's state plus per-item error detail |
| `SHARE_MAX_DEFINITION_BYTES` | 64 KiB | **Athena's 262,144-byte query-string quota**, not the state payload |
| `MAX_ITEMS_PER_BATCH` | 8 | `= COPY_CONCURRENCY`, so a batch is exactly one round of the pool |
| `TimeoutSeconds` | 10,800 | `SHARE_MAX_TRANSFER_BYTES` at a makespan rate, minus both Maps and the serial verbs |

**The two product caps exist because the per-source caps cannot express them.** Every manifest item
is a full copy, so both what the Map lists and what it moves scale with the recipient count. 20,000
objects is fine and 50 recipients is fine and together they are a million lines; 1 TiB is fine and 50
recipients is fine and together they are 50 TiB. **Read `docs/decisions.md` before changing any of
these** — five review rounds found four bounds measured against the wrong quantity, and the tests are
what hold the models now.

The cloned definition **travels by pointer** (`definitionKey` →
`table-share/{hash}/definition.json`), which is why its cap bounds Athena rather than the payload.
The `TimeoutSeconds` **cannot itself reach `NotifyFailure`** — AWS catchers do not cover top-level
execution failures — so it ships with an **EventBridge `TIMED_OUT` rule** invoking the same verb
through a second door.

The 256 KB state cap bites twice: the copy plan rides as an S3 pointer, because inline the Map's
`ItemSelector` put the state at 101% of the cap; and the recipient cap exists because each failed Map
item carries raw `{Error, Cause}`, with `cpcommon.errors.bounded_detail` truncation as the other half
of the bound.

## The admin-bucket key layout, and what the digest is NOT

Three levels, only the first two ours:

```
table-share/{digest}/copy-plan.json                              ← the SOURCE's file list
table-share/{digest}/{executionName}/transfer-manifest.jsonl     ← one RUN's (recipient × object) items
table-share/{digest}/{executionName}/results/{mapRunId}/…        ← Step Functions' ResultWriter export
```

**The digest names the copy plan, not a share request.** It is a SHA-256 of
`actor + source database + source table + result name` and **deliberately excludes recipients**: the
plan is the source object list, identical whoever receives it, and content-addressing is what makes
an `inspect-source` retry rewrite the same object instead of orphaning a second one. So **two shares
of the same table to different people share a root** and differ one level down, where the
recipient-dependent manifest lives — which is exactly the split needed, since a manifest's lines
depend on which recipients the guard accepted *at that moment*. It reads as one share swallowing
another and is not; verified 2026-08-10 against two real runs.

The bucket is **not readable by eye** — go from the execution's state output (or the Map state's
`ResultWriterDetails`) to the keys, never by browsing.

Recorded improvement, **not built**: the nesting puts run-scoped artifacts under a plan-scoped name,
and a `plans/{digest}/` + `runs/{execution}/` split would separate the two identities. Neither the
`table-share/*` IAM grant nor the `table-share/` lifecycle rule would change.

## The layer — `table-share-common/tscommon/`

| Module | Holds |
|---|---|
| `cognito` | user pool lookups for recipient validation |
| `config` | domain configuration |
| `copy_plan` | the copy plan, passed by pointer |
| `ddl` | renders the recipient `CREATE EXTERNAL TABLE` from the cloned source definition |
| `glue` | Glue catalog reads for the source |
| `messages` | user-facing outcome wording |
| `notify` | best-effort outcome notifications |

The verbs are listed in [`../INDEX.md`](../INDEX.md).
