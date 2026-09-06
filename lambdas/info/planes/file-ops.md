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

**The trusted actor is the nested `identity` block** the API stamps; the flat top-level `actor`
still carries the raw ID token until the API stops sending one, and the verb never reads it — both
are non-empty strings, so a fallback resolves a JWT as a username. It stays in the allowed-field
set until then, or a pre-cutover message becomes `malformed_event` rather than `unauthorized`.
The copy/move-only fields (`destination`, `onConflict`, `submittedAt`) are **rejected for a delete**
and emitted as explicit nulls. That is why `NeedsDestinationGuard` branches on `$.operation`: ASL's
`IsPresent` is TRUE for a field that is present and null.

**There is NO `Validated` Pass**, unlike every neighbour, and its absence is load-bearing: a Pass
reading a path a delete does not carry raises an uncatchable `States.Runtime`, so the very first
delete would have died before the notifier. Read that rule before adding a `Pass` here.

## The machine

`infra/modules/file-ops/state-machine.asl.json.tftpl`

`ValidateAuthorize → StampExecution → AcquireLock ⇄ WaitForLock → ChooseOperation → InspectSource →
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

## What holds the browser's copy of a rule to this plane's

Two rules are duplicated between the runtimes, and they are held together by different mechanisms
with different strengths. Reading them as one is the mistake this section exists to prevent.

**The LISTS are compared directly.** `protectedFoldersMirror.test.ts` reads `focommon/config.py` as
text, resolves each member to the string it denotes — the module mixes quoted literals, owner
attributes and local aliases, so this needs a three-shape resolver — and holds
`PICKER_LOCKED_FOLDERS` and `UNDELETABLE_ROOT_FOLDERS` equal as sets against the browser's. Each
tree also pins its own membership to spelled-out literals (`test_config_focommon.py`,
`fileBrowserPure.test.ts`), so an edit to one tree alone reddens that tree first. What the mirror
uniquely catches is a change made CONSISTENTLY within one tree.

**The ARCHIVE WRITE-LOCK rule is not compared at all.** It exists in three implementations of the
bucket policies' asymmetric Deny — root-anchored in a personal space, any-depth in a shared one:
`isWriteLockedPrefix` in the browser, `apicommon.protected.is_write_locked`, and this package's
`protected._is_at_or_below`. Nothing holds any of the three against another. (`focommon.delete` and
`arcommon.plan` carry a fourth and fifth archive refusal, but those deliberately mirror the
EXECUTION roles' strictly-any-depth Deny instead, and say so in their own docstrings.)

What each side is tied to, and what each therefore cannot see:

| Guard | Reads the policy for | Blind to |
|---|---|---|
| `archiveWriteLock.test.ts` | the Resource STRINGS — it turns each Sid's `Resource` into a key matcher (`*` matching `/`, which is the trap) and runs the browser predicate over a key table | a change to `Effect` or `Action` |
| `test_archive_bucket_isolation.py` | the `Effect`, the exact `Action` set, and that the `Resource` ends `/archive/*` | any change to the anchor that preserves that suffix |
| `test_spaces_and_protection.py`, `test_protected_focommon.py` | nothing — hand-written expectations whose docstrings narrate the Deny | everything about the policy |

**Measured rather than argued, three ways.** Widening the personal Deny's anchor to
`${bucket_arn}/*/archive/*` — still parses, still ends `/archive/*`, now means any user's archive
rather than the caller's own — reddens `archiveWriteLock.test.ts` and leaves every Python test of a
write-lock PREDICATE green. Four Python template tests do redden, but they pin the anchor's text,
not either predicate's answer. Flipping that Sid's `Effect` to `Allow` inverts it: the browser test
stays fully green and `test_archive_bucket_isolation.py` catches it.

So the gap is specific: **no Python test connects a write-lock predicate to what the policy means.**
Closing it is the browser test's shape applied to the two Python copies, and it is owed rather than
done.

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
the import would merge two domain layers to save nine lines. That was once enforced by the
packaging, which shipped them separately; one image can resolve both, so the separation now stands
as a code rule and nothing else. That exemption, and the rules it sits beside, are asserted in
`file-ops-common/test_layer_discipline_focommon.py`.

The verbs are listed in [`../INDEX.md`](../INDEX.md).
