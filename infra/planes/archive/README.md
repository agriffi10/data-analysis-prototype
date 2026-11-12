# `archive` — the vault, and the only plane that deletes user data

The standard control-plane shape — see [`../../modules/control-plane/README.md`](../../modules/control-plane/README.md)
for the files, roles and traps every plane shares. What follows is what is distinct here, and this
module is distinct in the way that matters most: **archiving is the only operation in this repo that
deletes a user's data as a side effect of a copy**, and a restore spends **billed, uncancellable
hours**.

Sixteen verbs across **two arms off one mode `Choice`**, sharing one machine because a restore is
meaningless without the archive that produced it. The Lambda side, including the state graphs, is
[`lambdas/info/planes/archive.md`](../../../lambdas/info/planes/archive.md).

Bucket 5 holds nothing but archived objects at the `GLACIER` storage class.

## ⚠ The browser has no relationship with the archive bucket at all

That is the design, not an omission, and it is enforced in four places:

- **No CORS configuration** — the same explicit absence the admin bucket carries.
- **The host is not in the CSP `connect-src`** — a reviewer must be able to read that enumerated list
  and see no archive host.
- **The portal role holds zero statements naming this ARN**, and a rendered-policy test asserts it.
- **The bucket policy denies everything but this plane and the deploy role**, using the same
  `StringNotLike aws:PrincipalArn` shape as the user-space bucket. That is what makes the property
  **enforced rather than merely true today**: an identity policy that grew a statement naming this
  ARN would still be denied here.

**The only route to archived bytes is a restore request through this plane** — which is the whole
point of archiving being reversible only through a request that takes hours.

The deploy role is excluded for the recorded reason: without it the deploy role cannot `HeadBucket`,
`tofu refresh` reads the bucket as deleted, and **every plan proposes a destructive recreate**.

## The source deletion is the statement to read twice

File-send and table-share each carry a blanket `Deny s3:DeleteObject` from their first apply and have
that be an enforced property forever. **This role cannot**, so the property that replaces it is
narrower and written out rather than assumed:

- `DeleteObject` is granted on **the two space buckets only** — never the admin bucket, and never the
  archive bucket's own data by that statement.
- **`NeverDeletePortalManagedObjects`** then Denies it under `athenaresults/` (the portal role's own
  results, which the bucket policy would refuse mid-batch anyway), `user_settings/` (the notification
  inbox and connections cache), `archive/` (the receipts **this** plane writes — archiving an
  archive), and on any `DO_NOT_DELETE.txt` **at any depth**, because `*` matches `/` in an IAM
  resource.
- **An explicit Deny beats every Allow, including a future one** — which is the point of writing it
  as a Deny rather than by narrowing the Allow.

**The IAM narrowing is the second line of defence and not the first.** The first is the **commit
gate** — the source is deleted only when every object has been confirmed copied — and the second is
`arcommon.delete.assert_deletable`, which **refuses the whole list before issuing anything**, so a
key the policy would refuse fails the run rather than stopping a deletion half way through.

**The archive bucket's own `DeleteObject` is the rollback's**, and it is the one grant that looks
surprising on a vault. **A partial copy is not an archive**, so it is removed; without this the gate
could refuse the deletion but not clean up after itself, and the residue would sit at the GLACIER
90-day minimum until the 7-year expiry. The restore uses the same grant to clear a restored archive.

## The restore added two grants, and the second is a deliberate widening

- **`s3:RestoreObject` on the vault.** It is a **distinct action** from `GetObject` and `PutObject` —
  a role holding both still cannot initiate a retrieval, and **the failure would be an `AccessDenied`
  at the point of no return rather than at plan time**.
- **`s3:PutObject` on the two space buckets, unrestricted by prefix within the space root**,
  replacing the old `*/archive/*`-only receipt grant. The archive only ever wrote a receipt into a
  user's space; **a restore writes wherever the data came from, which is anywhere in the space**, so
  the narrow grant cannot stand. The multipart pair joins it because an archived object may be up to
  `ARCHIVE_MAX_OBJECT_BYTES` (10 GiB) and the copy-back part-copies above 5 GiB.

**`NeverOverwritePortalManagedObjects` is the narrowing that goes with that widening**, and it is
defence in depth rather than the rule itself. `athenaresults/` and `user_settings/` can never appear
in an archive — `RESERVED_SOURCE_ROOTS` refuses them at archive time, `plan._assert_deletable_folder`
refuses them at any depth, and the destination guard's fail-closed 403-is-occupied rule refuses them
again at restore time — so **this Deny cannot refuse a legitimate restore**. What it buys is that a
plan which somehow named one of them could not overwrite the notification inbox or a user's query
results. It deliberately does **not** cover `archive/`, which is where the receipt lives.

