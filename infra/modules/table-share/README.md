# `table-share` — the share-a-table control plane

The standard control-plane shape — see [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md)
for the files, roles and traps every plane shares. What follows is what is distinct here.

`validate-authorize → inspect-source → GuardRecipients (Map) → build-transfer-manifest →
TransferObjects (Distributed Map) → collect-transfer-results → FinishRecipients (Map)`

Three Maps: guard each recipient, move the bytes in batches, then create each recipient's table.
Each per-recipient Map has a **per-item Catch — one recipient's failure never aborts its siblings**.

The Lambda side is [`lambdas/info/planes/table-share.md`](../../../lambdas/info/planes/table-share.md).

## ⚠ The Distributed Map's permissions belong to the STATE MACHINE role

AWS is explicit: **the state machine role** invokes `StartExecution` for each child workflow and
reads the `ItemReader` object and writes the `ResultWriter` export. So the manifest read and the
results write belong in `sfn-permissions.json.tftpl`, beside `states:StartExecution` — **not** in
`execution.json.tftpl`.

**That misplacement renders green, applies green, passes the policy-render test, and fails on the
first real share with `AccessDenied` at the `ItemReader`.**

`StopExecution` is **not** granted: nothing here stops a child, and `StartExecution` +
`DescribeExecution` is the documented least-privilege pair.

The `ResultWriter` bucket is the **admin** bucket — a module input of this account's stack — so the
same-account/same-Region requirement (a cross-account or cross-Region export fails the execution with
`States.ResultWriterFailed`) holds **by construction rather than by assertion**.

## The copy plan travels by pointer, and the admin bucket is the right home

`inspect-source` **writes** the object list to `{admin_bucket}/table-share/{requestId}/` and passes a
**key** onward; `copy-objects` reads it.

The list used to ride **inline** on the Step Functions state, and **the Map's `ItemSelector` copies
the whole state into every item** — at the then-shipped caps (1000 objects, ordinary Hive keys) that
put the Map's output state at **95% of the 256 KB payload limit**, where `States.DataLimitExceeded`
fires **on the Map** and destroys every per-recipient outcome the Map exists to preserve. Same fix and
same reason as the data-quality manifest.

**The admin bucket, not a user space:** the SPA never browses it, so the plan needs no hidden-folder
convention, and **a user cannot delete it out from under a running execution** (they *do* hold
`s3:DeleteObject` in their own space). No delete is granted here either —
`analytics/s3.tf`'s `expire-table-share-copy-plans` lifecycle rule expires it.

**Rationale goes in the `.tf`, never the `.tftpl`.** IAM rejects a `"//"` comment key inside a
statement — `Policy input list item 1 has invalid content`, verified with `simulate_custom_policy`.

## `MessageGroupId` is the source `database.table`, and content dedup is OFF

Repeated shares of the **same** source serialize strictly one-at-a-time, so a heavy copy never
overlaps itself; shares of different sources run in parallel.

**`content_based_deduplication` is off here, unlike the table-builder queue.** The producer sends an
explicit `MessageDeduplicationId = requestId` as the double-submit guard, and **two byte-identical
share requests a user genuinely repeats** — a re-share after deleting the copy — **must not be
silently absorbed** by a 5-minute content-dedup window.

## Two sizing numbers, and both are computed

**The Distributed Map's batch size equals `COPY_CONCURRENCY` (8) on purpose.** `copy_batch` gives one
**whole** object to each worker and `copy_one` part-copies serially, so a batch costs
`ceil(items/workers)` rounds of its **slowest** object — **a makespan, not bytes over a bandwidth**.
At 8 that ceiling is one round, so a batch costs one object's time. **At 10 it was two rounds and
859 s against a 900 s Lambda timeout.**

Terraform cannot import Python, so these are literals fed into the ASL and
`cpcommon/transfer/config.py` holds the same two for the batch verb. **A test asserts the pair still
match** — two homes for one number is how a batch quietly grows past the limit it was sized against.

