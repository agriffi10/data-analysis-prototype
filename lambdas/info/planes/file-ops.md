# File operations — control plane

Move, copy and delete inside a user's own space and between spaces. The plane exists because S3 is
not a filesystem: every move is `CopyObject` + `DeleteObject`, folder operations are recursive and
**non-atomic**, and versioning is off — which is what makes a failure between those two steps
unrecoverable.

These were the last bulk data operations this product performed in the **browser**. `copyFolder`
issued one `CopyObject` per object in a strictly sequential loop from the user's laptop, `moveFolder`
did that and then deleted, and closing the tab left the operation half-done with no record it had
started.

**ONE machine serves all three operations.** They share the request contract, the authorization
question, the lock and the failure vocabulary; a selection routes the same way whichever verb the
user pressed. What differs is only whether a destination is derived.

**A selection stays synchronous if and only if it is exactly ONE FILE.** A single folder — a *rename*
included — is enqueued, because a rename is one `CopyObject` per contained object.

**The envelope is FLAT**, with `actor` the raw ID token at the top level, for the DLQ drain's benefit.
The copy/move-only fields (`destination`, `onConflict`, `submittedAt`) are **rejected for a delete**
and emitted as explicit nulls. That is why `NeedsDestinationGuard` branches on `$.operation`: ASL's
`IsPresent` is TRUE for a field that is present and null.

**There is NO `Validated` Pass**, unlike every neighbour, and its absence is load-bearing: a Pass
reading a path a delete does not carry raises an uncatchable `States.Runtime`, so the very first
delete would have died before the notifier. Read that rule before adding a `Pass` here.

## The machine

`infra/modules/file-ops/state-machine.asl.json.tftpl`

`ValidateAuthorize → AcquireLock ⇄ WaitForLock → ChooseOperation → InspectSource →
NeedsDestinationGuard → CheckDestinations → CheckDestinationsAgain → BuildTransferManifest →
TransferObjects (Map) → CollectTransferResults → NeedsSourceDeletion → DeleteSource →
FinaliseOutcomes → ReleaseLock → NotifyOutcomes`

`ReleaseLockOnGiveUp` and `ReleaseLockOnFailure` are the other two arms — every terminal path
releases; there are three release states because one ASL state has one `Next`. The failure path is
`ValidateFailureSeed`/`RequestFailureSeed`/`GiveUpFailureSeed → RecordFailure → NotifyFailure →
Failed`.

**Every Task taken under the lock carries a `Catch`.** A Task without one has no edge to any
terminal, so the graph walk that proves no path reaches a terminal *holding* the lock stays green
while the space wedges until the stale steal.

**A per-SPACE lock, whose loser WAITS.** FIFO orders delivery and the Pipe starts the machine
`FIRE_AND_FORGET`, so delivery is ordered and execution is not — and this plane's loser would delete
objects a concurrent move had already relocated. `cpcommon.lock` under ETag CAS, held by the
execution ARN, released by overwriting, stolen only when stale.

## The plan

`{admin_bucket}/file-ops/{requestId}/plan.json`, written by inspect-source and read back by
everything after it. Only its key and the counts ride on the state, because at
`FILE_OPS_MAX_OBJECTS` the object list is tens of megabytes against a 256 KB payload limit.

A prefix-scoped lifecycle rule expires it (`modules/analytics/s3.tf`) and **cannot reach
`locks/file-ops/`** — an S3 lifecycle prefix anchors at the start of the key, and a lock that is
released by *overwriting* must never be expired into absence.

```
{ requestId, operation, submittedAt, onConflict, actor, executionArn,
  source: {bucket, root}, destination: {bucket, prefix} | null,
  items: [ { itemKey, label, kind, targetName, objectCount, totalBytes,
             objects: [ {srcBucket, srcKey, relKey, size, etag, destBucket?, destKey?} ] } ],
  itemCount, objectCount, totalBytes }
```

