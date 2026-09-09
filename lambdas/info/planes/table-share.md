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
recipients is fine and together they are 50 TiB. **Read `docs/decisions/analytics.md` before changing any of
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

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

### `tscommon/config.py` — sizing the three share caps

**`SHARE_MAX_RECIPIENTS = 50`.** The disaster this prevents is not the fan-out — it is the
Map's **result**. Each item contributes a summary entry to `$.recipientResults`, and a failed
entry carries the raw Step Functions `{Error, Cause}` (PR #252 — the ASL decode that used to
shrink it raised an uncatchable `States.Runtime`, so the raw object is what makes the reason
recoverable at all). Measured against a real Cause from execution history: **~570 bytes per
failed recipient, ~1.2 KB with a verbose Athena `StateChangeReason`**. Step Functions caps a
state payload at 256 KB, and breaching it raises `States.DataLimitExceeded` **on the Map** —
which routes to the whole-request failure state and destroys every per-recipient outcome the
Map exists to preserve, turning a partial success into a total failure.

Measured, not guessed: at the bounded worst case (a maximum-length detail plus a deep stack)
100 recipients reach ~154 KB — under the limit, but the request object rides in the *same*
payload, so that margin is thinner than it looks. 50 lands at ~68 KB, 26% of the limit.
`test_the_whole_map_state_stays_under_the_payload_limit`
(`lambdas/control-plane-common/test_state_machines_cpcommon.py`) computes this from the
constants, so changing either without re-checking the other fails the build. The other half of the bound is
`cpcommon.athena` truncating the raw Athena reason: a cap on **count** alone cannot bound a
32 KB Cause, which breaches at **seven** recipients. It is also a sane product limit in its own
right — 1000 objects × 50 recipients is 50,000 `CopyObject` calls, and there was previously no
cap at all.

> **Amended (SPEC-161).** The product is now bounded directly by `SHARE_MAX_TRANSFER_ITEMS`
> (20,000), so `SHARE_MAX_RECIPIENTS` no longer carries that second job by implication — its own
> two bounds, the inline Map's state and the per-item error detail, are untouched by the scale
> work and the value stays **50**.

**`SHARE_MAX_DEFINITION_BYTES = 32 KiB`.** The last unbounded term on the Map's state. Moving
the object list to a pointer removed the big one, but `tableDefinition` still rides inline —
and it is **user-controlled**: it clones the source's columns (name/type/comment) and its Glue
table properties verbatim, and a user can set both from the query workspace. Measured with the
plan already by pointer, 50 recipients all failing:

| definition | state | % of 256 KB |
|---|---|---|
| 300 columns, no comments | 89 KB | 34% |
| 1,000 columns, no comments | 123 KB | 47% |
| 1,000 columns, 255-char comments | 393 KB | **150% — breach, after the pointer** |

32 KiB is generous — roughly 600 plain columns — and lands the worst case near 41%.

> **Superseded (SPEC-161).** Every word above is now historical, and the reason is worth keeping:
> **32 KiB was generous for plain columns and tight for commented ones.** A 100-column table with
> a 255-character comment per column serialises to about 32 KiB — an ordinary thing to want to
> share, sitting exactly on the boundary. The cap was doing two incompatible jobs at once, and a
> cap cannot: protect the payload, or decide how wide a table a user may share. The definition
> **travels by pointer** now (`definitionKey`), so the term is a digest path and the choice is
> gone. Measured after the move: an at-cap definition put back inline takes the guard peak from
> ~29% to **~55%** of the limit, which
> `test_the_whole_map_state_stays_under_the_payload_limit` now asserts so the pointer is
> demonstrated load-bearing rather than assumed tidy. **`SHARE_MAX_DEFINITION_BYTES` survives at
> 64 KiB bounding something else entirely** — Athena's query-string quota, **262,144 bytes and
> not adjustable**, because the definition renders into one `CREATE EXTERNAL TABLE`. Do not read
> it as a state bound.

**`SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES`.** Sized so a recipient Map item's parallel
server-side copy finishes comfortably inside copy-objects' 900s timeout (architecture §12).

> **Amended (SPEC-160).** That sizing rationale is now historical: the copy is a Distributed Map
> over batches, so no single invocation carries a recipient's whole table and the timeout no longer
> sets the ceiling. **The two values are unchanged anyway** — 160 changed the mechanism only, so it
> is provably behaviour-neutral, and SPEC-161 is where the ceiling moves. The two caps that are
> still load-bearing on the *state* — `SHARE_MAX_RECIPIENTS` and `SHARE_MAX_DEFINITION_BYTES` — are
> untouched by the restructure: the per-recipient array is still exactly one entry per recipient.