## `TimeoutSeconds` is 3 hours, and the arithmetic corrected itself twice

Without it a Standard workflow's ceiling is Step Functions' own default of **one year**, so a wedged
run simply never ends.

**The arithmetic is `SHARE_MAX_TRANSFER_BYTES` (3 TiB), NOT `SHARE_MAX_TOTAL_BYTES`** — and that
distinction is the whole of it, missed by two review rounds. The manifest carries one item per
(recipient, object) pair and every item is a full copy, so **the Map moves the source once per
recipient**. Sized against the 1 TiB source cap alone, the number was short by a factor of
`SHARE_MAX_RECIPIENTS`.

**The denominator is a makespan, not an aggregate bandwidth**, and that correction cost a fourth
round. 160 concurrent copies (`transfer_map_max_concurrency × COPY_CONCURRENCY`) is the rate only
when every batch holds eight comparable objects; **a batch dominated by one large object runs at one
stream while seven idle** — an ordinary mixed-size Parquet table, not a corner. The pessimistic rate
is therefore `transfer_map_max_concurrency × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s, under
which 3 TiB is ~6,600 s. Add the finish Map's
`ceil(SHARE_MAX_RECIPIENTS / MaxConcurrency 5) × create-table 300 s` = 3,000 s and ~720 s of serial
verbs, and the worst run is ~10,300 s — inside the ceiling.

**A test computes all of it.** The hard-coded floor that stood here first, and then the aggregate
reading that replaced it, **each hid a mismatch for a full round**.

It is **deliberately not longer**: the timeout is how fast a wedged share becomes a notification, so
the margin is bought against the sender's silence, not for free.

## The timed-out run's only route to a notification

A top-level `TimeoutSeconds` expiry **terminates the execution outright**. Catchers cover Task,
Parallel and Map states but **not top-level execution failures**, so the machine's own
`RecordFailure → NotifyFailure` path is unreachable on this one failure and the sender would be told
nothing at all — **the exact silence the failure path exists to close**. An EventBridge `TIMED_OUT`
rule is the documented remedy.

**`TIMED_OUT` only, never `FAILED`.** Every other whole-request failure already reaches
`NotifyFailure` through a Catch, so matching `FAILED` would send a second notification for every one
of them.

`notify-failure` is **60 s here rather than 15 s**, because that second door does strictly more work
than the ASL one: a cold-start JWKS fetch over the network plus a JWT verify before the send, since
the sender has to come from the token in the timed-out execution's own input. 15 s was sized for a
decode and a send. The DLQ drain, which does the same verify, is at 60 s for the same reason.

## Why three verbs are sized above 60 s / 512 MB

- **`inspect-source`** lists the objects and holds the whole copy plan in memory before writing it.
  `SHARE_MAX_OBJECTS` went 1,000 → 20,000, and at S3's worst-case 1024-byte keys that plan is ~21 MB
  serialised (~3.4 MB at ordinary Hive keys), with the in-memory list of dicts several times either.
  **It fit at 512 MB** — but every other cap on this plane reasons from the worst case rather than
  the typical one.
- **`build-transfer-manifest` and `collect-transfer-results`** are the two verbs either side of the
  Distributed Map, and **they are the binding constraint on `SHARE_MAX_TRANSFER_ITEMS`**. They handle
  the same volume in opposite directions: at worst-case keys a transfer item is ~2.3 KB, so 20,000
  items is a ~46 MB manifest to build and serialise, and the Map Run export carries every batch's
  input back again. **Parsing that at 512 MB is where it would have died first.** The memory is also
  the CPU dial — a 2048 MB function gets ~4× the CPU of a 512 MB one, and this is JSON work, so it
  buys the timeout as much as the headroom.

## Module names carry the `table_share_` prefix

So they cannot collide with the table-builder's identically-named verbs on `sys.modules` under one
`pytest lambdas/` process — the `tbcommon`-package lesson, applied to verb modules.
