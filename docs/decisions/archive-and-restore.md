# Archive and restore — the only place a mistake is unrecoverable

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [The archive vault, and the four choices that shape the whole arc (SPEC-168)](#the-archive-vault-and-the-four-choices-that-shape-the-whole-arc-spec-168)
- [`GLACIER`, and why the other two were rejected](#glacier-and-why-the-other-two-were-rejected)
- [Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose](#retention-is-a-ceiling-not-a-worm-floor--and-the-lifecycle-rule-is-unfiltered-on-purpose)
- [The bucket the browser has no relationship with](#the-bucket-the-browser-has-no-relationship-with)
- [The key layout: the archived key carries its own origin, partitioned by space kind](#the-key-layout-the-archived-key-carries-its-own-origin-partitioned-by-space-kind)
- [One plane, one `mode` branch, and no grant this spec did not need](#one-plane-one-mode-branch-and-no-grant-this-spec-did-not-need)
- [Two things the fleet's own guards caught while this was being written](#two-things-the-fleets-own-guards-caught-while-this-was-being-written)
- [The commit gate, and the four choices that make a deletion safe (SPEC-169)](#the-commit-gate-and-the-four-choices-that-make-a-deletion-safe-spec-169)
- [The source is deleted only when EVERY object is confirmed copied](#the-source-is-deleted-only-when-every-object-is-confirmed-copied)
- [The rollback deletes what is THERE, not what it was told about](#the-rollback-deletes-what-is-there-not-what-it-was-told-about)
- [The delete grant is the one this role could not inherit](#the-delete-grant-is-the-one-this-role-could-not-inherit)
- [The request id is browser-supplied, so a reused one is refused twice over](#the-request-id-is-browser-supplied-so-a-reused-one-is-refused-twice-over)
- [An object this plane could copy but could not delete is refused, not archived](#an-object-this-plane-could-copy-but-could-not-delete-is-refused-not-archived)
- [The artifacts are ordered most durable to least, and the receipt's failure is terminal](#the-artifacts-are-ordered-most-durable-to-least-and-the-receipts-failure-is-terminal)
- [Three caps, and the one the spec does not name](#three-caps-and-the-one-the-spec-does-not-name)
- [The ceiling ships with its rule, again](#the-ceiling-ships-with-its-rule-again)
- [The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops](#the-receipts-paths-name-the-roots-and-the-expansion-keeps-what-every-other-plane-drops)
- [The restore guard, and the four choices that make it safe to start a bill (SPEC-170)](#the-restore-guard-and-the-four-choices-that-make-it-safe-to-start-a-bill-spec-170)
- [The guard is absolute, and it runs before the retrieval](#the-guard-is-absolute-and-it-runs-before-the-retrieval)
- [The bound is botocore's connection pool, not the thread count](#the-bound-is-botocores-connection-pool-not-the-thread-count)
- [The lookup reads the KEYS; the record is a cross-check it can do without](#the-lookup-reads-the-keys-the-record-is-a-cross-check-it-can-do-without)
- [The space comes from the request, and the two ids are different things](#the-space-comes-from-the-request-and-the-two-ids-are-different-things)
- [One front door, one `Validated` Pass, and two message prefixes](#one-front-door-one-validated-pass-and-two-message-prefixes)
- [This spec adds no IAM, and that is asserted rather than assumed](#this-spec-adds-no-iam-and-that-is-asserted-rather-than-assumed)
- [Review closed two holes, and one of them was a silent, unrecoverable deletion](#review-closed-two-holes-and-one-of-them-was-a-silent-unrecoverable-deletion)
- [Retrieval as the point of no return, and the four asymmetries the restore introduces (SPEC-171)](#retrieval-as-the-point-of-no-return-and-the-four-asymmetries-the-restore-introduces-spec-171)
- [The destination guard runs TWICE, because this spec turned a guarantee into a promise](#the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee-into-a-promise)
- [The retrieval Map tolerates NO failure, and the copy tolerates every one](#the-retrieval-map-tolerates-no-failure-and-the-copy-tolerates-every-one)
- [Completion is the `Restore` header, and an ABSENT header is a failure](#completion-is-the-restore-header-and-an-absent-header-is-a-failure)
- [The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane](#the-retrieval-budget-has-deliberate-headroom-and-the-ceiling-moved-for-the-whole-plane)
- [The restore's gate is the commit gate's MIRROR IMAGE, not its twin](#the-restores-gate-is-the-commit-gates-mirror-image-not-its-twin)
- [The receipt is rewritten, never re-rendered, and the counts come from the run](#the-receipt-is-rewritten-never-re-rendered-and-the-counts-come-from-the-run)
- [The metadata fix: a latent bug on all three planes, surfaced by a round trip](#the-metadata-fix-a-latent-bug-on-all-three-planes-surfaced-by-a-round-trip)
- [The archive surface: a confirm that is not a confirm, folder names as identity, and the first prefix write gate (SPEC-172)](#the-archive-surface-a-confirm-that-is-not-a-confirm-folder-names-as-identity-and-the-first-prefix-write-gate-spec-172)
- [The one dialog in this app where the confirm is not the default, and Enter does nothing](#the-one-dialog-in-this-app-where-the-confirm-is-not-the-default-and-enter-does-nothing)
- [The folder names ARE the archive ids, so the folder must stay visible](#the-folder-names-are-the-archive-ids-so-the-folder-must-stay-visible)
- [The write gate mirrors each bucket's own Deny, and averaging them gets one case wrong](#the-write-gate-mirrors-each-buckets-own-deny-and-averaging-them-gets-one-case-wrong)
- [Only three outcomes needed a producer, and one of them had to be invented](#only-three-outcomes-needed-a-producer-and-one-of-them-had-to-be-invented)
- [The restore's FIFO group id hashes the archive ROOT, not the bucket and the root](#the-restores-fifo-group-id-hashes-the-archive-root-not-the-bucket-and-the-root)
- [The group id orders the STARTS, not the runs, and the restore guard is not absolute at the write](#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)
- [A folder placeholder is not a file to the person reading the count](#a-folder-placeholder-is-not-a-file-to-the-person-reading-the-count)
- [The source is deleted only while it is UNCHANGED since the plan listed it](#the-source-is-deleted-only-while-it-is-unchanged-since-the-plan-listed-it)

## Fences

A separate `GLACIER` vault the browser has no relationship with. A restore is `RestoreObject` + a
3–5 hour wait + a copy.

- **The restore guard is ABSOLUTE and runs before the bill:** any occupied destination refuses the
  **whole** restore, and a **403 counts as occupied**. **It holds at the CHECK and at every WRITE**,
  by two mechanisms that are not redundant: the guard refuses the whole restore up front with the
  colliding paths named, and every copy-back line is a **conditional write**, so a file arriving
  while the Map runs is left alone one object at a time. A refused write is **resolved by comparing
  destination against source**, never read as occupied outright — a batch retrying after a transient
  fault meets its own earlier writes, and reading those as collisions would report the files it just
  restored as being in the way. **Every test of the condition runs against a fake**; the deployed
  behaviour is owed (`docs/testing/owed.md`, *the conditional copy-back*). **The comparison rests
  on an ETag, which under `AES256` is an MD5** — so a co-member of a shared space who knows an
  archived object's bytes could in principle write a same-length MD5 collision at the destination
  and have the item counted copied and the vault swept. It needs a chosen-prefix collision, the
  target's content, and write access to the path — which already allows overwriting the file
  directly — so what the attack adds is the sweep. Not repaired here; the repair is to prefer
  `ChecksumSHA256` when the object carries one.
- **It runs TWICE**, and the second pass is the spec correcting itself: those billed hours are spent
  telling the user a restore is in flight, so re-creating a file meanwhile is the ordinary case — and
  the copy-back would have overwritten it, reported success and swept the vault.
- **No restore message may tell the user to destroy anything, or state the archive's condition as
  fact** — two restores of one archive still both run, and the first to finish sweeps the vault, so
  the files a message names can be the other run's output and the only copy left. The remediation is
  **"move or rename"**; the one permitted claim is time-scoped (*"was still complete when this
  restore stopped"*) and must be **earned by counting** the prefix. Both rules are enforced over the
  whole table and the receipt by a test with its own plant corpus, because per-sentence fixes were
  tried first and each review round found another sentence. **Both rules are DENYLISTS and neither
  is finished** — a security review walked twelve ordinary instructions ("destroy", "trash", "get
  rid of", "send them to the recycle bin") past the first seven-word version — so the corpus of
  escapes found so far is kept as a test rather than the coverage being asserted, and widening the
  list is the cheap side of the trade. Two residuals stand: rule 2 does not catch
  `destination_occupied_after_retrieval`'s "will stay ready for a few days", which invites no
  deletion; and the rules run over TEMPLATES, so a colliding key rendered into `{sample}` is
  attacker-chosen text in a safety-critical sentence when the space is shared.
- **Retrieval is the point of no return.** Its Map tolerates **no** failure (the copy's tolerates
  100%): a fault means nothing copied and the archive untouched. What makes that free is that the
  **verb** tolerates two codes — `RestoreAlreadyInProgress` and `InvalidObjectState` — which is also
  what keeps the path unconditional on the storage class. **Do not "harden" the verb by removing
  them.**
- **The source is deleted only when EVERY object is confirmed copied**, and the gate is a **state** —
  the rollback arm cannot reach `DeleteSource`, asserted by walking the ASL graph, and an
  unrecognisable verdict fails closed. **And all or nothing on the ETag the plan recorded**: every
  copy is pinned to it, and delete-source heads every original first — one that changed refuses
  the whole deletion and removes the vault copy, because a partial one deletes into a vault the
  user holds no receipt for
  ([entry](#the-source-is-deleted-only-while-it-is-unchanged-since-the-plan-listed-it)). **It, not the queue, is what makes two overlapping archives of
  one space safe when their ids differ** — the group id orders their starts and nothing else. **One
  id sent twice is closed by a CLAIM**, not by the queue and not by the prefix listing, which two
  runs reaching it together both pass: inspect-source takes a create-only write on
  `archive/{requestId}/claim.json` after the listing and before anything else, so S3 decides which
  run proceeds. It **expires** with the admin prefix at 30 days, which is safe only while no second
  run of an id can start that late — a test reads the queue retentions and the machine's ceiling and
  fails when the margin closes.
- **A timeout does not stop a running verb.** The ceiling's door claims `delete-source`'s verdict
  create-only as `stopped` before it tells anyone "nothing was deleted", so a `delete-source` still
  running past the ceiling deletes nothing; a verdict to delete, or one that cannot be read, gets a
  sentence true either way ([entry](#a-timeout-does-not-stop-a-running-verb-so-the-timeout-door-claims-the-deletion-verdict)).

## The archive vault, and the four choices that shape the whole arc (SPEC-168)

## `GLACIER`, and why the other two were rejected

`arcommon.config.ARCHIVE_STORAGE_CLASS` is the single definition, and it determines the shape of
every spec after it. **`GLACIER` (Flexible Retrieval) is not readable**: a `CopyObject` whose source
is in it fails `InvalidObjectState`, so a restore is not a copy — it is `RestoreObject`, a 3-5 hour
wait, and *then* a copy. That is why SPEC-171 grows a `Wait`/poll loop no other plane in this repo
has, and why 170 must land before it.

**`GLACIER_IR` was rejected precisely because it would have removed all of that.** It is readable in
real time, which deletes the restore machinery entirely — and it is the most expensive Glacier
class. An archive the user can still read on demand is not an archive; it is data moved to a cheaper
bucket, and the feature's whole premise is that putting something away is deliberate and reversing
it is slow. **`DEEP_ARCHIVE` was rejected the other way**: ~4x cheaper again, but 12-48 hours to
restore and a **180-day** minimum, which turns an ordinary "I need that back" into a two-day wait.

The **90-day minimum storage duration is a property of the class, not a defect**, and the user has
to be told: an object archived on Monday and restored the following week is still billed for 90
days. SPEC-172's confirm dialog says so in user-facing wording.

The restore machinery is **unconditional** whatever the constant is set to — a class that needs no
restore still tolerates one being requested. A test forbids any branch on the constant anywhere on
the plane, because making the machinery conditional is how a config change silently deletes a code
path with nothing in the diff to show for it.

## Retention is a CEILING, not a WORM floor — and the lifecycle rule is unfiltered on purpose

Every object expires 2557 days (7 years) after creation. Nothing prevents an earlier delete, and
nothing may: SPEC-171's restore deletes the archived copy once it has been put back.

The expiry rule is **bucket-wide with no prefix filter**, and it is the exact **inverse** of the
admin bucket's `admin_lifecycle_rules_are_prefix_scoped` check. That check exists because *that*
bucket mixes `logs/` (retained forever) with expiring content, so an unfiltered expiring rule there
would silently delete the logs. This bucket holds exactly one class of object, so the risk runs the
other way: a prefix filter would be a silent way to leave some archived data unexpired past the
retention the feature promises. **S3 lifecycle can include a prefix but never exclude one**, so if a
second content class is ever put in this bucket the repair is *not* to add a filter — that would
leave the new class unexpired and this rule looking correct. It is to revisit the rule, and probably
to give the new class its own bucket.

**S3 Object Lock is out of scope for two independent reasons.** It requires bucket versioning, which
this project deferred by decision (2026-08-03); and in compliance mode nothing can delete an object,
not even root, which would make SPEC-171's cleanup of a restored archive impossible.

## The bucket the browser has no relationship with

No CORS configuration, no entry in the SPEC-140 `connect-src`, and the portal role holds **zero**
statements naming the ARN. The only route to archived bytes is a restore request through this plane.
The bucket's own policy is a `StringNotLike aws:PrincipalArn` Deny admitting the archive execution
role, the deploy role and the account root — so an identity policy that later grew a statement here
would still be refused. It denies `s3:RestoreObject` as well as the four ordinary actions:
`RestoreObject` is what makes a `GLACIER` object readable and is not covered by `GetObject`, so a
policy without it would leave any principal able to start a **billed** retrieval on someone's
archive.

What the browser *does* get is a **Deny** on `PutObject` / `DeleteObject` / `AbortMultipartUpload`
under `archive/` in both space buckets (FR-006). A user who can rewrite a receipt can misreport what
was archived. `AbortMultipartUpload` is included even though a `PutObject` Deny already blocks
multipart writes: without abort, a half-started upload cannot be tidied and its parts sit billed and
invisible. `GetObject`/`ListBucket` are untouched — the receipt is deliberately a plain text file
the user downloads and reads themselves, which leaves the no-preview rule intact. **The UI mirror is
owed and lands in SPEC-172**; an IAM Deny with no UI counterpart produces a bare `AccessDenied` for
a rule this application itself authored.

All of this is a **negative** claim, which is the kind that rots without anything looking wrong, so
`lambdas/test_archive_bucket_isolation.py` asserts it against the IaC rather than describing it.

## The key layout: the archived key carries its own origin, partitioned by space kind

`personal/{username}/archive/{uuid}/…` and `shared/{space}/archive/{uuid}/…` in the archive bucket;
`{root}archive/{uuid}/receipt.txt` in the space's own bucket.

**The archived key encodes its origin**, so `origin_key` reconstructs the source with no lookup at
all. That is what lets SPEC-170 rebuild every restore destination from one `ListObjectsV2` over the
archive prefix: **the receipt is a report, not a record**, exactly as SPEC-143 judges a table by
its shape rather than by the marker it also writes. The manifest exists only as a cross-check that
can fire when something is already wrong.

**The leading kind segment is the entire fix for a real collision.** Receipts live in each space's
own bucket, where the two namespaces cannot meet; the archive bucket is the first place they do.
Shared-space names are made unique against the shared-space registry only — **nothing anywhere
checks a proposed space name against the User Pool** — so a user `alice` and a space `alice` can
both exist today. Flat, they would share one archive prefix, and since SPEC-170 authorizes a restore
by *space* and then reads whatever sits at that prefix, a member of space `alice` could restore user
`alice`'s archived files into the shared space. The alternative fix — refusing to create a shared
space whose name matches an existing username — is **rejected**: it changes a shipped, unrelated
control plane, it cannot repair names that already exist, and it would make space creation depend on
the User Pool for a reason unrelated to space creation.

The `{uuid}` is browser-supplied and becomes a path segment in two buckets, so it is validated as a
UUID v4 **before it is ever concatenated**, at every builder rather than once at the front door, and
**lowercased** — S3 keys are case-sensitive, and a re-submitted id in different case would open a
second archive under a name that reads identically in every message and every listing.

## One plane, one `mode` branch, and no grant this spec did not need

**ONE machine serves both archive and restore**, branching on `mode` — SPEC-143's create/refresh
branch on the table-builder is the precedent, not a sixth module: the two verbs share the bucket,
the execution role, the key layout and the receipt, and a restore is meaningless without the archive
that produced it. The `Choice` guards **every** comparison with `IsPresent`, per choice rather than
once: a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default` does not cover
it. Its `Default` seeds a **reason code**, never `TerminalError` — notify-failure treats that one
name as evidence a verb's decorator already notified, so a seed wearing it would be silently
suppressed (the recorded `DiffMissingSeed` rule).

**The execution role holds no S3 grant on any data bucket at this stage, and the restraint matters
more here than on any other plane.** Archiving is the only operation in this repo that deletes a
user's data as a side effect of a copy. Every other plane's execution role carries a blanket
`Deny s3:DeleteObject` from its first apply and has that be an enforced property forever; **this one
cannot**, because SPEC-169 has to grant `DeleteObject` on the source buckets. So the property that
replaces it belongs to the spec that grants it — scoped to the space prefixes, never reaching
`athenaresults/`, `user_settings/` or any `DO_NOT_DELETE.txt`, with the commit gate in front of it —
and granting nothing today keeps that an explicit decision rather than an inheritance.

**No `TimeoutSeconds` yet, deliberately.** Nothing in this machine waits: no Map, no manifest, no
copy, no poll loop. A ceiling does **not** on its own reach `NotifyFailure` — AWS catchers cover
Task, Parallel and Map states but not top-level execution failures — so it must ship WITH an
EventBridge `TIMED_OUT` rule or it is SPEC-152 satisfied on paper and silent in practice. Two tests
are tripwires on exactly that: one fails the moment a `Map`, `Wait` or `Parallel` appears, the other
the moment notify-failure grows a second door without one.

## Two things the fleet's own guards caught while this was being written

**Containment moved to `cpcommon.paths` rather than being copied into `arcommon`** (SPEC-156).
`assert_inside_root` / `has_dot_segment` / `normalize_root` arrived on `fscommon.paths` with
SPEC-164; archive is the third plane to ask the identical question, and it is the one place where a
second copy that drifts is a **cross-tenant read**. `fscommon.paths` re-exports the three names, so
every file-send call site and test is unchanged. A test asserts `arcommon.paths` defines none of
them.

**`ARCHIVE_BUCKET` is not a `cpcommon.config` required variable.** The first attempt added it to
`_REQUIRED_VARS`, reasoning that the lazy `__getattr__` made it free for planes that never read it.
That is true of resolution and false of the contract: `_REQUIRED_VARS` is a **fleet-wide** set each
plane's Lambda environment must supply, and the change failed table-builder's guard immediately.
The value is `arcommon.config.archive_bucket()` instead — a **function**, not a module attribute, because a
constant resolved at import time in a layer runs for every attaching function and an unset variable
then crashes at **cold start**, where no test and no deploy can see it (PR #196). `cpcommon.config`
gained a public `require()` so a domain layer reaches for the fleet's one fail-fast reader rather
than writing a second.

> **Superseded in part (2026-09-01) — the CHECK, not the decision.**
> `test_the_common_environment_satisfies_every_import_time_require` was retired in #540. It also
> never had the reach its name implies: it read `infra/modules/table-builder` alone, so the
> paragraph above overstates it, as several other doc sites did. Keeping `ARCHIVE_BUCKET` out of
> `_REQUIRED_VARS` is unchanged and still right.
>
> **Restored, and this time across the fleet (2026-09-01).** `lambdas/test_fleet_environment.py`
> checks all 86 deployed functions. It does not demand the whole set on every plane, because that
> was never true — archive, file-ops and file-send reach no Athena workgroup on any branch and
> correctly omit it — so it refuses only a name a function's own import closure can reach while
> its Terraform withholds it. **That reachability is not what catches THIS decision, and the
> distinction is worth keeping straight:** `ARCHIVE_BUCKET` is read only by archive, whose
> Terraform sets it, so the reachability half stays green. What reddens is the pair of tripwires
> either side of it — the fleet guard's assertion that the required set is still exactly the four,
> and `user-directory-build`'s mirror of that set against its own block. Verified by adding the
> variable and watching exactly those two fail. The read itself is genuinely seen rather than
> merely absent: delete `ARCHIVE_BUCKET` from `infra/modules/archive/lambda.tf` in the same breath
> and seventeen of archive's eighteen verbs redden with it — all but `copy-objects`, the one whose
> closure never reaches `archive_bucket()`.

## The commit gate, and the four choices that make a deletion safe (SPEC-169)

## The source is deleted only when EVERY object is confirmed copied

Archiving is the only operation in this portal that deletes a user's data as a side effect of a
copy, and the failure mode it must never have is **"copied 900 of 1000, deleted 1000"**. So the
gate is a state, not a convention.

`collect-transfer-results` returns ONE BOOLEAN and `CommitOrRollback` branches on it: the
committing arm reaches `DeleteSource`, and the rollback arm **cannot** — asserted by walking the
ASL graph from the gate's default, because a `Catch` or a `Next` added anywhere on that arm could
reconnect it and nothing about the diff would say so. The `Default` is the ROLLBACK, so an absent
or unrecognisable verdict fails closed; the failure on the other side is deleting a user's only
copy.

**Three ways to be short, one verdict.** A reported item failure; an export accounting for fewer
items than the manifest listed; a manifest whose count disagrees with the plan it was built from.
The last is a check file-send cannot make — there a manifest line is one `(recipient, object)`
pair, so the two counts differ by design. Here they are the same number written twice, and a
disagreement is the one shape where every downstream count agrees with itself and is wrong.

**Both halves of the Map Run's export are read**, for SPEC-160's reason: Step Functions files a
child by its execution STATUS, and the batch copier deliberately succeeds while carrying per-item
failures. A `FAILED`-only collector reports universal success — and on this plane that reported
success is a deletion.

`plan.load` refuses a plan that is short of the `objectCount` it records, and that check is what
makes the gate's guarantee true rather than aspirational: a truncated plan produces a manifest
short of its lines, a copy that succeeds over it, and a gate that **agrees**, because both sides
of the comparison are short by the same amount.

## The rollback deletes what is THERE, not what it was told about

FR-004 says the rollback removes the objects the collector reports as copied. It is implemented as
a `ListObjectsV2` over the archive prefix, and the reading is deliberate. Keys are the unbounded
term — tens of thousands of them cannot ride a 256 KB state — but the listing is also the strictly
better answer: the prefix is `{kind}/{name}/archive/{uuid}/`, this request's alone, so everything
under it was put there by this archive and by nothing else, **including anything a batch copied
before it died and never reported**. A collector-supplied list would omit exactly those. Its
predicate ignores nothing, because the shared paginator's default drops zero-byte placeholders and
hidden segments and both are things this plane deliberately archives.

**A rollback that itself fails partially does not change the outcome.** The property that matters
is that the source is intact, and it is; the residue is billed at the GLACIER 90-day minimum, is
unreachable by the user (the browser has no relationship with that bucket) and is swept by the
7-year expiry. It is reported in the failure notification through its own reason code rather than
retried forever. The same disposition covers a collector that cannot read the export at all: that
is a whole-request terminal with the source untouched, and it does not roll back, because a
collector that cannot read the export cannot say what there is to roll back.

## The delete grant is the one this role could not inherit

Every other plane's execution role carries a blanket `Deny s3:DeleteObject` from its first apply.
This one cannot, so the narrower property is written out: `DeleteObject` on the two SPACE buckets
only, plus an explicit **Deny** under `athenaresults/`, `user_settings/`, `archive/` and on any
`DO_NOT_DELETE.txt` at any depth (`*` matches `/`). A Deny rather than a narrower Allow, because an
explicit Deny beats every Allow — including one a later spec adds without reading the file.

IAM is the SECOND line of defence. The first is the gate; the third is
`arcommon.delete.assert_deletable`, which checks the whole list **before issuing anything**, so a
key the policy would refuse fails the run rather than stopping a deletion half way through — after
some of the user's data has already gone. It fails loudly rather than filtering: a silent filter
would delete a source the archive is missing objects from.

Review found that check accepting `alice/../bob/secrets.csv`, which starts with `alice/` and passed
a prefix-only test. S3 resolves nothing, so no cross-tenant delete followed; it is closed because a
containment rule that holds only while every consumer stays careful is not a rule, and this
consumer is the one that deletes. **Containment is both of `cpcommon.paths`' rules, everywhere.**

## The request id is browser-supplied, so a reused one is refused twice over

**Both halves of this came out of review, and one of them could have deleted the wrong data.**

The request id is the whole identity of an archive: the copy plan, the archive prefix,
``_manifest.json`` and the receipt are all keyed on it alone (only the transfer manifest also
carries the execution). The queue's FIFO ``MessageDeduplicationId`` is that id, but its window is
five minutes against a three-hour ceiling, this arc's live checks submit hand-crafted messages, and
the browser producer that would mint a fresh id per submit is SPEC-172's. So a second request under
a used id is reachable, and nothing downstream noticed.

**delete-source takes the bucket, the root and the KEY LIST from a plan it re-reads.** The commit
gate upstream compares two values that both come from the state, so it cannot see a plan another
execution overwrote. Run 1 could therefore pass its own gate on its own counts and then delete run
2's selection — in either space bucket, since the grant covers both. ``plan.load`` now takes the
request and ``assert_describes`` compares the plan's request id, source bucket, source root and
object count against it; a mismatch is ``plan_superseded``, with the source untouched.

**The rollback made the second half worse than a duplicate.** A run under a used id that fails its
gate lists ``{kind}/{name}/archive/{uuid}/`` and deletes everything under it — including a
PREVIOUS, completed archive's objects, out of a bucket with versioning off. Unrecoverable. So
inspect-source now refuses up front when the archive prefix already holds anything
(``request_id_reused``), one ``ListObjectsV2`` before a single ``HeadObject`` is spent. It
**narrows rather than closes**, exactly as table-share's conflict guard does: two concurrent
executions can both find the prefix empty. What it removes is the ordinary case. **— Superseded
2026-09-20: the concurrent case is closed too.** inspect-source now takes a create-only claim on
the id immediately after this listing, so S3 decides between two runs that reach it together; this
listing stays because it is the cheaper and better-worded refusal for the ordinary reuse, and it
writes nothing at all. The refusal is told
to nobody: the objects under the prefix are the first run's, and that run's *"Archived"* is the
message to read ([the decision](control-planes.md#a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is-the-one-that-reports-data-quality-file-operations-archive)).

## An object this plane could copy but could not delete is refused, not archived

Two rules were each correct alone and disagreed with each other. The code's reserved-folder rule is
anchored at the SPACE ROOT on purpose — ``assert_not_reserved``'s own docstring says
``alice/reports/archive/`` is an ordinary folder the user made. The IAM Deny protecting the same
names cannot be anchored anywhere: ``*`` matches ``/`` in a resource ARN and IAM has no
single-segment wildcard, so ``*/archive/*`` covers every depth.

The gap between them was a real user-facing failure. Archiving ``alice/projects/`` containing
``alice/projects/archive/notes.txt`` would copy every object into Glacier at the 90-day minimum,
write its record, and then fail part way through the deletion with "contact an administrator" — a
full orphaned copy and an escalation, for an ordinarily-named folder.

It is refused at expansion time now, and refused **WHOLE** rather than excluded, which is SPEC-165's
rule: a silent exclusion drops the user's own data out of an archive that reports success. The
message names the folder so the user can rename it. A file merely CALLED ``archive`` is untouched —
the Deny needs a segment after the name, so the rule reads folder segments and not basenames.

## The artifacts are ordered most durable to least, and the receipt's failure is terminal

`_manifest.json` into the vault → the source deletion → the receipt into the user's own space,
matching the data-quality plane's report → notification → index. A receipt therefore only ever
exists for an archive that completed, and a run interrupted between any two states leaves something
an operator can read.

**The receipt failing fails the RUN**, even though the data is safely archived and the source is
already gone: a user with no receipt has no id and therefore no route to a restore. The message
says the data IS archived and names the request id, so the run is recoverable by hand.

**The manifest is a report, not a record.** Nothing may come to depend on it — SPEC-170 rebuilds
every restore destination from the archived keys themselves, because an archived key encodes its
own origin. An AST sweep over the plane enforces that for the specs that have not been written yet,
exempting docstrings by node identity (SPEC-165's recorded trap) and qualifying the import test,
because `cpcommon.transfer.manifest` is a different module with the same name.

Both timestamps come from `$$.Execution.StartTime`, stamped onto the state by the same `Pass` that
stamps the execution name. Two `now()` calls would disagree by however long the deletion took, and
a re-run would disagree with itself.

## Three caps, and the one the spec does not name

Each is COMPUTED by a test that reads `locals.tf` back, never asserted as a number.

`ARCHIVE_MAX_OBJECTS` **20,000** is sized by the copy plan held in memory — by inspect-source,
which builds and serialises it, and by delete-source, which loads it back. `ARCHIVE_MAX_BYTES`
**3 TiB** is sized by the machine's own `TimeoutSeconds` at a **makespan** rate
(`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s), never the aggregate the
same constants suggest multiplied together; the test adds the copy, the per-child overhead of
20,000 items in batches of 8, and the seven serial verbs (~8,100s against 43,200s). Unlike
file-send there is no product cap beside it: an archive has one destination, so the source cap IS
the transfer cap.

**`ARCHIVE_MAX_OBJECT_BYTES` 10 GiB is not in the spec, and the arithmetic above needs it.** A
batch is one round of the worker pool and **one object is one worker** — `copy_batch` hands a whole
object to a thread and `copy_one`'s multipart loop is serial — so nothing else bounds a single
object's copy time. S3 accepts objects up to 5 TiB, which is ~220,000s at the conservative rate:
240× the batch verb's timeout and 20× the whole machine's ceiling. Without it the makespan model
certifies the distributed case only, which is SPEC-166's recorded finding inherited rather than
rediscovered.

## The ceiling ships with its rule, again

`TimeoutSeconds` 10,800 is **top-level** (SPEC-157 settled that distinction), and it arrived in one
PR with the EventBridge `TIMED_OUT` rule, `ar_notify_failure`'s second door and its 15s → 60s
raise. AWS catchers cover Task, Parallel and Map states but **not top-level execution failures**, so
without the rule the ceiling terminates the run outright and the actor is told nothing — SPEC-152
satisfied on paper and silent in practice, on the one failure where the user has been waiting three
hours. `TIMED_OUT` only, never `FAILED`, or every caught failure double-notifies.

The door needs the same `DescribeExecution` fallback file-send's does, and for the same reason:
EventBridge caps an event at 256 KB and this plane's execution input is the Pipe's record, which
`ARCHIVE_MAX_ITEM_BYTES` deliberately allows to approach 200 KB — so the biggest selections, the
ones that run for hours, are exactly the ones the event alone cannot attribute. What the timeout
message may PROMISE is decided by where a timeout can land: the deletion is downstream of the gate,
so a timed-out archive has never deleted anything, whatever else it did. **Superseded:** the ceiling
can land while `delete-source` runs, and a running invocation outlives it — the promise is now earned
by the verdict record ([entry](#a-timeout-does-not-stop-a-running-verb-so-the-timeout-door-claims-the-deletion-verdict)).

## The receipt's paths name the ROOTS, and the expansion keeps what every other plane drops

The spec's illustrative receipt shows a selected folder as the original path. That would be wrong
for the key layout this arc shipped: `archived_key` keeps every object's path relative to the SPACE
root, so naming the selection pairs it with an archive prefix that does not correspond to it — and
a 200-item selection has no single original path at all. Rooted at the space root and the archive
root, the two lines are exact inverses of each other for every object, for every selection.

The expansion's ignore predicate is this plane's own, and it **keeps** what
`cpcommon.s3_listing.is_ignored` drops: zero-byte folder placeholders (an archived empty folder has
to come back, and nothing else in the plan records that it existed) and hidden or underscore-
prefixed segments (those are ignored because *Athena* ignores them, which says nothing about a
byte-for-byte copy of a user's own folder). It excludes only prefix markers and the portal-managed
root folders. An empty expansion is a REFUSAL, never a success: a receipt claiming zero files
archived is worse than a refusal, and an empty archive prefix is indistinguishable at restore time
from one whose objects have vanished.

## The restore guard, and the four choices that make it safe to start a bill (SPEC-170)

## The guard is absolute, and it runs before the retrieval

S3 has no move and no rename, so a restore is a copy and a copy overwrites. If the user has
re-created `reports/q1.csv` since archiving it, restoring on top destroys the newer file with no
trace and no versioning to recover from. So **any** occupied destination refuses the **whole**
restore: no skip, no overwrite, no merge and no "restore what fits". Partial restores around an
obstacle were considered and rejected — they leave a folder holding two generations of the same
data with nothing recording which is which, and the user cannot tell by looking.

**A `403` counts as OCCUPIED.** A key this role cannot head is a key it must not overwrite, and on
these buckets that is live rather than hypothetical: the execution role's own policy Denies it
beneath `athenaresults/`, `user_settings/` and `archive/`. Reading an ambiguous answer as "clear" is
the one mistake here that ends in data loss, so the guard fails closed on anything that is not a
proven 404 — including an error carrying no status at all.

**And it runs before any `RestoreObject`, which is why the arc splits at exactly this state.**
Glacier retrieval is billed and irreversible once initiated. Everything in SPEC-170 is verifiable in
seconds; everything in SPEC-171 takes 3–5 hours and cannot be cancelled. A guard on the far side
would report the same refusal and charge the user for the privilege. The property is asserted by
walking the ASL graph from the guard's failure branch and requiring that **everything** reachable
from it is the failure path itself — not by asserting "no path to a retrieval state", which passes
vacuously while no retrieval state exists and would go on passing forever.

The refusal names a **bounded sample** because the guard **short-circuits**: an archive of 200,000
objects must not issue 200,000 heads to report a conflict found in the first hundred. Having
short-circuited, it genuinely does not know the total — so the message says there may be more.
Implying the sample was exhaustive would send the user round the clear-and-retry loop once per
hidden collision. The sampled keys render **relative to the space root**, so the user reads a path
they recognise from the file browser.

## The bound is botocore's connection pool, not the thread count

`RESTORE_HEAD_CONCURRENCY`'s first value was 32, computed against "workers × timeout / latency",
which is the model that makes a head-heavy verb look like a scheduling problem. It is wrong in a way
its own arithmetic cannot show: `boto3.client("s3")` takes botocore's default
`max_pool_connections` of **10**, so threads past that do not each get a connection — they contend,
and urllib3 opens and discards sockets rather than reusing them. A pool of 32 buys throughput the
client cannot deliver *while every bound computed from it reads as satisfied*.

So the concurrency sits inside the client's ceiling at **8** — which is also, not coincidentally,
why `COPY_CONCURRENCY` is 8 — and the **timeout** is what pays for the work: 20,000 heads, 8 at a
time, at a pessimistic 100 ms each is ~250 s, and `locals.tf` gives the guard 600 s. A test reads
the ceiling off `botocore.config.Config` rather than restating it, because that is the term a later
"just raise the concurrency" would skip.

`RESTORE_CONFLICT_SAMPLE` (5) is a **presentation** bound and is documented as one: the guard has
usually seen only a handful, so the number is about what fits in a sentence a person reads.

## The lookup reads the KEYS; the record is a cross-check it can do without

`inspect-archive` derives every destination by listing the archive prefix and running each key
through `paths.origin_key` — the exact inverse of the writer — because the archived key encodes its
own origin. `_manifest.json` is consulted only to compare counts, and **absent, unreadable and
malformed are all tolerated**: a restore that refused for want of a convenience record would be
precisely the failure mode the self-describing key layout exists to prevent. Only a record that
**disagrees** refuses, which can fire only when something is already wrong.

That tolerance is what made SPEC-169's `test_no_restore_verb_requires_the_manifest` sweep survivable
rather than deleted. The exemption is the layer module alone; a companion test keeps **verbs** out,
including SPEC-171's, so the cross-check has one home and one tested tolerance.

The exclusion is by **exact key at the archive root**, never by basename: a user's own
`reports/_manifest.json` three folders down was archived like any other file and must come back.
Conversely the lookup applies **no ignore predicate at all** — SPEC-169's expansion deliberately
KEEPS zero-byte placeholders and hidden segments, so restoring through a filter the archive did not
write through would silently return less than was taken.

The restore plan goes to the admin bucket and only its **key** rides on the state, for the reason
every artifact on this plane does: at `ARCHIVE_MAX_OBJECTS` the list is tens of megabytes against a
256 KB payload limit, and `States.DataLimitExceeded` is caught by no `Catch` in this machine —
`States.ALL` does not match it and none names it. It is read back with the
same identity check SPEC-169's review added to the copy plan — the key is a pure function of the
request id, so a second run under a reused id overwrites it, and a guard that cleared **that** plan's
destinations would clear a restore for keys this run is not going to write.

## The space comes from the request, and the two ids are different things

Authorization is a question about the space the user's route names (SPEC-113's rule), never about
whatever the archive claims — so an archive belonging to another space resolves to an empty prefix
and is simply **not found**. `archive_not_found` therefore never distinguishes "never existed" from
"not yours"; the difference is an existence oracle over other people's archives.

`requestId` ≠ `archiveId` is enforced rather than conventional. The run and the archive are
different things: a refused restore must be re-submittable under a new run id, and a second attempt
at one archive is a new request rather than a duplicate of the first. A producer that conflates them
will do it on every request, and the symptom would surface only under a retry.

The pasted id is matched against `arcommon.paths`' **one** UUID regex before it is concatenated into
anything — the same rule `validated_request_id` uses, differing only in the refusal's wording,
because a second and laxer copy would be a second door into the same key. It is lowercased, so a
receipt retyped in capitals still resolves the prefix the archive was written under.

## One front door, one `Validated` Pass, and two message prefixes

The restore validator is a **branch of the existing verb**, not a second Lambda, and that is forced
rather than chosen: `ChooseMode` sits downstream of validate-authorize and reads `$.mode` off the
parsed request, while in the raw Pipe record the same field is inside an escaped JSON string ASL
cannot look into. A separate front door would need the branch to happen before anything had parsed
the body.

Both modes therefore return the **same five top-level keys**, because a shared `Validated` Pass
naming a path one mode lacks raises an uncatchable `States.Runtime`. `source` is the authorized
SPACE in both — the archive's source in one, the restore's destination in the other — and only its
`items` are archive-only. The unknown-field check is made **per mode**: a union of the two contracts
would accept a restore carrying a selection and an archive naming an archive id, and silently ignore
whichever the mode did not read.

The failure path carries `mode`, and `arcommon.messages` registers **two resolvers over one body
table**. The codes only one mode can reach are unambiguous; `forbidden`, `malformed_event` and
`invalid_request` are reachable by both and are exactly what a single "Couldn't archive that" prefix
gets wrong. `ValidateFailureSeed` supplies a literal `null` — its input is the raw error, so reading
`$.mode` there would raise on the failure path itself.

**`restore_archive_incomplete` does not reuse FR-005's proposed `archive_incomplete`.** SPEC-169 had
already registered that code for a copy that fell short, its body promises "nothing was deleted and
your files are exactly where they were" — meaningless about a restore — and the ASL seeds the
literal in `RollbackReturnedSeed`. One code cannot carry both sentences, and the shorter name
belongs to the arm that shipped first.

## This spec adds no IAM, and that is asserted rather than assumed

FR-006's additions were already in place: `SourceDataRead` grants the `s3:GetObject` a `HeadObject`
authorizes against, and `ArchiveVaultList`/`ArchiveVaultWrite` cover the vault — all SPEC-169's. So
there was no grants-first PR split to make, unlike 168 and 169.

The `GetObject`-not-`ListBucket` distinction is nonetheless pinned by a test, because the failure
mode of the wrong grant is a **false pass**: a role holding only the bucket-level listing permission
gets a 403 on every head, and a guard that read 403 as "clear" would then report every destination
clear and overwrite the lot. Both directions of that mistake come back to one statement existing.

## Review closed two holes, and one of them was a silent, unrecoverable deletion

**A user's own file at the SPACE ROOT called `_manifest.json` archived onto this plane's own
record.** An object's archive key is `{archivePrefix}{relKey}` and the record's is
`{archivePrefix}_manifest.json`, so the two collide for exactly one relative key. Nothing upstream
caught it: `assert_not_reserved` refuses selecting the space root as a *folder*, but naming that
file directly passes containment, the reserved-root rule and the marker rule. The copy would land,
`write-manifest` would **overwrite** it with the record, `delete-source` would then delete the
user's original — the vault has versioning off — and the run would report **success**. The archive
was also permanently unrestorable: the restore excludes that key as the record, counts one object
fewer than the record claims, and refuses `restore_archive_incomplete` for everything archived
beside it; archived alone, it restores as `archive_not_found` against a receipt the user is holding.

It is refused up front (`reserved_object_name`), for the whole request, rather than excluded —
SPEC-165's direction, because dropping it silently would archive everything else and delete the one
object it could not carry. Moving the record out of the archive prefix would remove the class
rather than the instance, and was **rejected**: FR-003 AC2 specifies the exclusion, so the record
living at the archive root is the spec's own model, and a sibling key would make the exclusion test
assert nothing. The rule is exactly as narrow as the collision — `reports/_manifest.json` three
folders down has a different relative key, collides with nothing, and archives and restores like any
other file.

**The guard did not short-circuit in the case FR-004 AC3 names.** The sample check sat after a full
round *and* required `RESTORE_CONFLICT_SAMPLE` collisions before returning — so fewer than five
meant no short-circuit at all. Measured: 20,000 heads to report a collision at index 3, when one
re-created file is the likeliest real conflict there is. It now stops at the round that finds the
first one. **The test that named the property could not fail**: its fixture used 64 *consecutive*
collisions, which fills the sample inside the first round, so it passed against the broken code — a
fixture that makes an assertion trivially true, which is the shape SPEC-163 records.

Two smaller ones, both about the wording rather than the data. A malformed **restore** was worded
as an archive failure, because `mode` came from the contract check's *return* and every refusal it
raises happens before that — so the wording mode is now seeded from the untrusted body first, which
is safe because the value selects between two fixed prefixes and reaches nothing else. And the
EventBridge `TIMED_OUT` door never passed `mode` at all: unreachable today, but SPEC-171's 3-5 hour
retrieval makes the timeout *predominantly* a restore event, so it now reads the mode out of the
same raw body the actor comes from and `restore_timed_out` ships beside `archive_timed_out` —
because what a timeout may PROMISE differs by arm, and "nothing was deleted and your files are
exactly where they were" says nothing true about a restore.

---

## Retrieval as the point of no return, and the four asymmetries the restore introduces (SPEC-171)

## The destination guard runs TWICE, because this spec turned a guarantee into a promise

SPEC-170's rule is absolute: **any** occupied destination refuses the **whole** restore, because S3
has no move and no rename, versioning is off, and a copy over a file the user re-created destroys it
with no trace. One check was sufficient while the guard and the copy were seconds apart — the
residual TOCTOU was an unlikely double-submit, the same one table-share and file-send carry.

**SPEC-171 put three to five BILLED HOURS between the check and the write, and spent them telling
the user a restore was in flight.** That is not the same window wearing a bigger number. It is a
window the plane itself opens and then invites the user to act inside: the receipt marker exists
precisely so somebody waiting hours knows something is happening, and somebody who knows their
restore is hours away goes and works in their own space. Re-creating a file there is the ordinary
case the guard was written for, arriving late — and the copy-back would have overwritten it,
reported **success**, and swept the vault.

`ReCheckDestinationClear` invokes the same verb over the same plan immediately before the copy-back.
It costs one round of heads (the guard's own 20,000-at-8 bound, ~250 s worst case) against a run
that has already waited hours, and it is what makes "any occupied destination refuses the whole
restore" true ~~at the moment of the WRITE~~ **— superseded 2026-09-15: when the copy-back STARTS,
which is not every write ([the group id entry](#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)) —**
rather than only at the moment of the PROMISE.

Two details are decisions rather than mechanics. **The refusal is worded differently**, because the
two passes leave the user somewhere different: before the retrieval nothing has been spent, and
after it the objects are out of Glacier and stay ready for `RESTORE_AVAILABILITY_DAYS`, so a prompt
second attempt costs neither the wait nor the bill again — a fact the user needs and cannot possibly
infer from "some files are already there". And **the stage is SEEDED BY THE MACHINE**, never
inferred from what else is on the state, for the same reason `update-receipt`'s three stages are:
"the retrieval has not run" and "the retrieval reported nothing" look identical from inside a
handler, and getting that wrong tells a user their retrieval is still warm when it was never made.

It **narrows rather than closes**, as table-share's and file-send's guards do — two concurrent
writers can still land a file between the second head and the copy. The difference in kind is what
matters: seconds of overlap is a double-submit, and hours is the user acting on a message this plane
sent them. **— Superseded 2026-09-15: the residual is not seconds.** The heads run once, before a
copy-back Map that runs for as long as the archive copy it mirrors, so the window before a late
object's write is most of that Map; and a second restore of the same archive runs beside this one,
because the FIFO group orders only the starts. **— And superseded again 2026-09-20: there is no
residual at the write.** Every copy-back line carries `ifAbsent`, so S3 refuses the write itself
whenever anything is at the key, however late it arrived. What these two passes still buy that the
condition cannot is the WHOLE-request refusal: the condition protects one object at a time and
reports the rest as landed, where a guard pass names the colliding paths and refuses before the
user has been told a restore is under way.
[The group id entry](#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)
has the repair.

## The retrieval Map tolerates NO failure, and the copy tolerates every one

`ToleratedFailurePercentage` is 0 on `RetrieveObjects` and 100 on `CopyBackObjects`, three states
apart in one machine. Both are right, and the reason is what each Map's failure would cost the
verdict after it.

The COPY must finish whatever happens, because a Map that aborted early leaves the gate after it
unable to tell "failed" from "not attempted" — on the archive arm that gate decides whether a user's
only copy is deleted, and on the restore arm it decides whether the archive is. The RETRIEVAL has no
verdict after it: a genuine fault means nothing was copied and the archive is untouched, so the
cheapest correct answer is to fail the Map Run and let the user re-submit.

**What makes that re-submission free is the two tolerated responses**, and without them the design
would be indefensible. `RestoreAlreadyInProgress` (HTTP 409) is the state the call wanted to bring
about, wearing an error's clothes — raised instead, a redriven execution or any re-submission would
fail on exactly the objects already on their way back, and each retry would bill a second retrieval
for the rest. `InvalidObjectState` is tolerated for a different reason: it is what S3 says when an
object is not in an archival class at all, so tolerating it is what keeps the restore path
**unconditional on `ARCHIVE_STORAGE_CLASS`**. Setting that constant to `GLACIER_IR` leaves this
machinery harmlessly in place rather than requiring a branch, which is how a config change deletes a
code path with nothing to show for it in a diff (SPEC-168's own rule, now load-bearing).

The retrieval is issued through a Distributed Map over the same manifest the copy-back reads, rather
than one verb with a longer timeout, because 20,000 `RestoreObject` calls is not work a single
invocation should be sized for — and the plane already knows how to fan out over a JSONL dataset.
**One manifest serves both Maps**: two would be two things that could disagree with the plan, and
the disagreement would surface as a restore that retrieved one set of objects and copied another,
with every count still agreeing with itself.

## Completion is the `Restore` header, and an ABSENT header is a failure

Nothing observable about an archived object changes when its retrieval completes. It stays
`GLACIER`; what appears beside it is a temporary readable copy that the `Restore` response header
describes. So the poll reads that header and nothing else, and there are three answers rather than
two:

- `ongoing-request="false"` — the temporary copy exists and the object can be copied.
- `ongoing-request="true"` — S3 is still working.
- **no header at all, on an object still in a Glacier class — nothing ever asked for this object.**

The third is why this is a module with its own suite rather than a boolean. Read as "not yet" it
would burn every one of the 84 poll iterations, wait seven hours, and then report `restore_timed_out`
for something that was never going to complete — a wrong cause on a run the user has been watching.
The mirror case matters too: an absent header on a NON-Glacier object means the object needs no
retrieval, so treating a missing header as a failure everywhere would refuse a restore of something
already readable.

**The poll samples, and its progress is an S3 pointer.** A per-object status list on the state is the
256 KB failure whose overflow escapes every `Catch` here (`States.ALL` does not match
`States.DataLimitExceeded` and none names it) — which on this plane is a run that told the user
nothing at all — so the record lives beside the plan in the admin bucket and only scalars ride. The
paging rule has two halves that are easy to conflate: `RESTORE_POLL_PAGE` is the granularity progress
is **recorded** at, and the invocation's own bound is the whole plan. One page per `Wait` was the
obvious reading and is wrong: every object was requested at once at one tier, so they finish
together, and sweeping 20,000 objects a page at a time would add twenty five-minute waits — over an
hour and a half — *after* the retrieval had already completed.

**S3 Event Notifications (`s3:ObjectRestore:Completed`) were rejected as the completion signal**, and
not because polling is nicer. They would need bucket notification configuration covering every
archive prefix, a correlation store keyed by object so an arriving event could be attributed to the
run that asked for it, and a second delivery path with its own at-least-once semantics — to replace
a poll inside a machine that is already sitting still for hours, and that the plane already knows how
to write. The poll costs one Lambda invocation every five minutes.

**The iteration cap lives in Python and not in the ASL `Choice`.** `poll-restore` computes
`exhausted` itself and the Choice reads a boolean, because a literal in the rendered machine plus a
constant in `config` is two homes for one number — and they would only ever disagree on a restore
that was already going badly.

## The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane

`RESTORE_MAX_POLLS × RESTORE_POLL_SECONDS` is **seven hours** against a tier whose documented worst
case is five. Every other timeout in this repo can be tight, because failing means re-running
something free. Here the cost is asymmetric in a way most timeouts are not: **giving up on a
retrieval that was going to finish makes the user pay for a second billed retrieval**, while waiting
two more hours costs one Lambda invocation every five minutes. AWS documents 3–5 hours as typical
rather than contractual, which is exactly the class of premise this project has been burned by
before.

That budget forced `TimeoutSeconds` from 10,800 to **43,200**, and the raise is not about data
volume: the archive arm's long pole is a copy, and the restore arm's is a *wait*. `TimeoutSeconds` is
a top-level ASL field on one machine serving two arms, so **the archive arm's backstop rose with
it** — a wedged archive is now reported after twelve hours rather than three. Accepted: it is a
backstop, not an expectation, and the alternative was killing healthy restores. A test asserts the
archive arm's own worst legal run still clears the ceiling by more than 4×, so the ceiling drifting
until it stops being a backstop for the arm that does not wait would fail the build.

## The restore's gate is the commit gate's MIRROR IMAGE, not its twin

Archiving's gate protects the SOURCE: nothing is deleted unless every object was confirmed copied.
The restore's gate looks identical — one boolean from one collector, `IsPresent`-guarded, failing
closed — and protects the ARCHIVE, for a reason that runs the other way.

**A partial restore cannot be rolled back.** The user's space already holds some of their own data,
and deleting it to make the operation atomic would destroy the very thing the restore was for. So
the failure arm deletes **nothing** — not the objects that landed, not the archive — and the archive
it keeps is then the only complete copy in existence. A restore that half succeeded and then deleted
its own source would be unrecoverable, versioning being off. A graph walk asserts no path from that
arm reaches `DeleteArchived`, the same way SPEC-169's walk asserts no path from its rollback reaches
`DeleteSource`.

`restore_incomplete` therefore has to say **three** things, and the third is the one an author would
leave out: how many objects came back, that the archive is intact and still restorable under the
same id, and that **requesting it again will report the files that DID land**. **— Superseded
2026-09-20: the second of the three may not be said as a fact.** A sibling restore can sweep the
vault after the message is sent, so the body now says the archive "was still complete when this
restore stopped" and only when a count of the prefix earned it; where the count does not add up it
becomes `restore_archive_cleared`, which claims nothing. The third is unchanged except that its
remediation is "move or rename" rather than "delete". Without that last
sentence the obvious next action produces a `destination_occupied` refusal that reads like a new bug
on top of the old one. It is also the one body on this plane that describes a partial outcome, so
`test_no_body_promises_a_partial_outcome_except_the_one_that_is` gained a named exemption
set rather than a skipped assertion — a second body drifting into partial wording has to be
argued for.

**The vault sweep's failure does NOT fail the run, where the source deletion's does.** Same
algorithm, opposite consequence: a half-deleted source means a user told their archive completed
while their files are still half there, and a half-swept vault costs storage in a bucket the browser
cannot reach that the 7-year expiry reclaims. So it is a `cleanupIncomplete` flag on a *successful*
run and the user is not told at all. Deleting inside the `GLACIER` 90-day minimum is an
early-deletion fee brought forward, not a defect — recorded because a later cost investigation would
otherwise read it as one.

## The receipt is rewritten, never re-rendered, and the counts come from the run

`arcommon.receipt` is still the single writer, but SPEC-171 rewrites **two lines by label** and
keeps every other line verbatim. The archive lines record the archive RUN, and its start time is the
one field no restore can recompute — so re-rendering the document from the restore's own state would
silently blank `Requested` on the only durable record the user has of what was archived and when. An
absent receipt (a **proven** 404) is composed fresh, losing only that one field; an **ambiguous**
read — a 403, or a fault carrying no status — raises rather than taking that branch, which is the
destination guard's fail-closed 403-is-occupied discipline pointed at a write.

**The marker runs before the retrieval, not after.** FR-006 AC4 asks for it "when retrieval is
initiated"; immediately before is the same guarantee and strictly safer, because there a
receipt-write failure costs nothing where a moment later it would fail a run the user had already
been billed for. It is also why that stage's failure contract differs from the other two: before the
bill a failed write fails the run, and after the data has landed it must not — the ASL `Catch` on
`UpdateReceipt` reaches the SUCCESS terminal, because the ordering is most durable to least (data
restored → receipt → notification).

One function serves all three stages and **the ASL seeds which one**, rather than the verb inferring
it from what else is on the state: "nothing has run yet" and "the run reported nothing" are
different facts that look identical from inside a handler. The seed carries the STAGE and the run
carries the COUNTS — an earlier version let the seed supply `restored`/`expected` too, so the
sentence written onto the receipt and the tokens in the notification had **two sources and could
disagree**, with nothing to say which was right.

## The metadata fix: a latent bug on all three planes, surfaced by a round trip

FR-003 AC5 asked for `MetadataDirective: COPY` on both copies. `CopyObject` has that directive and
defaults to it; **`CreateMultipartUpload` has no such directive at all**, and `UploadPartCopy` moves
bytes and nothing else. So every object over `MULTIPART_COPY_THRESHOLD` (5 GiB) came out of a copy
as `binary/octet-stream` with its user metadata gone — silently, and on table-share and file-send as
much as here.

It surfaced on this spec because an archive round trip is the first operation in this repo that
copies an object **twice** and hands it back to the user expecting it unchanged; a shared table is
read through Athena, which does not care about a content type. The fix is explicit on the single
path (stated rather than assumed, because the path beside it proves the default is not universal)
and a `HeadObject` on the multipart path whose headers are re-stated on the create call, skipping
anything the source does not carry so the two existing callers' requests are unchanged below 5 GiB.

**One thing `MetadataDirective` carries that the multipart path still does not: the object's TAG
SET.** `CopyObject` copies tags by default; `HeadObject` does not report them, so parity would cost
a `GetObjectTagging` per object over 5 GiB. Nothing in this portal tags an object, so it is
**recorded in `copy.py` rather than bought** — the moment a plane starts tagging, every object over
the threshold will start losing them silently.

**A test that fixtured only a small object would have passed while the bug lived on**, so the round
trip runs at both copy strategies. That is the same shape as SPEC-163's recipes that re-implemented
the gate they were testing: the fixture, not the assertion, is what decided whether the test could
fail.

---

## The archive surface: a confirm that is not a confirm, folder names as identity, and the first prefix write gate (SPEC-172)

## The one dialog in this app where the confirm is not the default, and Enter does nothing

Every other destructive confirm in this portal focuses Cancel because a stray Enter should not
delete a file. Archiving raises that from a courtesy to a structural requirement: it is the **only**
action here that removes the user's data and cannot be undone in the same sitting — getting it back
takes three to five billed hours.

So `ArchiveDialog` is built on `ConfirmDialog` **because of what `FormDialog` has**. `FormDialog`'s
`submitOnEnterRef` is a real affordance, and a dialog that merely declined to pass one would be one
refactor away from acquiring it. `ConfirmDialog` is not a form at all: focus lands on Cancel and
Enter cancels, by construction rather than by discipline. `RestoreArchiveDialog` makes the opposite
call for the opposite reason — one field, and Enter submits from it.

**The dialog does NOT say "This can't be undone."** `ConfirmDialog` will render that line on
request, the delete confirm uses it, and it would be the single false sentence in this dialog: a
restore is exactly that undo. What it says instead is how long one takes, which is the fact the user
actually needs and the one no button label can carry.

## The folder names ARE the archive ids, so the folder must stay visible

An archive is identified by a UUID the browser minted, and the user needs it back to restore. There
are three places it could come from: a notification, the receipt, and the folder that holds the
receipt. The notification is transient and the receipt is inside the folder — so the FOLDER is the
durable surface, and `archive/` is therefore the first app-managed root that is visible, unpasteable
and undestroyable at once.

**Amended: visible now means one click in, not top of the listing.** `archive/` sits inside the
`system_settings` group row with the other two folders the app fills — a collapse, not a hide, and
the distinction is the whole of what keeps this decision intact: the folder names are still the
durable surface and `ls` is still the index. What the grouping DID falsify was the prose, which sent
users to "your archive folder" at a root where it no longer appears; the restore dialog and both
help entries now name the `system_settings` → `archive` path, and they are load-bearing rather than
descriptive. A future change that collapses this row without carrying that wording is the failure
this paragraph exists to prevent — the id is needed at exactly the moment the user has nothing else
to go on.

That is also why this spec ships **no archive index, no archive browser and no picker of past
archives**. A cross-space index is the directory-shaped disclosure SPEC-158 declined; a per-space
one would be a second, weaker copy of a listing the file browser already renders. `ls` is the index.

**The receipt is downloaded and read, not previewed.** The project's no-in-browser-preview rule is
untouched, and this is the intended surface rather than a workaround: the ids are readable from the
folder names without opening anything at all.

## The write gate mirrors each bucket's own Deny, and averaging them gets one case wrong

`isWriteLockedPrefix` is the app's first rule about the prefix the user is STANDING in, as opposed
to a rule about a folder's name. It exists because IAM already denies writes beneath `archive/`, and
without a browser counterpart every attempt produces a bare `AccessDenied` for a rule this
application authored — the situation `undeletableRootFolderRefusal` exists to prevent for
`athenaresults/`.

**The two space buckets are denied differently**, and that asymmetry is structural rather than an
oversight:

- personal: `{bucket}/${aws:PrincipalTag/username}/archive/*` — anchored at the caller's own root,
  because in that bucket the prefix IS the principal tag;
- shared: `{bucket}/*/archive/*` — where the wildcard is the space slot, and **an S3 resource
  wildcard matches `/`**, so it reaches an `archive` folder at any depth.

Anchoring both at the root offers writes into a nested shared `archive/` that IAM refuses; applying
the any-depth rule to both refuses writes into a user's own `alice/backups/archive/` that IAM
permits. FR-004's criterion is both directions — "must not offer a write the policy refuses, and
must not refuse one it permits" — so the predicate takes the space kind. `archiveWriteLock.test.ts`
turns each `Resource` into a key matcher and runs the app's own predicate over the same keys;
deleting the shared branch reddens it (measured).

**The query results folder is the one deliberate exception to the second half, and it is a separate
predicate beside this one.** IAM permits a write beneath `system_settings/athenaresults/` and denies
the delete, so whatever a user writes there can never be removed — the folder marker's reason,
applied to a whole folder. `writeLockRefusal` refuses those writes in its own words and
`protected.assert_writable` refuses them at the object routes, which nothing legitimate writes
through: Athena delivers its results itself, under whichever role ran the query, and the browser
only copies them out. `isWriteLockedPrefix` and
`is_write_locked` still refuse only what the policy refuses, and the results rule is held against
its `DeleteObject` Deny by the same matchers, in both trees. **The data-quality reports folder is a
second exception, and it mirrors no Deny at all**: the plane reads its manifest back between verbs
from a key a caller can predict, so `assert_writable` refuses the root-anchored
`_data-quality-reports/` at the object routes, where only reads were ever legitimate.

**The refusal is `aria-disabled`, not `disabled`.** A `disabled` control is skipped by the tab order,
so its reason is reachable only by hovering — which is how "it's greyed out and I can't find out
why" happens. `Button.disabledReason` renders the reason as the accessible DESCRIPTION and swallows
the click, and deliberately does not put the text inside the button: content becomes part of the
accessible NAME, which every `GATED_SURFACES` row and journey test queries by.

## Only three outcomes needed a producer, and one of them had to be invented

FR-006 names nine terminal outcomes. Six were already reason codes in `arcommon.messages`, emitted
exactly once by `notifies_on_failure` or by the machine's `NotifyFailure` — a second producer for
them would be the duplicate SPEC-114's one-token-per-OUTCOME rule exists to prevent. What was
missing was what a failure table cannot carry: `archived`, `restored`, and `restore_started`.

**`restore_started` is the only "started" notification in this application**, and the reason is
specific to this plane rather than a general improvement: every other control plane finishes in
seconds or minutes, so silence until the outcome is honest there. Here it is three to five *billed*
hours, during which silence is indistinguishable from a request that was dropped. It is emitted
**after** `RetrieveObjects`, not before — that Map is where the bill and the wait actually begin, so
announcing earlier would promise a wait that a failed retrieval never starts.

**The producer cannot fail the run, and the ASL enforces it.** On the archive arm the source is
already deleted when it speaks; a raise would turn a completed archive into a reported failure with
the data gone. All three states carry `ResultPath: null` (two sit mid-machine, ahead of a wait, a
poll loop, a second guard and a copy) and a `States.ALL` Catch whose `Next` is the state they were
inserted in front of. The verb carries `@traced` and no `@notifies_on_failure` — that decorator
would report a failure of the NOTIFIER as a failure of the archive.

**The ASL seeds which outcome it is.** All three call sites carry identical keys, so nothing on the
state distinguishes them and inferring would mean guessing — SPEC-171 settled its two destination
guards the same way, for the same reason.

**The restored link is the SPACE ROOT.** A restore puts every object back where it came from, which
for any selection of more than one folder is several places at once; picking the first would send
the user to a folder holding part of what they asked for. The archived link is the receipt's own
folder, and both carry the recipient's full key including the space root — SPEC-167's finding, that
a root-relative prefix is silently discarded by the route and lands the user at their space root
looking like a link that worked.

## The restore's FIFO group id hashes the archive ROOT, not the bucket and the root

SPEC-170 FR-001 specifies the digest of `{archiveBucket}/{archiveRoot}` and left it owed to this
spec, which is the producer. The browser cannot produce it: SPEC-168 decided the browser has **no
relationship with that bucket** — no CORS, no `connect-src` entry, zero portal-role statements — ~~and
`test_archive_bucket_isolation.py` asserts the SPA's build env learns the archive QUEUE and nothing
else about the plane.~~ **— superseded:** that assertion went in the 2026-08-28 suite cut, and
SPEC-200 retired the fact — the SPA's configuration now names nothing of the plane, not even its
queue, because the restore is enqueued through the API, which derives this group id by the same rule.
`test_archive_bucket_isolation.py` asserts that neither space's portal-role template names the
archive bucket and that the browser's archive enqueue grant is retired.

Including it would also buy nothing. The group id's one job here is ~~that two restores of ONE
archive serialize~~ **— superseded 2026-09-15: that the restores of ONE archive share a group, which
orders their starts and does not serialize them, since the Pipe starts executions
`FIRE_AND_FORGET` ([the entry below](#the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is-not-absolute-at-the-write)) —**
and the archive root's own leading `personal/`/`shared/` segment — the segment SPEC-168
added precisely because nothing checks a space name against the User Pool — already makes it
globally unique. The bucket is one constant across every restore this app can make.

So the canonical string is `{kind}/{name}/archive/{archiveId}/`, mirroring `arcommon.paths.
archive_root`, and `docs/testing/e2e.md`'s hand-crafted command was corrected to
match so the live check exercises the rule ~~the browser reproduces~~ **— superseded by SPEC-200:**
the API reproduces (`apicommon.fifo`). A test pins the derivation and
names SPEC-168's browser isolation — not the test — as the decision to re-open if it ever fails.

## The group id orders the STARTS, not the runs, and the restore guard is not absolute at the write

> **Repaired 2026-09-20 by SPEC-237; the diagnosis above stands and the consequences it
> describes no longer do.** Every copy-back line is now a conditional write, so no restore overwrites
> anything — not a file the user edited, not a file a sibling restore put back — and the
> unconditional-`CopyObject` sentences below are superseded. One archive id is one run, by a
> create-only claim inspect-source takes after the listing, so the reused-id arm is closed rather
> than narrowed. **What remains true is the overlap itself and what it costs in REPORTS:** two
> restores of one archive still both run, both may send "started" and "restored", and a run whose
> sibling swept the vault first still reports an incomplete restore or fails as
> `archive_object_unreadable`. What no longer follows is data loss, because no message tells the
> user to delete anything and none calls the archive complete without counting the prefix.

Found 2026-09-15, auditing the module README's claim that two archives from one space, and two
restores of one archive, serialize. Neither does, and the same audit found the guard's own residual
understated.

**The premise was false.** This plane's Pipe starts its Standard machine `FIRE_AND_FORGET`, as every
plane's does — AWS allows a Standard workflow no other mode — and the message leaves the queue once
`StartExecution` returns, after which the Pipe sends the group's next batch. A `MessageGroupId`
therefore orders the starts, and a failed start holds the next one back until its retries run out;
nothing stops a second run beginning while the first is still going. The table-builder refresh and
file-ops each hold a lock for exactly this, and file-ops' live check watched two runs in one group
overlap on a Pipe identical to this plane's. **This plane's own live run already had**: two restores
of one archive submitted 25 s apart on 2026-09-09, where the second failed after its poll met the
vault the first had swept (`docs/testing/sessions.md`, *The archive and restore, run under §4.11's
approval gate*). The archive specs gave serialization as the reason for
both keys and this plane's prose carried it forward, while `arcommon.plan` already keyed each
manifest by execution so that two overlapping executions of one request could not clobber each
other.

**What overlap does, arm by arm:**

- **Two archives from one space, different ids: safe, and the commit gate is why.** Each run deletes
  only its own plan's keys, only once every one is confirmed under its own `{uuid}` prefix, and its
  rollback lists only that prefix. An overlapping object is either archived twice — two receipts,
  two `GLACIER` copies at the 90-day minimum — or deleted by one run before the other copies it,
  which fails the other's copy and rolls it back with nothing deleted. `DeleteObjects` reports a key
  the other run already removed as deleted, so neither run fails on the other's work.
- **One archive id twice, past the dedup window: unrecoverable, and already recorded.** [The reused-id
  entry](#the-request-id-is-browser-supplied-so-a-reused-one-is-refused-twice-over) says
  `request_id_reused` narrows it and does not close it. What it did not say is that the queue does
  not close it either.
- **Two restores of one archive: not billed twice, and not safe.** S3 answers the second
  `RestoreObject` with `RestoreAlreadyInProgress` while the first is in flight, and bills it as a GET
  once the first has finished, so the retrieval is spent once. Both runs pass the first guard, since
  nothing lands for hours, and each then polls on its own five-minute clock, so what follows depends
  on timing. The first to see the retrieval finish can restore a small archive and sweep the vault
  before the other polls again, and that poll then heads a missing object and fails as
  `archive_object_unreadable`, telling the user to contact an administrator. A second guard pass that
  runs after the other run has copied a file back refuses as occupied, over the restore's own files.
  If both second passes run before any copy lands, both copy back with an unconditional `CopyObject`,
  and if one sweeps the vault while the other is still copying, the other reports
  `restore_incomplete` over a restore that fully landed and rewrites the receipt to say the archive
  is intact, when it is gone — and the message tells the user to delete the files that came back
  and request again, which would destroy the only copy. A file the user edits after the first run
  restored it is overwritten silently if the second run copies it while the vault copy still exists.

**The guard's own residual was understated, with no overlap needed.** The second pass heads every
destination once, before the copy-back Map, and the Map then runs for as long as the archive copy it
mirrors. So the guard holds when the copy-back STARTS rather than at every write, and the residual
the [guard-runs-twice entry](#the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee-into-a-promise)
called seconds is most of that Map for an object copied late in it: a file the user re-creates at a
path not yet restored is overwritten by a single restore.

**Decided 2026-09-15 (Andrew): repair it with conditional writes, not a lock.** `CopyObject` and
`CompleteMultipartUpload` both take `If-None-Match: *` on the destination and answer `412` when the
key exists, which would make the guard hold at every write, against the user and a second restore
alike; and a create-only claim on the archive id would close the reused-id race that
`assert_archive_unused` only narrows. A per-archive restore lock was weighed and not chosen: it stops
the overlap and its misleading reports, but it brings acquire and release states and a staleness
limit above the 12-hour ceiling, and it leaves the single-restore window open. The overlapping
restore's duplicate and false-failure reports are the accepted cost — **except the incomplete
report's instruction to delete the files that came back**, which a spec review found would destroy
the only copy once another run has swept the vault. That one is not accepted (Andrew, the same day):
SPEC-237 holds every restore message to two rules, and counts the vault before any message calls the
archive complete.

**What the repair cost, measured rather than predicted.** The conditional write is one header on
two operations, and the work was in what a refusal MEANS: a batch re-raises one item's transient
fault after every copy has settled, so its retry meets its own earlier writes and every one of
them is refused. Read as "occupied", a retried restore would have reported the files it had just
put back as being in the way. So a `412` is settled by heading both objects and comparing ETag,
length, content type and user metadata — the run's own write always matches on both copy paths,
because the single copy carries metadata under `MetadataDirective` and the multipart create
re-states it, and every bucket here is `AES256`, which is what makes an ETag content-derived.
Under SSE-KMS none of this would work. A `409` is transient on both paths, and the multipart half
is safe for a reason worth writing down: AWS says a conflict there requires re-initiating the
upload and re-copying every part, and the engine satisfies that by construction, because it aborts
and raises so the batch's own retry runs `CreateMultipartUpload` again.

## A folder placeholder is not a file to the person reading the count

**Found by the live check on 2026-09-21.** A member of a shared space made a folder with **New
folder**, uploaded one 38-byte file into it and archived the folder. The notification said
"Archived 2 files", the receipt said `Files archived: 2`, and the restore said "Restoring 2 files".
The second "file" was the zero-byte `live0921_archive/` key that New folder writes. This plane
carries such keys on purpose, because an archived empty folder has to come back
([the expansion entry](#the-receipts-paths-name-the-roots-and-the-expansion-keeps-what-every-other-plane-drops)),
and every sentence was rendering `objectCount`.

**The fix changes the number a person reads, not what is copied.** `objectCount`, the plans, the
manifest's item count, the commit gate, `archive_is_intact` and the retrieval record all still count
objects, and the Maps still iterate every placeholder. A separate count is used for the wording, and
`arcommon.counts` holds the one rule for it: **a placeholder counts toward a number a person reads
only when it is the thing that fell short.** A success names files. A shortfall names "done of
total", where done is the files that landed and total is the files plus any placeholder that fell
short. The gap between the two is then the whole shortfall, so no sentence about a real shortfall
can read "only 1 of 1 file(s) could be copied". A selection with no files, only empty folders, reads "Archived 1 empty
folder". Andrew chose that wording and the exact treatment of the failure sentences on 2026-09-21;
the receipt still records `Files archived: 0` for it. Its failure sentences still count in
files ("only 0 of 1 file(s) could be copied"), which was left unworded. The two archive
shortfall bodies say "file(s)", as the restore's already did, because a total of 1 is ordinary.

**The rule's cost, accepted with it.** When only a placeholder falls short, the sentence counts it
as one of the files: "only 1 of 2 file(s)" over a one-file selection, and on a partial restore a
receipt whose `Files archived: 1` sits above "1 of 2 file(s) were written". The alternative was
"only 1 of 1", which reads as a run that did not fall short at all.

**Every copy-shortfall sentence needed the copy's per-item results to say which kind fell short, and
they said nothing.** The engine forbids echoing keys onto a failure record. So each transfer-manifest
line on both arms now carries a boolean `folder`, which is a bounded name and keeps that rule. The
one copy verb and the one collector echo it on both halves of the export. The collector adds a
`shown` block to its verdict, and the rollback, the receipt's restore line and the three
partial-restore bodies all read it, so they still share one source. Delete-source counts its total
from the keys it deletes. The rollback's residue stays a count of every object left behind, because
by the rule each one is a thing that fell short. One constant names the field for the builders, the
copy verb and the collector, because if the name drifted between the writer and a reader, every
failed placeholder would be counted as a file and nothing would fail.

**The file count rides inside `transfer`, not as a field of its own, and that is a deploy
constraint.** Deploy Infrastructure and Deploy Lambdas run in parallel on a merge, in no fixed
order. A notify payload reading a new `$.fileCount` would be an absent `Parameters` path whenever
the definition landed before the verb that writes it. That is an uncatchable `States.Runtime` on
`NotifyArchived`, which runs after the source has been deleted. The manifest builders already put
`$.transfer` on the state under the old code and the new alike, so the three notifies thread the
whole block. This is the precedent `$.cleanup` set. Each reader falls back to the object count when
the block, the field or the `shown` verdict is absent: a restore waits hours on the definition it
started with. A failure record with no flag, from a copy verb or a manifest older than it, returns
the object counts for the whole verdict rather than guessing its kind; only items an export never
covered are attributed, to files first and never below zero. An ASL walk reddens when any reader of
`$.transfer` is reachable before a builder, or after a state that reshapes the object — a `Pass`
naming its own keys, a Map or Catch with no `ResultPath`, or a Task that stops selecting its verb's
return.

**Deliberately left counting objects.** `restore_archive_incomplete`'s "holds {found} file(s) but
its record says {expected}" compares two object inventories. Manifests already written record only
`objectCount`, so no file figure exists for them, and the sentence fires only on an already-broken
archive and sends the user to an administrator. `too_many_objects` names a cap that the walk counts
in objects, not a count of the run. Over-coverage, an export that accounts for more items than the
manifest listed, is incomplete with nothing attributable, so its pair reads "N of N". The object
counts it replaced read "3 of 2" there.

**The other planes were checked, and none needs this.** File-send's expansion drops keys ending in
`/` (`fscommon/expand.py`), so its "(N files)" was already files. File-ops keeps placeholders, but
every number it renders counts selected items. Table-share renders no count, and its default listing
drops them anyway.

## The source is deleted only while it is UNCHANGED since the plan listed it

**Found by a data-loss audit of the control planes on 2026-09-26.** `delete-source` deleted the
plan's keys by name alone. The commit gate proves every object was copied; it says nothing about
whether the original stood still afterwards, and an archive at the caps copies for minutes to over
an hour. A file written over in that window — re-uploaded by its owner, or by any member of a
shared space — was deleted, leaving the vault's older copy as the only one, with versioning off.
The file-operations move had already closed the same shape with a HEAD-compare before its
deletion; this plane had not.

**The plan records each object's ETag** — from the listing, or the file head that already returned
it — and it is used twice. **Every copy line is pinned to it** (`srcEtag`, sent as
`CopySourceIfMatch`), so the vault holds exactly the planned version, and a file changed before its
copy fails that item and the commit gate rolls the archive back under the existing message. **Then
`delete-source` heads every original before deleting any**, and one that no longer carries the tag
refuses the whole deletion: it removes the vault copy by the rollback's own listing and fails
`source_changed_during_archive` — "N file(s) changed while they were being archived, so nothing was
archived and your files are exactly where they were. Please try again." An entry with **no**
recorded tag refuses the same way without being headed: a plan written before the tag existed
cannot say what the vault holds. An original that heads as **absent** is not a change, because a
Retry re-heads what its first attempt removed.

**And no original is deleted unless the vault holds every planned object at that moment**, counted
by the restore's own fail-closed `archive_is_intact`; a short count removes what is left of the copy
and fails `archive_copy_unconfirmed`, in the existing "we could not confirm that every file had been
copied" sentence.

**The verdict is RECORDED before it is acted on, and every later attempt follows the record** — the
second review's finding, and the one that made the shape above safe to retry. A delete batch that
throttles raises only after every other batch ran, so the state's Retry meets a first attempt that
has already partly acted, and re-deciding let the two paths undo each other in both directions,
each proved against a stateful fake: a deletion that re-decided as a refusal removed the vault copy
of the originals it had already deleted, and a refusal that re-decided as a deletion — the changed
file deleted in between, or a head that failed once — deleted originals whose copy was half gone
and reported success. So `delete-source` writes `source-decision.json` create-only beside the claim
before acting, and a Retry, a lost response or a redrive follows it: a recorded refusal finishes
removing the copy, and a recorded deletion never touches the vault — an original changed since the
verdict is kept, and the run fails `source_delete_incomplete` with the copy intact. **An original
already gone when the verdict is taken forbids a refusal**, since the vault may then hold its only
copy: the verdict is a deletion that keeps whatever changed, and if the vault cannot be counted
whole as well, nothing is decided or touched. The case is a run in flight at the deploy that brought
this in — its plan carries no tags and the old `delete-source` may have deleted part of it before
its Retry landed on the new one — found by a third review in the replay frame.

**All or nothing, and Andrew chose it over keeping per file.** The first shape kept only the
changed originals, deleted the rest and failed `source_delete_incomplete`; a review found that this
deletes into a vault the user cannot find — the receipt that names an archive is written only after
this state succeeds — and that the kept file then blocks a restore of it as a collision. Per file
is right on file operations because each item's outcome reaches the user; here nothing does.

**The residual is the time between an original's head and its batch's delete.** Deciding all or
nothing needs every head before the first delete, so a write landing after its head is not seen:
seconds for an ordinary archive, a few minutes at the object cap. A second sweep just before each
batch would narrow it and was computed against the budget instead of added — two sweeps at the
guard's modelled latency do not fit the Lambda ceiling with this file's headroom rule. The heads cost the
guard's arithmetic, so `delete-source` took the guard's 600s and a test reads it back. **Not a
conditional `DeleteObjects`,** for `focommon.delete`'s reason: whether S3 enforces the ETag on
these buckets is unproven, and a condition serialized and ignored deletes silently.

## A timeout does not stop a running verb, so the timeout door claims the deletion verdict

**Found on 2026-09-26 by a replay-frame review during the control-plane data-loss audit.** The
archive's EventBridge `TIMED_OUT` door always sent `archive_timed_out` — "Nothing was deleted and
your files are exactly where they were" — on the reasoning above that deletion is downstream of the
commit gate. Nothing stopped the 43,200 s ceiling landing while `delete-source` ran, or while
`write-receipt` ran after it: originals partly or wholly gone, no receipt, and a message saying
nothing was deleted.

**Reading the verdict record was the suggested fix, and it leaves a race.** Step Functions stops
waiting at the ceiling, but Lambda has no way to cancel an invocation, so a `delete-source` already
running goes on for up to its own 600 s. Caught while it is still heading originals, it has
recorded nothing: the door reads "no verdict" within seconds and promises, and the invocation then
records a deletion and acts on it. So the door does not read the record — it **claims** it, a
create-only `stopped` through `plan.record_source_decision`, and S3 decides which writer came first.
`delete-source` follows `stopped` at either of its reads by deleting no original, removing nothing
from the vault and failing `archive_timed_out`, the door's own sentence. An older `delete-source`
that does not know the verdict reads the record as unreadable and refuses to decide, so the deploy
order cannot delete over it. The claim is taken before the actor is known, because it protects the
originals whether or not anyone can be told.

**What each outcome tells the user, and Andrew chose all three.** No verdict (claimed as `stopped`),
`refuse` or `unconfirmed` keeps `archive_timed_out`, which the record now makes true. `delete` gets
`archive_timed_out_may_have_deleted`: the files "may already be archived and no longer in your
space", "Nothing has been lost", and the archive id to quote to an administrator — the id is the
archive's name, and the receipt that would carry it may never have been written. "Nothing has been
lost" holds because `delete-source` deletes only after counting the vault whole and only originals
still carrying the planned tag, and a timeout runs no rollback that could remove the vault. **A
claim or read that fails gets the same hedged sentence** rather than the promise, because the promise
is the one sentence that can then be false. A restore claims nothing: it deletes no original.

**The key comes from the VALIDATED id, not the raw body's.** `validate-authorize` lowercases the
browser's id before any verb keys on it, and the door reads the Pipe's raw record — so an id sent in
capitals would have found no verdict under its own spelling and promised. The door runs it through
`paths.validated_request_id`, and an id that fails that check was refused before any verb ran.

**Not repaired here: results-conversion's timeout sentence** also promises ("Nothing was saved")
from outside the run while its convert verb can outlive the ceiling. It is left because that ceiling
is sized above the longest path a test computes, so reaching it at all means that arithmetic was
wrong.