`requestId`, `submittedAt` and `onConflict` are on the plan because the guard's overwrite predicate
reads them from there and **not** from the state — reading them off the state is the substitution
`plan_superseded` exists to catch. `executionArn` is what makes the reused-id guard retry-safe: every
Task retries three times, so refusing any occupied prefix would refuse the request the verb had
itself just planned. `etag` rides because `ListObjectsV2` already returned it, and it is the field a
later conditional delete turns on.

## The notification

**It is the completion channel, and one producer says it.** `NotifyOutcomes` is the last state and it
sits **after** the release — before it, the space would be held for as long as the messages take to
write — and **both** of `ReleaseLock`'s edges reach it, because a release that exhausts its `Retry`
still has to notify, or a completed operation tells the user nothing.

It cannot fail the run (`ResultPath: null`, a `Catch` to the terminal, no `@notifies_on_failure`): by
the time it runs, a `move` has already deleted its sources. It is also the one Task whose catch
reaches a terminal rather than a release — the lock is free, and a release is an *overwrite*, so a
second one would clobber whichever execution had since acquired that space.

**ONE message per run, not per item**, carrying a link and an optional structured `payload` on the
notification row: `requestId` always (a reader settles its in-flight record by matching it, and a
clean run has nothing to re-submit), plus what a re-submit needs — the operation, both spaces, the
destination prefix and the **bounded** conflicted items. Bounded by **bytes as well as count**,
because one conflicted item is around 200 bytes at ordinary key lengths and around 12,000 at this
plane's caps.

The link is the destination when anything landed, the source otherwise, and for a `delete` the common
folder of the items' **parents**. Its prefix is **percent-encoded**, which no other plane's link
needs, because this is the only one built from an arbitrary user-controlled key.

## What the role may do

**The execution role reads both data buckets and writes to neither** — `ListBucket`,
`GetBucketLocation` and `GetObject`, with an explicit `Deny` on every write verb, so the transfer
spec has to delete a statement by name rather than widen an Allow. Its lock and plan prefixes in the
admin bucket are the only places it may write, and it is on the user-space bucket policy's allowlist.

## The fences

- **The lock is per SPACE and its loser WAITS** (`LockAcquired → WaitForLock`), rather than being
  refused. A cross-space operation takes **both** locks in digest order or neither.
- **The space root is refused as an item.**
- **The collision unit is the derived destination key**, not the source name, and a **403 counts as
  occupied**.
- **The deletion takes confirmed plan keys**, never a prefix listing — a listing orphans an
  uncopied object.
- **A duplicate is `(kind, key)`, never the key alone.** One key can arrive as both a file and a
  folder; collapsing on the key ships a zero-byte placeholder and reports success.
- `focommon.protected` refuses the portal's own folders server-side — the first plane to do so.
- The browser's async switchover **consults the routing predicate once**, above every submission
  point, in one dispatcher; the in-flight record is session-scoped and settles on a notification
  carrying its request id.

## The layer — `file-ops-common/focommon/`

| Module | Holds |
|---|---|
| `authz` | space authorization |
| `config` | domain configuration |
| `delete` | batched deletion, scoped **per item** — a whole-list refusal on a move would leave everything copied and nothing deleted |
| `lock` | the per-space lock |
| `messages` | user-facing outcome wording |
| `notify` | best-effort failure notifications |
| `outcomes` | the per-item outcome vocabulary every verb reads and extends |
| `paths` | key containment and the derived destination |
| `plan` | the copy plan, passed by pointer |
| `protected` | the portal's own folders |

`focommon` deliberately keeps its own copy of `item_name` rather than importing `fscommon.paths` —
two domain layers are packaged separately, so the import would merge them to save nine lines. That
exemption, and the rules it sits beside, are asserted in
`file-ops-common/test_layer_discipline_focommon.py`.

The verbs are listed in [`../INDEX.md`](../INDEX.md).
