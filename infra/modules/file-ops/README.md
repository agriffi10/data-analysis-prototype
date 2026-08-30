# `file-ops` — the move/copy/delete control plane

The standard control-plane shape — see [`../../info/control-plane-shape.md`](../../info/control-plane-shape.md)
for the files, roles and traps every plane shares. What follows is what is distinct here.

Twelve verbs: the front door, the lock's two halves, the notification of last resort, the two that
decide **what** and **whether**, the five that make it happen — the manifest, the Map's batch copier,
the attribution, the source deletion and the terminals — and the one that finally tells the user,
**after the lock is already free**.

The Lambda side is [`lambdas/info/planes/file-ops.md`](../../../lambdas/info/planes/file-ops.md).

## ⚠ This role holds `DeleteObject` across both data buckets

**The single most dangerous grant in this repo.** It arrived **grants-first**, together with the code
that justifies it and the Denies that bound it. The two earlier specs deliberately shipped without
it, so the widening was a review of its own rather than a line inside a larger change.

Each grant, and why none is an exception:

- **`EmitNotifications`** — the failure path ships from day one and that verb enqueues a
  notification, so a role without this cannot run the plane's own first failure path.
- **`RegistryRead`** — authorizing a **shared** space is a registry read. Without it every
  shared-space source or destination fails `AccessDenied` while every personal one works — **a split
  that reads like a code bug and is not**.
- **`SpaceLockReadWrite`** and **`PlanReadWrite`** — the lock object and the copy plan, each scoped
  to its own prefix.
- **`ReadSpaceObjects`** — the expansion lists and heads, the guard heads every destination, the
  deletion heads every source to compare against the recorded ETag. **It is also a hard requirement
  of a conditional delete**: AWS documents that a valued `If-Match` delete needs **both**
  `s3:DeleteObject` **and** `s3:GetObject`, so narrowing this later would **silently break every
  conditional deletion rather than failing loudly**.
- **`WriteSpaceObjects` / `DeleteSpaceObjects`** — `ListMultipartUploadParts` and
  `AbortMultipartUpload` are there because an object over 5 GiB copies through `UploadPartCopy`, and
  an aborted upload that cannot be cleaned up accrues storage the user never sees.
- **`ReadTimedOutExecutionInput`** — the one grant the timeout door needs, on **this** role rather
  than the machine's, because it is the `notify-failure` **Lambda** that makes the call, invoked by
  EventBridge **outside any execution**. It reads back the input of a run whose event omitted it,
  which here is **the ordinary case for a large selection**: EventBridge caps an event at 256 KB and
  this plane's own cap allows a request to approach it.

**No Cognito grant, and the absence is deliberate rather than pending.** Token verification is
offline against the pool's public JWKS — an HTTPS fetch, not an API call — and **this plane looks
nobody up**: it authorizes the actor against a *space*, never against a user directory. The
neighbouring planes carry `AdminGetUser` because they resolve a **recipient**; there is no recipient
here.

## `NoDataObjectWrite` is gone, deliberately and by name

It was the blanket "this role writes nothing into a user's space" Deny, and the transfer is exactly
what it forbade. **Removing a Deny is the kind of edit that should be hard to do by accident**, which
is why the two earlier specs left it in place and said in this module that the transfer would take it
out.

**What replaces it is narrower but not weaker where it matters:** the portal's own folders are still
unwritable and undeletable by this role, now stated as their own two Denies.

## The portal-managed Denies are any-depth, which is stricter than the browser's own rule

The browser refuses `athenaresults/` **root-anchored** in a personal space — its policy is written
against `${aws:PrincipalTag/username}`, which pins it to one segment — and **at any depth** in a
shared one.

**This role carries no principal tag, and an IAM `Resource` wildcard matches `/`** — there is no way
to say "exactly one path segment" — so the personal case **cannot be expressed root-anchored here**,
and the strict side is taken.

**The consequence is real and is handled rather than hidden:** a personal folder holding a *nested*
`athenaresults/` is undeletable by this plane, so **`focommon/delete.py` mirrors this policy rather
than the browser's rule** and refuses such an item **per item, before anything is copied**. Mirroring
the browser instead would produce an `AccessDenied` part way through a batch, **after the copy, with
the source half gone**.

## The marker Deny matches a path SEGMENT, not a suffix

`*/DO_NOT_DELETE.txt`, **not** `*DO_NOT_DELETE.txt` — the suffix form the archive plane uses also
matches `alice/reports/backupDO_NOT_DELETE.txt`, a perfectly ordinary user file.