**It also covers `_config/` and `_directory/`, which sit at the bucket root and not inside any
space.** A `*/x/*` pattern cannot match a key with one segment before the folder, so **the two
documents that are arguably the most dangerous things in that bucket** — the feature-flag document
that decides what every user can see, and the username directory — **were outside a statement whose
name claims to cover portal-managed state**. They are unreachable from code, because every restore
destination is built by `paths.origin_key` under an authorized space root, but the widening is what
made naming them cheap and correct.

**The two Denies are two different verbs on two overlapping prefix sets, and the difference is the
receipt: this plane may WRITE under `archive/` and may never DELETE there.**

**Rationale goes in the `.tf`, never the `.tftpl`** — IAM rejects a `"//"` comment key inside a
statement, verified with `simulate_custom_policy`.

`states:DescribeExecution` is on the **execution** role rather than the machine's, because it is the
`notify-failure` **Lambda** that makes the call, invoked by EventBridge outside any execution — and
on this plane a large archive's event routinely omits the input, so **the archives most likely to
time out are the ones nobody could otherwise be told about**.

## Versioning is off, and Object Lock is out of scope for two reasons

Deferred by decision, 2026-08-03, matching every other bucket. **It is worth saying explicitly on an
archive bucket** because the obvious next thought is S3 Object Lock — which **requires versioning**,
and which is out of scope for a second, independent reason: **in compliance mode nothing can delete
an object, not even root**, so the cleanup of a restored archive would be impossible.

## Retention is a CEILING, not a WORM floor

Every object expires 7 years after creation. **Nothing here prevents an earlier delete** — the
restore deletes the archived copy once it has been put back, and it must be able to.

**The expiry rule is deliberately bucket-wide with no prefix filter, and it is the exact inverse of
the admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check.** That check exists because the
admin bucket mixes `logs/` (retained forever) with expiring content, so an unfiltered rule there
would silently delete the logs. **This bucket holds exactly one class of object, so the risk runs the
other way**: a prefix filter would be a silent way to leave some archived data unexpired past the
retention the feature promises.

**S3 lifecycle can include a prefix but never exclude one.** So if a second content class is ever put
in this bucket, **the repair is not to add a filter here** — that would leave the new class unexpired
and this rule looking correct. It is to revisit the rule, and probably to give the new class its own
bucket.

The multipart-abort rule carries no `expiration` and can only discard the **parts** of an upload that
never completed, so **it cannot delete an object**.

## ⚠ The group id orders the STARTS, not the runs

`MessageGroupId` for an **archive** is the SHA-256 digest of `{bucket}/{sourceSpaceRoot}` — **a hash,
never the raw path**, since SQS caps a group id at 128 characters and an S3 key reaches 1024. **A
restore keys on the ARCHIVE, not the space:** the SHA-256 of the archive root alone,
`{kind}/{name}/archive/{archiveId}/`.

**Neither key serializes execution.** The Pipe starts the machine `FIRE_AND_FORGET`, the only mode a
Standard machine accepts, and the message leaves the queue once `StartExecution` returns — so the next
message in the group starts a second run while the first is still going. What a group id buys is that
the starts for one space, or for one archive, are made one at a time and in order, and that a failed
start holds the next one back until its retries run out. File-ops holds a lock for exactly this, and
its live check watched two runs in one group overlap on a Pipe identical to this one; **this plane has
no lock**, so here is what overlap does.

- **Two archives from one space may select overlapping folders, and an archive deletes its source.
  The commit gate is what keeps that safe, not the queue.** Each run deletes only its own plan's keys,
  only once every one is confirmed under its own archive id, and its rollback lists only that prefix.
  An object both runs copy before either deletes is archived twice; an object one run deletes before
  the other copies fails that copy, and the other run rolls back having deleted nothing.
