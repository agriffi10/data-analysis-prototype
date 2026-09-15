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
carries the raw ID token only on a message enqueued before the API stopped sending one, and the
verb never reads it — both are non-empty strings, so a fallback resolves a JWT as a username. It
stays in the allowed-field set, or a pre-cutover message — a flat token and no block — becomes
`malformed_event` rather than `unauthorized`.
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

**A whole-request failure carries `{requestId}` and nothing else**, from every Lambda of this
plane's own that sends one. A verb's decorator reads it off the running state. The validator builds
its emitter's event by hand, so it names the id there. Both doors of `notify-failure` read it through
`observability.request_id_of`, because a seed that replaced the state nulls it and only the
forwarded request under `raw` still carries it. The browser reads a row with an id and no
`operation` as a refusal, and settles the card on it. The shared DLQ drain writes the same
`{requestId}` for a request that dead-letters, so that request's card settles as a refusal too.

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

## What the cap chain reads, and what it only computes

`test_config_focommon` holds almost every file-ops number, and its guards divide by **what they
open**. Of 31, **seventeen** reach outside the package: **thirteen** read verb rows or scalars out of
`infra/modules/file-ops/locals.tf` (one of those also reads the state machine's ASL template, to hold
the twice-swept destination guard charged twice); one globs the verb directories for
`plan.load(`/`plan.write(` and holds the derived plan-holder set **equal** to the one the memory
budget measures; one reads the browser's `fileOps.service.ts`; one reads botocore's real
`max_pool_connections`; and one reads `MAX_PAYLOAD_BYTES` out of the notifications writer. **Those
are the ones a change elsewhere can redden.**

The other **fourteen** compute a cap against a modelled worst case — the escaped Pipe record, the
state after the transfer, the inbox row — and can only be broken by moving a constant in
`focommon/config.py`. That is the split to hold in mind before trusting one: a guard that opens
nothing cannot notice Terraform moving underneath it.

**Not quite every number**: `PLAN_PREFIX` is held to its Terraform local and the admin bucket's
lifecycle rule in `lambdas/test_file_ops_admin_list_grant.py`, not here.

**What none of them covers**: `notifications_writer`'s ceiling is read as the two operands it is
written as, so a rewrite of that expression fails the read rather than the comparison — deliberately,
because a reader that evaluated it would accept a form this should be failing on.

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

**The ARCHIVE WRITE-LOCK rule is held to the POLICY, never to another copy.** It exists in three
implementations of the bucket policies' asymmetric Deny — root-anchored in a personal space,
any-depth in a shared one: `isWriteLockedPrefix` in the browser, `apicommon.protected.is_write_locked`,
and this package's `protected._is_at_or_below`. Each is run against a matcher built from the Deny it
mirrors, and none is compared to another, which is deliberately the stronger claim: two copies can
agree with each other and both be wrong about the policy. (`focommon.delete` and `arcommon.plan`
carry a fourth and fifth archive refusal, but those deliberately mirror the EXECUTION roles'
strictly-any-depth Deny instead, and say so in their own docstrings.)

What each side is tied to, and what each therefore cannot see:

| Guard | Reads the policy for | Blind to |
|---|---|---|
| `archiveWriteLock.test.ts` | the Resource STRINGS — it turns each Sid's `Resource` into a key matcher (`*` matching `/`, which is the trap) and runs the browser predicate over a key table | a change to `Effect` or `Action` |
| `test_archive_write_lock_mirrors_iam.py` | the same Resource strings **and** the `Effect`, over ONE key table run against BOTH Python predicates | everything else in the statement — `Action`, `Condition`, `NotAction` — and everything outside it |
| `test_archive_bucket_isolation.py` | the `Effect`, the exact `Action` set, and that the `Resource` ends `/archive/*` — for the two PRIMARY Sids only | any change to the anchor that preserves that suffix |
| `test_spaces_and_protection.py`, `test_protected_focommon.py` | nothing — hand-written expectations whose docstrings narrate the Deny. They pin each predicate's SHAPE, which is still worth having | everything about the policy |

**Measured rather than argued.** Widening the personal Deny's anchor to `${bucket_arn}/*/archive/*` —
still parses, still ends `/archive/*`, now means any user's archive rather than the caller's own —
once reddened `archiveWriteLock.test.ts` alone and left every Python test of a write-lock PREDICATE
green; four Python template tests reddened, but they pin the anchor's text, not either predicate's
answer. It now reddens ten rows of `test_archive_write_lock_mirrors_iam.py` as well. Flipping that
Sid's `Effect` to `Allow` reddens the new guard and `test_archive_bucket_isolation.py`, and leaves
the browser test fully green.

**Writing that guard is what found the divergence between the two Python copies.**
`_is_at_or_below` drops a file key's final segment before scanning for the folder name, because a
file *called* `archive` is not a file *inside* one; `is_write_locked` did not, so the API answered
403 for `finance/reports/archive` — a key the shared Deny's `*/archive/*` does not match. Neither
copy's own suite could see it: each was written from the same prose, and prose is what they agreed
with.

**What no guard here reads is the document AROUND the statement**, and two changes exploit that.
Wrapping a Deny in a balanced `%{ if … }` directive deletes it from the RENDERED policy while every
guard in the table above still reads it as text and passes. And the policy `Version` is asserted
nowhere in the repo: under `2008-10-17` IAM stops expanding policy variables, so
`${aws:PrincipalTag/username}` becomes a literal that matches nothing — which is the premise the
key matcher's whole substitution rests on. A third has the same shape: every guard reads the
`.tftpl` FILE, and none reads the `aws_iam_role_policy` that attaches it, so deleting that
attachment leaves each of them green with no Deny deployed at all. All three were measured. None is
ranked urgent — the first two also break `UserPrefixObjects` and the third breaks the shared-space
plane loudly, so each fails in the direction where something stops working rather than quietly
opening — but a guard that reads statements can never see any of them, and saying so is the point
of this table.

The `Action` sets, by contrast, ARE covered — both surviving statements, by two guards.
`test_archive_bucket_isolation.py` pins the exact set on each bucket's receipt Deny.
`test_portal_role_preservation.py` reaches the same two from the other side, comparing each against
the depth-one statement it replaced, read from the baseline commit. So the set cannot be narrowed in
one place and left alone in the other, and dropping `s3:PutObject` from either Deny reddens both
guards — measured on BOTH, which is the point: the first draft of this paragraph measured the
personal half and wrote "either", and the shared half then had one guard, not two. The preservation
test's shared branch gained its action comparison for that reason.

There were four statements and three guards until the narrowing: each folder had a depth-one home
and a `…SystemSettings` sibling, and a third guard held the shared sibling's actions equal to its
twin's. The depth-one halves are retired, so that comparison has no second side left and the guard
that made it was retired with them.

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