Every code rule on this plane matches the **basename** exactly, so the suffix form would let such a
key **pass the pre-delete check, get copied, and then take an `AccessDenied` mid-batch** — leaving
the item reported as a duplicate with an orphan behind it. **That is precisely the mid-batch denial
the pre-check exists to prevent.**

## The `s3:if-match` bucket-policy enforcement is declined

The documented pattern — `"Null": {"s3:if-match": "false"}` — denies any delete carrying no condition
header. **It cannot be used because this plane has two delete paths with different conditionality on
purpose**: a **move's** deletion is conditional on the recorded ETag, and a **delete operation's** is
deliberately unconditional (there is no copy to protect, and an object modified since the expansion is
still one the user asked to remove). A bucket-wide condition cannot express both, so enabling it would
**403 every delete-operation deletion**.

## `NoLockDelete` is a Deny present from the first apply

**The lock releases by overwriting, never by deleting**, so that "free" is a **state** of the object
rather than its absence, and a stolen lock stays detectable by compare-and-set. Writing the Deny early
makes that an enforced property instead of a convention. It is scoped to the **admin bucket alone**,
so the data-bucket deletes are unaffected.

**Rationale goes in the `.tf`, never the `.tftpl`** — IAM rejects a `"//"` comment key inside a
statement.

## ⚠ Ordered delivery is not serialized execution

`MessageGroupId` is the SHA-256 digest of `{bucket}/{sourceSpaceRoot}` — **a hash, never the raw
path**, since SQS caps a group id at 128 characters and an S3 key reaches 1024.

But **the Pipe starts the machine `FIRE_AND_FORGET` and returns**, so it is free to deliver the next
message while the previous execution is still running. **A delete removing objects a concurrent move
has already relocated is silent, unrecoverable loss with versioning off.**

**The Pipe is the resource that makes the lock necessary.** Reading FIFO as "ordering handles it" is
the mistake the per-space lock exists to correct. The group id buys **ordering and throughput
isolation, and nothing else**.

`content_based_deduplication` is **off**: two byte-identical operations a user genuinely repeats must
not be absorbed by a 5-minute window.

**At-least-once delivery does not give this plane a re-run** — the Pipe cannot name the executions it
starts, and a redelivered message either returns the original ARN or fails with
`ExecutionAlreadyExists`. **Recovery is the DLQ drain.** Its own queue and its own DLQ: a malformed
file operation must never dead-letter someone's file send.

## Three verbs hold the parsed plan, and their memory rows are inputs to a cap

`FILE_OPS_MAX_OBJECTS` is the **minimum** over every plan-holding verb's memory, and
**`test_config_focommon` reads these numbers back out of `locals.tf`**. Adding a sixth plan-holder
without adding it to that set **would have the cap certify memory it never checked**.

- **`build-transfer-manifest` is the worst of the three**: it holds the parsed plan **and** the joined
  manifest body at once, because `cpcommon.transfer.manifest` builds the whole payload with
  `"\n".join(...).encode()` before the PUT. **Both terms are charged in the cap's own test rather than
  assumed to fit.**
- **`notify` reads the STATE and nothing else.** Reaching for the plan would put it in the set whose
  `min()` sizes `FILE_OPS_MAX_OBJECTS`, **shrinking a cap that has nothing to do with notifying** —
  and a test derives that set from the source to stop exactly that.
- **`copy-objects` passes no object bytes**: every copy is server-side, so its memory is the runtime's
  floor rather than a function of the data. Its timeout is `COPY_TIMEOUT_SECONDS`, which the batch
  size is computed against, and a test holds the two equal.

**`validate-authorize`'s timeout is an input to the lock budget**, and **`delete-source`'s and
`notify`'s are terms in the machine's ceiling.** A test recomputes each. Raising one without
re-deriving fails the build.

## `TimeoutSeconds` ships from the first version, and the CAP moved rather than the ceiling

Unlike the planes whose ceiling arrived with their transfer, **this machine can wedge before it does
any data work at all**, because the waiting loop is in it from day one: a request whose lock is held
by something that never finishes would otherwise sit in a Wait/re-acquire cycle for **a year**.

`test_config_focommon` computes the **joint budget** — the lock give-up, plus **two** guard sweeps,
plus every serial verb timeout, plus the copy's makespan at `FILE_OPS_MAX_TOTAL_BYTES`, plus the
deletion — and asserts it fits.