- **Two restores of one archive are not billed twice** — S3 answers the second `RestoreObject` with
  `RestoreAlreadyInProgress`, which the verb tolerates, or bills it as a GET once the first has
  finished. **But both pass the first guard**, since nothing lands for hours, and what follows
  depends on timing, because each run polls every five minutes on its own clock. The first run to
  see the retrieval finish can restore a small archive and sweep the vault before the other polls
  again, and that poll then fails as `archive_object_unreadable`, telling the user to contact an
  administrator — **this plane's own live run hit exactly that**, two restores 25 s apart
  (`docs/testing/sessions.md`, *The archive and restore, run under §4.11's approval gate*). A
  second guard pass that runs after the other run has copied any file back refuses as occupied,
  over files that are the restore itself. If both second passes run before any copy lands, both
  copy back — **conditionally**, since every restore manifest line carries `ifAbsent`, so neither
  run can write over a file the other put back and neither can write over a file the USER created
  while the Map was running. A refused write is resolved by comparing the destination against the
  source rather than reported as a collision, so a batch retrying after a transient fault does not
  report the files it just restored as being in the way.

  **What overlap still costs is reports, and that is the accepted price.** Both runs may send
  "started" and "restored"; where one sweeps the vault before the other finishes copying, the
  other reports an incomplete restore over files that all landed; where it sweeps before the other
  polls again, the other fails as `archive_object_unreadable`. **What it no longer costs is the
  only copy**: no restore message tells the user to delete anything, and none calls the archive
  intact without counting it — the incomplete arm counts the objects still under the prefix and
  says only what that count proves.
- **One request id sent twice, past the five-minute dedup window, used to be the unrecoverable
  case.** The two runs share one prefix, and a second run that fails its gate has its rollback
  delete the first run's completed archive after the first has deleted the source.
  `assert_archive_unused` narrows that and cannot close it — two runs reaching it together both
  find the prefix empty. **inspect-source therefore claims the id** with a create-only write to
  `archive/{requestId}/claim.json` in the admin bucket, taken after the listing and before
  anything else is written, so S3 rather than either run decides which one proceeds; the loser
  refuses `request_id_reused`, silently, because the winner reports under that id. The claim
  expires with the admin prefix after 30 days, which is safe only because no second run of an id
  can start that late — the queue and its DLQ hold a message for at most fourteen days and a run
  lasts at most twelve hours. A test reads those three numbers and fails if the margin closes.

> The restore's group id is derived server-side, by the API, since the queue moved behind it,
> so the property the browser used to be trusted with is held where it is now computed.
> `test_archive_restore_keys_on_the_archive_root_and_carries_no_bucket` pins that the id does
> not move when the space bucket changes, and `test_every_captured_vector_replays_byte_for_byte`
> replays two captured `archive.restore` vectors byte for byte, which is what holds the id
> itself — no bucket appears in either.

`content_based_deduplication` is **off**: the producer sends an explicit
`MessageDeduplicationId = requestId`, **and that id is also the archive's permanent identity**, which
makes the two properties one — **a resend of the same request cannot open a second archive under a
second uuid**. Inside the five-minute window a resend is absorbed outright; past it, it opens a second
RUN under the same uuid, which is the last case above.

Its own queue and its own DLQ, registered with the drain sweep, which names the feature by the DLQ a
request lands on: a dead-lettered archive must never reach its user as a file send.

## `TimeoutSeconds` is 43,200 — and the storage class, not the data, is why

Three hours sizes the **archive** arm, whose long pole is a copy: `ARCHIVE_MAX_BYTES` over a
**makespan** rate of `transfer_map_max_concurrency × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s
— **not the ~4 GB/s the same constants suggest multiplied together**. Under that rate 3 TiB is
~6,600 s, and the per-child overhead plus the seven serial verbs take the worst run to ~8,100 s.
**Unlike file-send there is no recipient product to multiply by: an archive has one destination, so
the source cap *is* the transfer cap.**

**The restore arm's long pole is a WAIT.** A `GLACIER` object is not readable, and the Standard
retrieval tier takes **3–5 hours** to produce the temporary copy the copy-back reads — **so the old
three-hour ceiling would have killed a healthy restore before S3 had finished with it**. The restore's
terms are the retrieval budget (`RESTORE_POLL_SECONDS × RESTORE_MAX_POLLS` = 7 hours, **deliberately
above the tier's own 5, because giving up early makes the user pay for a second billed retrieval**),
the poll's own work, the copy-back at the same makespan rate, both Maps' per-child overhead and the
serial verbs — ~35,500 s in total.

**`test_the_whole_archive_run_fits_the_machines_ceiling` and
`test_the_whole_restore_fits_the_machines_ceiling` sum every term of their arm, and read the
ceiling and the serial verb timeouts out of these locals** — the copy term comes from the Python
caps instead. Both carry several times' headroom, so RE-DERIVE them when raising a cap rather
than expecting the build to refuse: no verb-timeout raise Lambda would accept reaches either.

**It is one field on one machine, so the archive arm's backstop rises with it** — a wedged archive is
now reported after twelve hours rather than three. That is the accepted cost of the two arms sharing a
machine; `TimeoutSeconds` is top-level ASL and **cannot differ per branch**. The archive arm's own
worst legal run is ~8,100 s and still clears this by 5×.

**It does not on its own reach `NotifyFailure`** — catchers do not cover top-level execution failures,
so the EventBridge `TIMED_OUT` rule is the remedy, **`TIMED_OUT` only, never `FAILED`**. That rule,
`notify-failure`'s second door and its raise from 15 s to 60 s **all arrived with the transfer**,
because **a timeout that cannot notify is a failure path satisfied on paper and silent in practice**.
The deploy-role `events:` grant that manages the rule shipped **one PR ahead** — the merge apply went
red for exactly that ordering.

## Verb sizing, and the numbers a test reads back

- **`inspect-source`** and **`inspect-archive`** are sized by holding the whole plan in memory, not by
  the listing. `test_the_worst_case_archive_copy_plan_fits_in_the_verbs_memory` reads
  `inspect-source` (and `delete-source`); `inspect-archive` is read back by
  `test_the_restore_plan_fits_in_the_lookup_verbs_memory`.
- **`build-transfer-manifest` / `collect-transfer-results`** (and their restore twins) handle the same
  volume in opposite directions; memory is the CPU dial as much as the headroom. Both rows are read
  back by `test_the_worst_case_manifest_fits_in_the_verbs_either_side_of_the_map` — **a test that
  arrived in review: until it did, the comment claimed a bound nothing held**.
- **`check-destination-clear`'s timeout is the free variable in `RESTORE_HEAD_CONCURRENCY`'s
  arithmetic.** The pool **cannot simply be widened to go faster**: boto3's S3 client takes botocore's
  default `max_pool_connections` of 10, **so 8 workers is the ceiling that actually holds and the TIME
  is what has to be bought**. 20,000 destinations, 8 at a time, at a pessimistic 100 ms each is ~250 s.
  `test_the_guard_can_head_every_destination_inside_its_timeout` reads it.
- **`poll-restore` re-uses the guard's arithmetic rather than re-deriving it**, because it does the
  same work. A sweep that finds every page complete heads all 20,000 objects in one invocation —
  **that is the point of sweeping past the page rather than stopping at it, since one page per
  five-minute Wait would add over an hour after a retrieval had already finished**.
- **`copy-objects`** takes 900 s because that is `COPY_TIMEOUT_SECONDS`, the budget
  `cpcommon/transfer/config.py` divides by to size `MAX_ITEMS_PER_BATCH`, and a test reads the row
  back.
- **`initiate-restore`** is far cheaper than the copy beside it — a retrieval request is a small
  synchronous call and no bytes move — so 60 s is the room a cold start and a retry storm need, **not
  the work**.
- **`notify`** is the plane's only **success** producer and the smallest verb here; `notify-failure` is
  larger because its second door may read a large run's input back with `DescribeExecution` before
  the send. It was sized when that door also verified a JWT, which it no longer does.

## Reuse that makes the state count exceed the verb count

**Three ASL states point at `update-receipt`**, and two point at `copy-objects` and
`collect-transfer-results`. Both reuses are deliberate:

- The receipt records a restore at three stages (requested, restored, incomplete) **and the ASL seeds
  which one**, so the verb never infers its own stage from what else happens to be lying on the state.
- The copy-back asks the copy's identical question in the opposite direction; what differs is only
  what the answer authorizes.
- **`notify` is fed to three states for the same reason**: the outcome is a property of *where the
  machine is*, not of what is on the state.

**The front door serves both modes** — the mode `Choice` sits downstream of it, so a second
restore-only validator would need the branch to happen before anything had parsed the body.

## Naming, and the one bucket that breaks the pattern

The deploy policy matches `${project_name}-*-archive-*`, needing the literal `-archive-` infix **and**
a trailing segment. A name built from the Python package — `dat-prod-arcommon` — matches nothing, and
**fails as an implicit deny in `Deploy Lambdas`, not as a plan error**.

**The bucket is the one exception, deliberately.** `{project}-prod-archive` has no trailing segment, so
it does **not** match `-archive-*`; it is granted by its own exact-name statement, exactly as the other
four buckets are. S3 bucket names are globally unique, so it takes a root variable override too.

**There is no `execution_role_arn` local here** — root constructs its own twin for **both** the
user-space bucket-policy allowlist and this bucket's own policy.

## Numbers mirrored from Python, and one deliberately not mirrored

The transfer Map's batch numbers and `RESTORE_POLL_SECONDS` are mirrored because ASL cannot import
Python, and a test holds each pair equal. Five minutes against a 3–5 hour retrieval is **~1% of the
wait spent asking**.

**`RESTORE_MAX_POLLS` lives only in Python**, because `poll-restore` computes `exhausted` itself
rather than the `Choice` comparing against a literal — **two homes for that number would only disagree
on a restore that was already going badly**. The file-ops lock records the same split.

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
evidence settling it: `docs/decisions/infrastructure/` → *A role that cannot list a bucket cannot
be told an object is absent*. `lambdas/test_absence_is_answerable.py` holds every registry-reading
directory to this, and fails closed on one it cannot map to a role.