> **Superseded (SPEC-161) — the ceiling moved, and each cap now names a DIFFERENT limit.** They
> used to share one rationale (the copy verb's timeout) because one verb was the whole bound.
>
> **`SHARE_MAX_OBJECTS` = 20,000. Bound: `inspect-source`'s listing time.** `list_data_objects`
> pages at 1000 keys, so 20,000 objects is 20 `ListObjectsV2` round trips — one to two seconds of
> a 120-second budget — and the copy plan it writes is ~3.4 MB at ordinary Hive keys, ~21 MB at
> S3's worst-case 1024-byte ones, which is what inspect-source's 1024 MB is sized for.
>
> **`SHARE_MAX_TOTAL_BYTES` = 1 TiB. Bound: one copy of the SOURCE, and nothing more.** It caps
> what inspect-source lists and what the copy plan describes. **It does NOT bound the transfer**,
> and reading it as though it did is how the machine's `TimeoutSeconds` shipped unsatisfiable
> through two review rounds — see the entry below.
>
> **`SHARE_MAX_TRANSFER_BYTES` = 3 TiB (NEW). Bound: the state machine's `TimeoutSeconds`.** The
> manifest carries one item per (recipient, object) pair and **every item is a full copy**, so the
> Map moves `total_bytes × recipients`. This is the byte-axis twin of `SHARE_MAX_TRANSFER_ITEMS`,
> and the argument is verbatim the one that cap already made.
>
> **Two wrong models were tried before this number, and both read as safe.** First, sizing the
> timeout against `SHARE_MAX_TOTAL_BYTES` alone — 50 recipients × a 1 TiB source is **50 TiB**,
> 3.8 h at the conservative rate against a 3 h ceiling, with break-even at 8 recipients. Second,
> dividing by an **aggregate bandwidth** of 160 concurrent copies (`MAP_MAX_CONCURRENCY` ×
> `COPY_CONCURRENCY` × 25 MB/s = 4.0 GB/s), under which 16 TiB looked like 4,400 s.
>
> **The rate is a makespan.** `copy_batch` hands one WHOLE object to one worker and `copy_one`
> part-copies serially, so a batch whose bytes sit in one large object runs at **one** stream
> while seven idle — an ordinary mixed-size Parquet table, not a corner. The pessimistic
> denominator is `MAP_MAX_CONCURRENCY × rate` = **500 MB/s**, at which 16 TiB is 35,000 s. 3 TiB
> is ~6,600 s, and adding the finish Map (3,000 s) and the serial verbs (~720 s) the worst run is
> ~10,300 s inside the 10,800 s ceiling. All three terms are in the test, because each time a
> term was left out it stayed out for a whole review round.
>
> **`SHARE_MAX_OBJECT_BYTES` = 10 GiB (NEW). Bound: the copy verb's timeout, via the BATCH** — and
> that qualifier is the whole of it, because the first version of this cap got the granularity
> wrong. `ItemBatcher` batches by **COUNT, never by bytes**, so the unit that has to copy inside
> `copy-objects`' 900 seconds is `MAX_ITEMS_PER_BATCH` objects, not one. While the TOTAL cap was
> 20 GiB that bound was implicit — a batch could not exceed the whole table — and **raising the
> total to 1 TiB removed it with nothing replacing it**. A per-object cap alone does not restore
> it: at 50 items x 20 GiB the worst batch is **1000 GiB**, over 900 s even at an optimistic
> 100 MB/s per stream, so the child dies on the Lambda timeout, lands in `FAILED_n.json`, and the
> recipient is failed for a reason they cannot act on.
>
> **So `MAX_ITEMS_PER_BATCH` moves alongside it — to 8, which is `COPY_CONCURRENCY`.** And the
> quantity it is held against is a **makespan, not the batch's bytes**: `copy_batch` gives one
> whole object to one worker and `copy_one` part-copies serially, so a batch costs
> `ceil(items / COPY_CONCURRENCY)` ROUNDS of its slowest object. Setting the two equal makes that
> ceiling one, so a batch costs one object's time — **429 s** for 10 GiB at the conservative rate,
> inside two thirds of the 900 s timeout. At 10 items it was two rounds and **859 s**, 41 seconds
> from a hard timeout, while the bytes-over-bandwidth reading of the same numbers said 537 s.
>
> 10 GiB is chosen over a smaller per-object cap because it stays above S3's 5 GiB single-copy
> limit, so the multipart part-copy path stays reachable rather than becoming dead code. The price
> is more child executions on a many-small-files share; state transitions and Lambda invocations
> are both cheap and `MAP_MAX_CONCURRENCY` still bounds in-flight work.
> `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the makespan and
> `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality, so moving any of the
> three constants alone fails the build.
>
> **`SHARE_MAX_TRANSFER_ITEMS` = 20,000 (NEW). Bound: the manifest write and the collector's
> read-back**, which are the same volume in both directions. At S3's worst-case 1024-byte keys an
> item is ~2.3 KB, so 20,000 items is a ~46 MB manifest, and the Map Run export
> `collect-transfer-results` reads carries every batch's input again. **This is the cap the other
> two cannot express** — 20,000 objects is fine and 50 recipients is fine, and together they are a
> million manifest lines. It is enforced in `inspect-source` on the **requested** recipient count,
> before the guard Map, so an identical request cannot succeed or fail depending on who already
> holds a table of that name.
>
> **`build-transfer-manifest` and `collect-transfer-results` went 60 s/512 MB → 300 s/2048 MB**,
> because they *are* that third bound. Memory is also the CPU dial and this is JSON work, so it
> buys the timeout as much as the headroom.
> `test_the_manifest_verbs_are_sized_for_the_transfer_item_cap`
> (`lambdas/table-share-common/test_state_machine_table_share.py`) **computes** the worst-case
> volume from the cap and the same worst-case item the batch sizing uses, and holds the deployed
> memory above it. **It is a floor, not a tripwire, and the difference is measured:** the first
> item count it refuses is 38,207, so the cap can be raised by 91% without touching either verb.
> What it does catch is the verbs being shrunk — 1024 MB and the fleet default 512 MB are both
> refused — which is the direction a tidy-up moves them. Raising the cap is on the author.
>
> **The item cap equals the object cap, so the object cap is reachable only for a single-recipient
> share** — 500 objects can go to 40 recipients, and 500 to all 50 is refused at 25,000 items. A
> deliberate consequence of bounding the product; the refusal names both numbers.
>
> **Step Functions is nowhere near binding at any of this** (checked against the live quota pages,
> 2026-08-10): an `ItemReader` file may be **10 GB**, a Map Run **100,000,000** items, and a
> Standard execution runs a **year**. Our own Lambdas are the ceiling, which is why every bound
> above names one.