**At the 3 TiB the byte cap started at, that came to ~12,700 s against this 10,800 s.** Raising the
**ceiling** instead would have raised `STALE_LOCK_SECONDS` with it — **that threshold must exceed the
ceiling, or a running execution's lock gets stolen** — and a longer stale window on a **shared** space
blocks everyone else who works in it, not just the person whose run wedged. **So
`FILE_OPS_MAX_TOTAL_BYTES` came down to 2 TiB.**

**It does not on its own reach `NotifyFailure`** — catchers do not cover top-level execution failures,
so the EventBridge `TIMED_OUT` rule is the remedy. **`TIMED_OUT` only, never `FAILED`.** Same shape as
the neighbouring planes': **three planes with one failure mode should not have three answers to it.**

**That door deliberately does not release the lock.** By the time it fires the execution is already
gone and the lock may have been **stolen by a later arrival** — releasing here would overwrite that
new holder's claim and **reintroduce exactly the concurrency the lock exists to prevent, from its own
cleanup**. The stale-lock steal is the recovery.

## Numbers mirrored from Python, and one deliberately not mirrored

The lock prefix, the copy-plan prefix, the re-acquire `Wait` interval and the Map's shape are all
mirrored from Python because ASL cannot import it, and **a test holds each pair (or trio) equal**.

**The copy-plan prefix cannot match `locks/file-ops/`** — an S3 lifecycle prefix anchors at the start
of the key — **which is what keeps an expiry rule off the lock objects**, whose absence is what would
make a lock "lost" rather than "free".

**`LOCK_MAX_ATTEMPTS` is deliberately not here.** The interval is an ASL field and has to be; the cap
is the verb's own decision, and **a second home for it is a number that can drift**. The archive
plane's poll loop records the same split.

## The layer is named after the PLANE, not the package

The deploy policy matches `${project_name}-*-file-ops-*`, needing the literal `-file-ops-` infix
**and** a trailing segment. `dat-prod-focommon` matches nothing, **and the failure surfaces as an
implicit deny in `Deploy Lambdas`, not as a plan error**.

**There is no `execution_role_arn` local here** — root constructs its own twin for the bucket-policy
allowlist, and a second construction would be one more place to drift, **with the failure appearing as
a runtime `AccessDenied`, not a plan error**.

## Absence is asked with a LIST, because a denied read and a missing object look the same

`ListPlanPrefixForHonestAbsence` lets this role run `s3:ListBucket` on the admin bucket, confined
by an `s3:prefix` condition to the plan prefix. The condition is why `focommon.plan` carries a
probe rather than relying on the read alone.

The plan guard reads `file-ops/{requestId}/plan.json` and treats absence as "nobody has planned
this id". S3 only answers `NoSuchKey` for a missing object when the caller can list the bucket;
without that permission a missing object is `AccessDenied`, which the guard classified as
`plan_unreadable`. The plan never exists on a first submission, so **every** operation this plane
handles failed — which is every folder copy, move and delete, and every multi-item one too: the
routing predicate sends it anything that is not exactly one file — reported to the user as *"the working list for that could not be read back."* Not
hypothetical: the plane's first live execution failed at `InspectSource` on exactly this, and
nothing caught it earlier because the offline suites faked absence as `NoSuchKey`, which is the one
shape production never produces.

**A conditioned grant does not fix the read, and that is deliberate rather than an oversight.** A
`GetObject` request carries no prefix, so the condition sits on an unpopulated key and fails closed
— simulated against the deployed shared-space role, `s3:ListBucket` on this bucket is
`implicitDeny` with no `s3:prefix` supplied and `allowed` with one. The unconditioned form *would*
fix the read directly, and it was rejected: this role already holds `GetObject` on
`${admin_bucket_arn}/shared-spaces/*`, so a bucket-wide list would hand it every shared space's
name and then every roster — the disclosure the project declines by publishing no shared-space
directory at all. The space name was the only thing gating that read.

So the grant stays inside the plan prefix and `plan._absent` asks the question with a list, which
does carry the prefix. The remaining rule is what keeps it from failing open: **a denial is never
absence on its own.** Only a list that comes back without the key is. A real denial on an object
that exists still raises, rather than planning over a run already copying, and a denied *list*
raises too — the caller cannot tell, so it does not guess. The third alternative, reading
`AccessDenied` as absence in code, is that fail-open and is refused everywhere else on this fleet.

`test_file_ops_admin_list_grant.py` pins the grant, its condition, and the fact that the condition
names the same template variable the object statements do — a rename that moved one and not the
other would restore the original failure with both halves individually well-formed.
