# `file-send` — the send-files-to-someone control plane

The standard control-plane shape — see [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md)
for the files, roles and traps every plane shares. What follows is what is distinct here.

`validate-authorize → inspect-source → GuardRecipients (Map) → build-transfer-manifest →
TransferObjects (Distributed Map) → collect-transfer-results → notify`

Seven verbs: the front door, the source resolution, and the transfer's guard, manifest, batch copy,
attribution and outcome. **Only the copy runs inside the Distributed Map**; the guard runs per
recipient in an inline Map, and the rest once per request.

The Lambda side is [`lambdas/info/planes/file-send.md`](../../../lambdas/info/planes/file-send.md).

## Its own plane, not a mode of table share

The two features share an **algorithm** (`cpcommon.transfer`) and nothing else — different request
contract, different authorization question, different failure vocabulary. Folding them together would
put **one queue and one DLQ under two unrelated user features**, and **a malformed send would
dead-letter someone's table share**.

Its DLQ is registered with the drain sweep, so a dead-lettered send becomes a user notification
rather than silence.

## ⚠ The source grants are bucket-wide, and the isolation is not in them

A per-user condition **is not expressible here**: the sender is a runtime value from a verified
token, not a principal tag on this role — **the role is the privileged path, which is the whole
reason the plane exists**.

The isolation is `fscommon.authz` + `fscommon.paths`, applied **before any listing and re-applied to
every key the listing returns**, which is why those two modules carry the heaviest tests on this
plane.

**The only write into a user's space is under `shared_files/`.** The copy needs `PutObject` plus the
two multipart actions an object over S3's 5 GiB single-copy limit takes, scoped to
`*/shared_files/*` in both data buckets — so this role can write into an inbox and **nowhere else in
anybody's prefix**. It mirrors table-share's `*/shared_tables/*` grant one for one, which is the
point: **two planes writing into user space under one pattern is reviewable, two patterns is not**.

**`NoDataObjectDelete` is a Deny present from the first apply.** A send is a **copy** — it never
deletes the sender's copy and never overwrites at the destination — so nothing here will ever need
`s3:DeleteObject`. Writing the Deny early makes that an **enforced property instead of an
intention**, and costs nothing. It matters because **this role is on the user-space bucket's
principal allowlist**: a bug in a later verb would be deleting some other user's data.

**`AdminGetUser` alone, deliberately.** Table-share's twin statement also carries
`cognito-idp:ListUsers`, which nothing in this repo calls — every existence check in the fleet is
`admin_get_user`. **`ListUsers` would let this role enumerate the whole pool** (every username, email
and attribute), and copying it over would have widened the blast radius for no functionality.

**Rationale goes in the `.tf`, never the `.tftpl`.** IAM rejects a `"//"` comment key inside a
statement — verified with `simulate_custom_policy`.

## The browser gets no cross-prefix write, ever

Its only privilege is `sqs:SendMessage`. **That the browser cannot write into another user's prefix
is the isolation model working, and is the entire reason this plane exists.**

## `states:DescribeExecution` is on the execution role, not the machine's

It is the **`notify-failure` Lambda** that makes the call — invoked by EventBridge, **outside any
execution**. It reads back the input of a run whose event omitted it, which on this plane is **the
ordinary case for a large send**: EventBridge caps an event at 256 KB and the Pipe record is allowed
to approach 200 KB, so **without this the sends most likely to time out are the ones nobody can be
told about**.

## `MessageGroupId` is a HASH, never the raw path

The SHA-256 hex digest of `{bucket}/{sourceSpaceRoot}`, so repeated sends **out of** one space
serialize while sends from different spaces run in parallel.

**SQS caps the group id at 128 characters and an S3 key reaches 1024**, so the raw form would be a
length failure that only appears for deeply-nested sources.

`content_based_deduplication` is **off**, as on table-share: two byte-identical sends a user
genuinely repeats must not be silently absorbed by a 5-minute window.

## At-least-once delivery does not give this plane a re-run

The Pipe **cannot name the executions it starts**, and a redelivered message either returns the
original ARN or fails with `ExecutionAlreadyExists` (measured 2026-08-10). **Recovery is the DLQ
drain, never redelivery.**

`FIRE_AND_FORGET` is not merely chosen — `REQUEST_RESPONSE` is **impossible** for a Standard state
machine, and this plane's outcome is a notification rather than a response.

## The layer is named after the PLANE, not the package

The deploy policy matches `${project_name}-*-file-send-*`, which requires the literal `-file-send-`
infix **and** a trailing segment. A name built from the Python package instead —
`dat-prod-fscommon` — **matches nothing, and the failure surfaced as an implicit deny in `Deploy
Lambdas`, not as a plan error**.

**Nothing publishes a layer any more.** No workflow builds one, a container function cannot attach one, and the layer table is deleted. The name local and the deploy-role wildcard it was shaped to match both survive only until the published versions are destroyed, and they are removed in that order in their own PRs — so this section describes a rule that is still enforced and no longer reachable.

**There is no `execution_role_arn` local here**, deliberately. Root constructs its own twin for the
user-space bucket-policy allowlist, and a second construction of the same string in this module would
be one more place for it to drift from the role that actually exists — **with the failure appearing
as a runtime `AccessDenied`, not a plan error**.

## Why each verb is sized as it is, and which numbers a test reads back

- **`inspect-source`** is sized by holding the whole copy plan in memory, **not** by the listing,
  which pages at 1000 keys and costs 20 round trips at `SEND_MAX_OBJECTS`. Each plan entry carries
  the absolute source key, the relative key and the owning item name, so at worst-case 1024-byte keys
  20,000 objects serialise to ~48 MB with the in-memory list several times that again.
  **`test_the_worst_case_copy_plan_fits_in_the_verbs_memory` reads this number** and computes the
  plan against it, so raising `SEND_MAX_OBJECTS` without raising the memory fails the build.
- **`check-target-absent`** does **one delimited listing** of the recipient's inbox, paginated — so
  its cost is bounded by **what this sender has previously sent to this recipient**, not by the size
  of the send. The obvious alternative, a probe per selected item, would have been 400 round trips
  per recipient **and could not answer the question correctly** (see `fscommon/inbox.py` on S3's key
  ordering).
- **`build-transfer-manifest` and `collect-transfer-results`** handle the same volume in opposite
  directions and are JSON work, so memory is the CPU dial as much as the headroom — a 2048 MB
  function gets ~4× the CPU of a 512 MB one.
  **2048 MB is an asserted number at this stage, and saying so is the honest version.** It is
  table-share's shipped sizing for the identical pair at a 20,000-item cap. This plane has no
  transfer-item cap yet — the manifest is (recipients × objects), so today's caps permit
  50 × 20,000 = 1M items, **which this memory does not hold**. `SEND_MAX_TRANSFER_ITEMS` carries a
  test that reads this row and computes the cap against it. **Until then the bound is prose, which is
  what the cap is for.**
- **`copy-objects`** takes 900 s, and that is **not a preference**: it is `COPY_TIMEOUT_SECONDS`, the
  budget `cpcommon/transfer/config.py` divides by to size `MAX_ITEMS_PER_BATCH`.
  **`test_the_copy_timeout_matches_this_planes_deployed_verb` reads this row back**, so lowering it
  here fails the build rather than silently invalidating every makespan bound the engine reasons
  with. No object bytes pass through the function, so the memory buys CPU for the pool's threads.
- **`notify-failure`** is 60 s rather than 15 s, because the EventBridge `TIMED_OUT` door does
  strictly more work than the ASL one: a cold-start JWKS fetch plus a JWT verify before the send.

## `TimeoutSeconds` is 3 hours, and it arrived with the thing that made it necessary

Source resolution alone recorded that this machine **could not wedge**, because nothing in it waited:
no Map, no poll loop, no copy. The transfer adds all three, so it adds the timeout — **and with it
the EventBridge rule and the deploy-role `events:` grant that manages that rule, because a timeout
that cannot notify is a failure path satisfied on paper and silent in practice**.

**The arithmetic is `SEND_MAX_TRANSFER_BYTES` (3 TiB) — the recipient product, not
`SEND_MAX_TOTAL_BYTES`.** Every manifest item is a full copy, so the Map moves the source once per
recipient; sized against the 1 TiB source cap alone the number would be short by a factor of
`SEND_MAX_RECIPIENTS`.

**The denominator is a makespan, not an aggregate bandwidth.** `copy_batch` gives one whole object to
one worker and `copy_one` part-copies serially, so the pessimistic rate is
`transfer_map_max_concurrency × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s — **not the ~4 GB/s
the same constants suggest if you multiply them all together**. Under that rate 3 TiB is ~6,600 s;
the guard Map, the serial verbs and the per-child overhead of 50,000 items in batches of 8 take the
worst run to ~8,900 s.

**`test_the_whole_run_fits_the_machines_ceiling` computes every term of that from these locals**, so
a cap or a verb timeout raised without re-deriving it fails the build.

It is **deliberately not longer**: the timeout is how fast a wedged send becomes a notification.

**It does not on its own reach `NotifyFailure`** — catchers do not cover top-level execution
failures, so the EventBridge `TIMED_OUT` rule is the remedy. **`TIMED_OUT` only, never `FAILED`**, or
every caught failure double-notifies. Same shape as table-share's, which is the point: **two planes
with one failure mode should not have two answers to it.**

The guard Map's fan-out (5) is **named as a local rather than written into the ASL because the
transfer-cap test reads it** — the guard Map's makespan is one of the terms in the machine's own
timeout budget.

## The registry list grant is what makes "no such space" answerable

`RegistryList` lets this role run `s3:ListBucket` on the admin bucket, conditioned to
`shared-spaces/*` — the prefix `cpcommon.registry.load` reads and nothing wider.

It is there because this plane's authorize step branches on that function returning None for "no
such space", and S3 reports a missing object as absent only to a caller that can list the bucket.
Without the grant the None is unreachable and a request naming an unregistered space fails as a
fault instead of taking its refusal. Found in production on 2026-08-17, under a role that held the
`GetObject` grant and no list statement at all.

**Do not widen it to an unconditioned list.** This role reads `${admin_bucket_arn}/shared-spaces/*`,
so a bucket-wide list would hand it every shared space's name and then every roster, and the space
name is the only thing gating that read.

Why a conditioned grant is sufficient, why the IAM simulate suggests otherwise, and the production
evidence settling it: `docs/decisions/infrastructure.md` → *A role that cannot list a bucket cannot
be told an object is absent*. `lambdas/test_absence_is_answerable.py` holds every registry-reading
directory to this, and fails closed on one it cannot map to a role.
