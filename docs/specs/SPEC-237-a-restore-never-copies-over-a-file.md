# Spec: A Restore Never Copies Over a File, and One Archive Id Is One Run

**ID:** SPEC-237
**Status:** Completed
**Last Updated:** 2026-09-15
**Depends On:** SPEC-169, SPEC-170, SPEC-171

## Overview

Archiving is the one operation in this portal that deletes a user's data, and restoring is the one
that writes into their space after hours of silence. The plane was built on the belief that its FIFO
queue lets only one archive per space, and one restore per archive, run at a time. It does not: the
Pipe starts each run and moves on, so two runs in one group overlap. Most of that is harmless, and
two parts are not. **A restore can overwrite a file the user has edited since**, whether a second
restore of the same archive lands on it or the user simply saves a file while a long copy-back is
still running. **A single archive request sent twice can have its second run delete the first
run's finished archive** after the first has already deleted the source. And **when two restores
overlap, the messages can tell the user to delete the only copy of their files.** This spec makes all
three impossible: a restore never writes where a file already exists, an archive id belongs to
exactly one run, and no restore message calls an archive intact without looking or suggests deleting
anything. It does this with S3's own conditional writes rather than a lock.

### What was checked, and how

- **The overlap is documented by AWS and has been observed here.** A Standard workflow target must be
  invoked asynchronously, and the Pipe deletes a message once `StartExecution` returns and then sends
  the group's next batch
  ([targets](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes-event-target.html),
  [SQS source](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes-sqs.html)). This
  plane's own live run had two restores of one archive overlap on 2026-09-09
  (`docs/testing/sessions.md`, *The archive and restore, run under §4.11's approval gate*). The
  consequences, arm by arm, are in the register entry *The group id orders the STARTS, not the runs,
  and the restore guard is not absolute at the write* (`docs/decisions/archive-and-restore.md`).
- **The copy-back overwrites.** `cpcommon.transfer.copy.copy_one` issues `CopyObject` and
  `CompleteMultipartUpload` with no condition. `ReCheckDestinationClear` heads every destination once,
  before the `CopyBackObjects` Map, and the Map then runs for as long as the archive copy it mirrors.
- **S3 can refuse the write.** `CopyObject` and `CompleteMultipartUpload` both accept
  `If-None-Match: *` on the destination and answer `412 Precondition Failed` when the key exists, and
  `409 ConditionalRequestConflict`, meaning "retry", when a concurrent write races it
  ([CopyObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CopyObject.html)). `CopyObject`
  gained the header on 2025-10-29
  ([announcement](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-s3-conditional-write-functionality-copy-operations)).
  **The botocore on this Mac is 1.35.99 and its `CopyObject` has no `IfNoneMatch`** — measured by
  reading the service model; `CompleteMultipartUpload` and `PutObject` do. The Lambda image carries
  its own botocore, pinned by the base image's digest.
- **A retried batch meets its own writes.** `copy_batch` re-raises one item's transient fault for the
  whole batch once every copy has settled, and the Map's `Retry` re-runs the batch, so items the first
  attempt copied are copied again. Unconditional, that is harmless and the engine's docstring calls
  copy idempotent. Conditional, each of those items answers `412`.
- **All three buckets use `AES256` (SSE-S3)**, so a single-part object's ETag is the MD5 of its bytes,
  and a multipart object's ETag is derived from its parts' MD5s. `HeadObject` on a `GLACIER`-class
  vault object returns its ETag; `arcommon.retrieval` already heads them.
- **The reused-id race is known and narrowed, not closed.** `arcommon.plan.assert_archive_unused`
  lists the archive prefix, and two concurrent runs of one id can both find it empty. The copy plan is
  keyed on the request id alone, so the losing run of such a pair can overwrite the winner's plan.
  The admin bucket's `archive/` prefix, where that plan lives, expires after
  `admin_results_retention_days` (30).
- **Restore messages tell the user to delete files, and state the archive's condition as fact.**
  `destination_occupied`, `destination_occupied_after_retrieval` and `restore_incomplete` each say
  "move, rename or delete"; `restore_incomplete` says "The archive is still intact", `restore_timed_out`
  says "the archive is untouched", and the incomplete arm rewrites the receipt to "The archive is
  intact" (`arcommon/messages.py`, `arcommon/receipt.py`). When two restores of one archive overlap,
  the files those messages name can be the other run's output, and that run sweeps the vault when it
  finishes — `DeleteArchived` is reachable only from a complete restore — so a user who follows the
  instruction deletes the only copy. A claim about the archive is also only true when it is made: a
  sibling can sweep the vault after the message is sent. Each round of this spec's review found
  another sentence of this kind, which is why FR-007 is a rule enforced over the whole table rather than a
  list of sentences. It is live today, independent of the rest of this spec.
- **No second run of an id can outlive a 30-day claim.** The request queue keeps a message for SQS's
  default four days, the DLQ keeps one for fourteen and is drained into a notification rather than
  sent back (`infra/modules/archive/sqs.tf`), and the machine's ceiling is twelve hours.
- **The infra and Lambda deploys are not ordered.** `deploy-infra.yml` and `deploy-lambdas.yml` both
  fire on a push to `main` touching `infra/modules/**`, with nothing sequencing one after the other.

### The decisions, made while authoring

1. **Conditional writes, not a lock** (Andrew, 2026-09-15). A per-archive restore lock would stop the
   overlap and its misleading reports, but it brings acquire and release states and a staleness limit
   above the 12-hour ceiling, and it leaves the single-restore window open. The conditional copy closes
   both windows, and the overlapping restore's duplicate and false-failure reports are the accepted
   cost — except any report that could lead a user to delete the only copy, which decisions 11 and 12
   remove.
2. **A `412` is resolved by comparing the bytes' identity, not read as "occupied".** Otherwise every
   batch retry would report the files it had just restored as collisions. When the destination and
   the source both head with the same ETag, length, content type and user metadata, the item counts
   as copied: it is this run's own earlier write, or an object matching it in all four, and in either
   case nothing is lost when the vault is swept. **Those four, not everything the copy carries** —
   the multipart path also re-states content encoding, disposition, language, cache control, expiry
   and a website redirect, and comparing those would risk a false collision whenever S3 renders one
   back differently from the way it was supplied, which is the failure this resolution exists to
   prevent. The residual is recorded in the register entry. Both copy paths carry the
   content type and user metadata (`MetadataDirective: COPY`, and the multipart path's carried
   headers), so the run's own write always matches; a user's file with the same bytes but different
   metadata reads as occupied, which keeps the archive. A head that fails transiently raises
   `TransientError`, like every transient fault in a batch; any other failed head, or a head that
   returns no ETag or no length, resolves to occupied. The copy-back uses the part
   size the archive copy used, so the same bytes give the same multipart ETag; if
   `MULTIPART_PART_SIZE` ever changes, a retried object over 5 GiB reads as occupied, which keeps the
   archive and loses nothing.
3. **A `409` on a conditional write is transient here, and that differs from results conversion on
   purpose.** `rc_convert` reads a `409` as occupied because a conversion writes one object once.
   A batch copy retries, and after the retry the `412` comparison decides; reading a `409` as occupied
   would turn a write race with this run's own earlier attempt into a false collision.
4. **`cpcommon.cas` tells the two codes apart for everyone.** `cas.is_precondition` collapses `412` and
   `409` because a compare-and-set retries on either, and `test_the_precondition_predicate_has_not_reappeared`
   forbids naming the codes outside `cas.py`. This spec needs them apart in two places, so `cas` gains
   `is_precondition_failed` (`412`) and `is_conditional_conflict` (`409`), and `is_precondition` becomes
   their union. No new exemption is added to the gate.
5. **Only the copy-back is conditional.** The archive's copy into the vault writes under a prefix
   that FR-005 makes one run's alone, so a condition there buys nothing and costs a comparison on
   every retried batch.
6. **The claim lives in the admin bucket, beside the copy plan, and is taken after the listing.** Not
   in the vault: the restore rebuilds a destination from every key under the archive prefix, the
   rollback and `DeleteArchived` list and delete the whole prefix, and a claim written at `GLACIER`
   could not be read back to see who holds it. It names the execution, not the request, because a
   request id identifies the message and a `Retry` of the same execution must recognise its own claim.
   It is taken **after** `assert_archive_unused` and before anything else is written: the listing still
   refuses an id reused long ago without writing anything, and the claim is the atomic step that
   decides between two runs racing past the listing together. It needs no release — an id is one run
   for good — and it expires with the admin prefix after 30 days. That is safe because no second run
   of an id can start that late: the queue and the DLQ hold a message for at most fourteen days, the
   DLQ is never sent back, and a run lasts at most twelve hours. An id replayed by hand after the claim
   has expired meets either a vault prefix still holding its archive, which the listing refuses, or an
   empty one — swept by a restore or emptied by a rollback — where there is nothing to destroy. The
   bound is pinned by a test, because `admin_results_retention_days` is shared by several prefixes
   and nothing else stops a later cost cut from shortening it below the queue's retention.
7. **The second guard pass stays.** It still refuses the whole restore, up front and with the paths
   named, when something is already in the way; the conditional copy is what makes the rule hold for
   anything that arrives after it.
8. **The runtime is proven at image build, not at import.** A botocore without the parameter rejects
   the argument at the call, which here is a restore failing its copy-back after its bill is spent.
   The image build already asserts facts about its own dependencies in a `RUN python -c` step, and an
   import-time check would fail only at a cold start.
9. **The new message gives a count, not a list of paths.** A sample would put destination keys on the
   collector's return; the whole-restore refusal before the copy already names paths.
10. **The ASL reorder deploys before the claim.** Because nothing orders the two deploys, a claim that
    reached inspect-source before `StampExecution` moved ahead of it would find no execution name on
    every archive. Moving `StampExecution` first is inert on its own — inspect-source already passes
    its input through — so it lands and deploys ahead of the code that reads it.
11. **Restore messages follow two rules, and a test holds the whole table to them** (Andrew,
    2026-09-15, to fold the hazard into this spec). No sentence tells the user to delete anything —
    "move or rename" keeps the bytes whoever they belong to, and a user who wants a file gone does not
    need the app to suggest it. And no sentence states the archive's present condition as fact,
    because a sibling restore can sweep the vault after the message is sent; the one permitted form
    is time-scoped and earned by counting (decision 12). The population is every code the restore
    resolver can render — it registers the whole table — less an explicit set only the archive arm
    raises, so a code added later is checked by default. The test searches for destructive verbs after
    stripping an explicit allowlist of negations, and the safety sentence is a suffix the restore
    resolver adds to every message rather than a sentence each body must remember. Per-sentence fixes
    were tried first, and each review round found another sentence; a verb list with a looser
    negation rule let eleven of seventeen destructive sentences through when it was measured.
12. **The incomplete arm counts the vault, says only what the count proves, and fails closed.** It
    compares the archived objects under the prefix with the plan's `objectCount`, using the exclusion
    predicate the plan was built with. A full count earns "the archive was still complete when this
    restore stopped" — true when said, and phrased so it stays true after a sweep. Anything else,
    including a listing that still fails after two in-verb retries, selects the cleared outcome, whose
    body gives the counts and does not claim the rest came back: a wrong "cleared" costs a user asking
    an administrator, and a wrong "intact" can cost the only copy. The retries are bounded well inside
    the verb's 30-second timeout; a verb killed anyway surfaces as `Sandbox.Timedout`, reaches the
    state's `Catch` and the generic failure message, which makes no claim about the archive.

## Scope

### In Scope

- A per-item `ifAbsent` flag in the shared copy engine, with the `412` comparison and the `409` retry.
- `cpcommon.cas` split into its two codes.
- The restore's copy-back marked conditional; the archive's vault copy left as it is.
- A distinct outcome and message for a restore that met an occupied destination at the write.
- A create-only claim on the archive id, taken after the listing and before any other write.
- A build-time assertion that the image's botocore accepts the condition.
- Two rules for every restore message, held by a test over the whole table; the incomplete arm's
  vault count; the `restore_archive_cleared` outcome and the reworded bodies.
- Every site that states the guard is not yet absolute at the write corrected, and a live check
  recorded as owed.

### Out of Scope

- **A lock**, per decision 1.
- **Preventing two restores of one archive from both running.** They still both run. Both may send
  "started" and "restored" messages. Where one sweeps the vault before the other finishes copying,
  the second reports an incomplete restore over files that all landed; where it sweeps before the
  other has even polled again, the other fails as `archive_object_unreadable`. Those misleading
  reports are the accepted cost; what this spec removes is the overwrite, and every sentence that
  could lead a user to delete the only copy (FR-007).
- **A conditional vault copy**, per decision 5.
- **Claiming a restore's request id.** Two runs of one restore request write the same request-keyed
  plan with the same content, their manifests are execution-keyed, and the conditional copy-back is
  what protects the user.
- **The other planes' FIFO prose**, which makes the same serialization claim; that is separate work.
- **Changing file-ops' conditional-delete classifier or `rc_convert`** to use the split predicates.
  Both keep their gate exemptions; moving them is a refactor with no behaviour to gain here.
- **Removing either guard pass**, per decision 7.
- **Changing `MULTIPART_PART_SIZE`.**
- **IAM.** Conditional writes need no action beyond `s3:PutObject`, and the heads and the claim's
  read-back use grants the plane already holds, `s3:GetObject` on the admin `archive/*` prefix among
  them. FR-006 asserts the rendered policy is unchanged.

---

## Functional Requirements

### FR-001: The copy engine can refuse to overwrite, per item

#### Description:

A manifest line may carry `ifAbsent: true`. For such a line, `copy_one` passes `IfNoneMatch="*"` to
`CopyObject` on the single-copy path and to `CompleteMultipartUpload` on the multipart path.
`CreateMultipartUpload` and `UploadPartCopy` carry no condition, because S3 accepts none there. A
line whose `ifAbsent` is present and is not a boolean fails its item as malformed, rather than being
copied unconditionally. A line without the key produces exactly the requests it produces today, for
every caller: table share, file send, file-ops and the archive's own vault copy.

#### Acceptance Criteria:

- [ ] A conditional line at or under `MULTIPART_COPY_THRESHOLD` issues `CopyObject` with
      `IfNoneMatch="*"`; one over it issues `CompleteMultipartUpload` with `IfNoneMatch="*"`, and its
      create and part-copy calls carry no `IfNoneMatch` — asserted on the recorded arguments.
- [ ] A line with no `ifAbsent`, or with `ifAbsent: false`, issues calls whose arguments are equal to
      today's on both paths — the assertion `test_an_item_with_no_storage_class_names_no_storage_class_at_all`
      makes for the storage class.
- [ ] A line with `ifAbsent: "true"` (a string) fails its item with the caller's `failure_reason` and
      issues no copy.
- [ ] A `409` on a conditional write raises `TransientError`, so the batch retries rather than failing
      the item; on an unconditional line the classification is unchanged.
- [ ] A multipart copy whose completion answers `412` aborts its upload, then resolves as FR-002 says.
- [ ] `cpcommon.cas` exposes `is_precondition_failed` and `is_conditional_conflict`,
      `is_precondition` returns their union for every input the existing tests give it, and
      `test_the_precondition_predicate_has_not_reappeared` passes with no new exemption.

### FR-002: A refused write is resolved as already copied or as occupied

#### Description:

When a conditional write answers `412`, `copy_one` heads the destination and then the source. If both
succeed and their `ETag` and `ContentLength` are present and equal, and their `ContentType` and
`Metadata` are equal, the item is copied, and `copy_one` returns as if the write had succeeded. Otherwise it raises `DestinationOccupied`, and `copy_batch`
records the item with the caller's `occupied_reason` instead of `failure_reason`. A head that fails
transiently raises `TransientError`. A head that fails any other way — a `403`, a `404`, anything
unrecognised — or returns no ETag or no length resolves to occupied, and a failed destination head
means the source is not headed. `occupied_reason` is a keyword argument of `copy_batch` that defaults
to `None`, meaning the caller's `failure_reason`, so no existing caller changes.

#### Acceptance Criteria:

- [ ] A batch retried after one item's transient fault, whose first attempt copied the other items,
      reports every item copied and none occupied, at both copy sizes — driven through `copy_batch`
      against a fake S3 that honours `IfNoneMatch` and computes ETags as SSE-S3 does (the MD5 for a
      single copy; the MD5 of the part MD5s with `-N` for a multipart one).
- [ ] That test reddens when the resolution is replaced by "every `412` is occupied".
- [ ] A destination holding different bytes fails its item with `occupied_reason`, and the fake
      records no write to that key; so does one holding the same bytes under a different content
      type.
- [ ] A destination whose head answers `403`, and a source whose head answers `404`, each fail the
      item with `occupied_reason`; neither is counted as copied.
- [ ] A transient fault on either head raises `TransientError` out of `copy_batch`.
- [ ] `test_every_absence_site_in_the_tree_is_dispositioned` passes, with a `DISPOSITIONS` row for the
      comparison's head saying why a `403` and a `404` may give the same answer here: both resolve to
      occupied, which never overwrites.
- [ ] Each of the four existing callers' requests is unchanged: none of them sets `ifAbsent`, so none
      can reach the comparison.

### FR-003: The restore's copy-back is conditional, and the archive's vault copy is not

#### Description:

`build-restore-manifest` writes `ifAbsent: true` on every line. `build-transfer-manifest` writes no
`ifAbsent` at all. `archive-copy-objects`, the verb both arms share, passes a new per-item reason,
`destination_occupied_during_copy`, as `occupied_reason`. It is registered in `arcommon.messages`
beside `copy_failed`, the per-item reason it is a sibling of, with a body that is true for the one
file it would describe: that file was not restored because a file appeared at its path, and nothing
was overwritten. Nothing raises it as a whole-request refusal.

#### Acceptance Criteria:

- [ ] Every line `build-restore-manifest` writes carries `ifAbsent: true`, and no line
      `build-transfer-manifest` writes carries the key — both asserted by driving the verbs, in the
      shape of `test_the_two_existing_planes_write_no_storage_class_into_their_manifests`.
- [ ] `archive-copy-objects` passes `occupied_reason="destination_occupied_during_copy"`, asserted on
      the recorded `copy_batch` call.

### FR-004: A restore that meets an occupied destination keeps the archive and says so

#### Description:

`collect-transfer-results` counts the failures carrying `destination_occupied_during_copy` and returns
the count as `transferOutcome.occupied`, `0` when there are none, on both arms. An item that did not
land already makes the verdict incomplete, and the restore gate already routes an incomplete verdict
to the arm that deletes nothing, so the archive is kept. On that arm, when `occupied` is above zero,
`update-receipt` raises `restore_incomplete_occupied` instead of `restore_incomplete`, with this body
under the restore prefix:

> {restored} of {total} file(s) were restored to your space. {occupied} of the rest were not, because
> a file appeared at the same path while the restore was copying - nothing was overwritten. The
> archive was still complete when this restore stopped, so it can be requested again once the paths
> are clear: move or rename the files now in the way, including the ones this restore put back.

"Of the rest" is deliberate: when some items also failed for another reason, `occupied` is less than
`total - restored`, and the sentence stays true without explaining the difference. The body obeys
FR-007's rules, and it is raised only when FR-007's count found the archive complete.

#### Acceptance Criteria:

- [ ] A copy-back export with 2 of 5 items failed as occupied yields
      `transferOutcome.complete == false` and `transferOutcome.occupied == 2`, and the run's
      notification carries `restore_incomplete_occupied` with `restored=3`, `total=5`, `occupied=2`.
- [ ] An incomplete restore with no occupied items still raises `restore_incomplete`, with the body
      FR-007 sets.
- [ ] Every collector return carries `occupied`, including the archive arm's and a return with no
      failures; `test_a_complete_transfer_commits`, which compares the whole outcome, is updated to
      expect it.
- [ ] `test_every_marker_in_every_body_can_be_filled_by_somebody` passes with `occupied` added to its
      fillable set, commented with where it is filled.
- [ ] `test_no_body_promises_a_partial_outcome_except_the_one_that_is` passes with
      `restore_incomplete_occupied` added to `_DELIBERATELY_PARTIAL`, and the set's comment argues
      the second member: it is the same asymmetry as `restore_incomplete`, reached by a different cause.
- [ ] `test_no_path_from_the_partial_restore_reaches_the_archive_deletion` passes unchanged: the new
      outcome adds no edge.

### FR-005: One archive id is one run

#### Description:

`StampExecution` moves ahead of `InspectSource` on the archive arm, so `$.execution` — the name and the
start time — is on the state when inspect-source starts, and inspect-source keeps echoing its input so
it survives. After `assert_archive_unused` and before anything else, inspect-source claims the id by
writing `archive/{requestId}/claim.json` to the admin bucket with `IfNoneMatch="*"`, its body
`{execution, requestId, claimedAt}` taken from `$.execution` so a re-run writes the same bytes. The key
is derived in `arcommon.plan` beside the plan's, under the prefix the plane's grant and lifecycle
already cover. On a `412` (`cas.is_precondition_failed`), inspect-source reads the claim back: this
execution's name proceeds, because a `Retry` of inspect-source is not a reuse; another execution's
name refuses `request_id_reused` before the copy plan is written. A claim that is absent on read-back,
or whose read fails other than transiently, also refuses. A `409` on the write, or a transient failure
on the read-back, raises `TransientError`. A request with no `$.execution` raises `malformed_event`,
for the reason `arcommon.plan`'s execution-keyed paths already do. `request_id_reused` is one of
`cpcommon.messages.SILENT_REASONS`, so every one of these refusals notifies nobody — including the
absent or unreadable claim, where no run can be shown to hold the id and report under it.

#### Acceptance Criteria:

- [ ] Two runs of one request id, driven concurrently against a fake S3 that honours `IfNoneMatch`,
      with the prefix listing pinned empty for both, end with exactly one proceeding and the other
      refused `request_id_reused`; the refused run writes no copy plan, and the winner's plan is the
      winner's.
- [ ] That test reddens when the claim is removed.
- [ ] A second inspect-source by the same execution, after its claim succeeded, proceeds.
- [ ] A `412` followed by an absent or unreadable claim refuses `request_id_reused`; a `412` followed
      by a transient read failure raises `TransientError`; a `409` on the write raises `TransientError`.
- [ ] An id whose vault prefix already holds objects is still refused before anything is written —
      `test_a_request_id_that_has_been_used_before_is_refused_before_anything_is_read` keeps its
      `fake.puts == []` assertion.
- [ ] On the rendered archive arm, `StampExecution` precedes `InspectSource` and the restore arm is
      unchanged; `test_a_field_naming_state_reads_exactly_what_its_verb_returns` and
      `test_the_admin_prefix_matches_the_iam_grant_and_the_lifecycle_rule` pass, and the
      inspect-source tests whose fixtures lacked `$.execution` gain it.
- [ ] `test_every_absence_site_in_the_tree_is_dispositioned` passes with a `DISPOSITIONS` row for the
      claim's read-back: an absent claim and an unreadable one both refuse.
- [ ] A test reads the rendered admin lifecycle rule for `archive/` and the archive queues, and
      fails when the claim's expiry is not longer than the DLQ's retention plus the machine's
      `TimeoutSeconds` — so shortening `admin_results_retention_days`, or lengthening a retention,
      cannot quietly reopen the race.
- [ ] The rollback's ASL comment and `arcommon.plan`'s docstrings say the archive prefix is one run's
      alone because of the claim, and `assert_archive_unused` no longer says it narrows rather than
      closes.

### FR-006: The runtime is proven, and the docs say the guard holds at every write

#### Description:

The Lambda image build asserts, in a `RUN python -c` step beside the existing one, that its own
botocore's S3 model accepts `IfNoneMatch` on `CopyObject` and `CompleteMultipartUpload`, and fails the
build otherwise. Every site that states the guard is "not yet" absolute at the write, or that
overlapping restores can overwrite, or that the reused-id race is only narrowed, is corrected, with
superseded claims marked in place: the archive README's group-id section, `sqs.tf` and `pipe.tf`,
`apicommon.fifo`'s `_group_archive_restore` docstring, `arcommon.guard`'s docstring, the
`ReCheckDestinationClear` comment, the register entry this spec answers and the Fences it feeds, the
plane page's fence in `lambdas/info/planes/archive.md`, and `architecture.md`'s row 29. The live check
invokes a deployed verb with a hand-built batch, which no signed-in session can do, so it is recorded
as a row in `docs/testing/owed.md`.

#### Acceptance Criteria:

- [ ] The build step's expression, run against this Mac's botocore 1.35.99, exits non-zero naming
      `CopyObject`; run in the built image, it exits 0.
- [ ] The Fences bullet saying the guard *"is absolute at the CHECK, not yet at the write"* is
      replaced by one saying it holds at every write because the copy-back is conditional — citing
      the `owed.md` row by name until that row is discharged, since every test of the condition runs
      against a fake — and the commit-gate bullet's "one id sent twice is still the unrecoverable
      case" clause is replaced by one naming the claim.
- [ ] No rendered IAM policy changes — asserted on the rendered templates before and after.
- [ ] `docs/testing/owed.md` carries the live check: the deployed `archive-copy-objects`, given a
      one-line conditional batch whose destination exists and holds different bytes, reports the item
      `destination_occupied_during_copy` and leaves the destination's ETag unchanged; given the same
      batch with the destination absent, it copies it.

### FR-007: Every restore message is safe to follow while another restore of the archive runs

#### Description:

Two rules hold for every body the restore resolver can render — every code in `arcommon.messages`'
table except an explicit `ARCHIVE_ONLY` set of codes only the archive arm raises — and for every line
`arcommon.receipt` writes on a restore:

1. **No sentence tells the user to destroy anything.** The remediation is "move or rename". The test
   searches for a set of destructive verbs — delete, remove, discard, overwrite, erase, wipe, purge,
   and "clear ... out" — after first stripping an explicit allowlist of the negated phrases the table
   uses ("don't delete or overwrite", "nothing was deleted", "nothing was overwritten", "can't be
   removed"). A negation nobody has added to the allowlist fails the test, which is the safe way to be
   wrong: a phrase-level rule that exempted any sentence containing a "not" let "Nothing was
   overwritten, so you can delete the older copies" through.
2. **No sentence states the archive's present condition as fact.** "Is intact", "still intact",
   "remains intact", "is untouched", "can still be restored", "can be restored again" and "still
   available" are all false once a sibling has swept the vault. The one permitted form is "was still
   complete when this restore stopped", and only the two bodies the count below selects may use it.
   A sentence about the user's space ("your files are exactly where they were") is not about the
   archive and is not in the list.

**The safety sentence is the restore resolver's, not each body's.** `cpcommon.messages.register`
gains an optional `suffix`, and `arcommon.messages.restore_resolver` passes " If any files from this
archive are already back in your space, please don't delete or overwrite them - they may be the only
copy." Every message the restore resolver renders ends with it — every body, the access-denied message
and the fallback — so a code that is reachable after a copy-back has begun needs no list to carry it,
and the generic "something went wrong" a killed verb produces carries it too. No other resolver passes
a suffix, so every other plane's messages are unchanged.

**The count.** `update-receipt`'s incomplete arm counts the archived objects under `$.archive.root`
in `$.archive.bucket` before it writes the receipt or raises. The exclusion predicate inside
`arcommon.restore.derive_destinations` is lifted to module level, and the count and
`derive_destinations` both call it, so the count and `$.objectCount` cannot disagree about what an
archived object is. A count equal to `$.objectCount` selects `restore_incomplete` or
`restore_incomplete_occupied`. Anything else — a short count, an empty prefix, or a listing that
still fails after two in-verb retries — selects `restore_archive_cleared`, which takes precedence over
both. Nothing that remains is raised out of the count.

**The bodies this FR sets**, all under the restore prefix:

- `restore_archive_cleared`: "{restored} of {total} file(s) came back before this restore stopped,
  and the archive could not be confirmed as still complete - another restore of it may have finished
  first, in which case the rest are back too. Please contact an administrator before requesting this
  restore again."
- `restore_incomplete`: "{restored} of {total} file(s) were restored to your space before the restore
  stopped, so it did not finish. The archive was still complete when this restore stopped, so it can
  be requested again once the paths are clear - requesting it will report the files that came back,
  so move or rename them first."
- `restore_timed_out`: "that restore ran for too long and was stopped, and some files may already be
  back in your space. Please contact an administrator before requesting this restore again."
- `restore_never_requested`: "the archived files were not all retrieved from long-term storage, so
  this restore copied nothing into your space. Please try again." — its "the archive is untouched"
  is a present-state claim like the rest.
- `destination_occupied` and `destination_occupied_after_retrieval` keep their wording with "move,
  rename or delete" replaced by "move or rename".

Run against today's table, the two rules flag exactly these five codes — `restore_timed_out`,
`restore_never_requested`, `restore_incomplete`, `destination_occupied` and
`destination_occupied_after_retrieval` — and every other body passes unchanged.

**The receipt.** `receipt.restore_lines`' incomplete branch reads an `archiveIntact` flag from the
restore state and writes "Restore did not finish - {restored} of {expected} file(s) were written to
{destination}." followed by "The archive was still complete when this restore stopped." when the
count was full, and "The archive could not be confirmed as complete when this restore stopped."
otherwise. It never writes "The archive is intact".

#### Acceptance Criteria:

- [ ] The rule-1 test over every restore-renderable code reddens when "or delete" is put back into
      any of the three bodies that had it, and on each of these planted sentences: "Please delete
      them.", "Please remove them.", "Discard the old copies.", "Overwrite them.", "Clear them out.",
      "move, rename or remove them", and "Nothing was overwritten, so you can delete the older
      copies." It passes on every restore-reachable body the spec sets.
- [ ] The rule-2 test over the same population fails on each phrase rule 2 lists; "was still complete
      when this restore stopped" appears only in `restore_incomplete`, `restore_incomplete_occupied`
      and the receipt's counted line.
- [ ] Both rules also run over every line `arcommon.receipt` can write on a restore:
      `restore_lines`' output for every status and both values of `archiveIntact`, and `render` of
      update-receipt's fallback record, the receipt a restore writes when none exists.
- [ ] `ARCHIVE_ONLY` is an explicit set whose comment names why each member cannot be reached by a
      restore, and a code missing from it is checked — asserted by a planted code. The four codes both
      arms can raise — `plan_unreadable`, `plan_superseded`, `transfer_results_unreadable` and
      `protected_marker` — are not in it.
- [ ] Every message the restore resolver renders — each restore-reachable body, the access-denied
      message and the fallback — ends with the suffix, and a message rendered by the archive resolver,
      or by any other plane's, does not.
- [ ] `restore_archive_cleared` and `restore_timed_out` join `_DELIBERATELY_PARTIAL` beside
      `restore_incomplete_occupied`, the set's comment arguing each as the same asymmetry reached by a
      different cause — both describe files that may already be back.
- [ ] An incomplete restore whose prefix holds `objectCount` archived objects raises
      `restore_incomplete` (or `restore_incomplete_occupied`); one whose prefix holds fewer — including
      none, and only `_manifest.json` — raises `restore_archive_cleared`; one whose listing raises a
      non-transient error, and one whose listing raises `TransientError` three times, both raise
      `restore_archive_cleared`.
- [ ] `test_archive_update_receipt.py`'s fake S3 gains a paginator over the vault prefix, and its
      fixtures agree on `objectCount`.
- [ ] `restore_archive_cleared` is registered and names no marker nothing fills.
---

## Data Model

```python
# A transfer manifest line — cpcommon.transfer.manifest writes it, copy_batch reads it.
{
    "srcBucket": str, "srcKey": str, "destBucket": str, "destKey": str, "size": int,
    "storageClass": str,  # optional, as today
    "ifAbsent": bool,     # optional; NEW — true on every restore copy-back line, absent elsewhere
}

# The archive-id claim — admin bucket, archive/{requestId}/claim.json. Written once, never updated.
{"execution": str, "requestId": str, "claimedAt": str}  # both from $.execution

# transferOutcome, as collect-transfer-results returns it — gains one field.
{"complete": bool, "copied": int, "failed": int, "expected": int, "occupied": int}
```

## API / Interface Contract

```python
# lambdas/control-plane-common/cpcommon/cas.py
def is_precondition_failed(exc) -> bool: ...   # 412
def is_conditional_conflict(exc) -> bool: ...  # 409
def is_precondition(exc) -> bool: ...          # unchanged behaviour: the union of the two

# lambdas/control-plane-common/cpcommon/messages.py — register() gains one keyword
def register(domain_messages: Mapping[str, str], *, prefix: str = "", access_denied: str = "",
             fallback: str | None = None, blank_unfilled: bool = False,
             suffix: str = "") -> Resolver: ...

# lambdas/control-plane-common/cpcommon/transfer/copy.py
class DestinationOccupied(Exception): ...

def copy_one(s3, src_bucket: str, src_key: str, dest_bucket: str, dest_key: str, size: int,
             storage_class: str = "", if_absent: bool = False) -> None: ...

def copy_batch(items: list, failure_reason: str, *, echo_fields: tuple,
               occupied_reason: str | None = None,
               concurrency: int = COPY_CONCURRENCY) -> dict: ...

# lambdas/archive-common/arcommon/plan.py
def claim_key(request: dict) -> str: ...
def claim_archive_id(request: dict) -> None:
    """Reads $.execution; raises TerminalError('request_id_reused') when another execution holds
    the id, TerminalError('malformed_event') when the request carries no execution."""

# lambdas/archive-common/arcommon/restore.py
def is_archived_object(key: str, archive_root: str) -> bool:
    """The exclusion predicate derive_destinations used inline, lifted so the count shares it."""

def archive_is_intact(bucket: str, archive_root: str, expected: int) -> bool:
    """True only when the prefix holds exactly `expected` keys is_archived_object accepts.
    Retries a transient fault twice and returns False on anything left."""

# lambdas/archive-common/arcommon/receipt.py — restore_lines' incomplete branch reads one more
# field from the restore state, "archiveIntact": bool, and says "cleared" when it is false.
```

## File & Folder Structure

```
lambdas/
├── Dockerfile                                   # the botocore assertion
├── control-plane-common/cpcommon/{cas.py,messages.py,transfer/copy.py}
├── archive-common/arcommon/{plan.py,messages.py,guard.py,restore.py,receipt.py}
├── archive-build-restore-manifest/archive_build_restore_manifest.py
├── archive-copy-objects/archive_copy_objects.py
├── archive-collect-transfer-results/archive_collect_transfer_results.py
├── archive-inspect-source/archive_inspect_source.py
├── archive-update-receipt/archive_update_receipt.py
└── test_absence_is_answerable.py                # two DISPOSITIONS rows
infra/modules/archive/{state-machine.asl.json.tftpl,README.md,sqs.tf,pipe.tf}
docs/decisions/archive-and-restore.md
docs/testing/owed.md
```

## Implementation Phases

The only ordering the system imposes is decision 10: the ASL reorder deploys before the claim reads
what it provides. Everything else can land together; the plan decides the PR grouping. Phase 0 closes
a hazard that is live today and depends on nothing else here, so it is worth landing first.

### Phase 0: Every restore message is safe to follow

- The two rules' test over the whole table and the receipt, `ARCHIVE_ONLY`, the reworded bodies,
  and the restore resolver's suffix.
- The lifted exclusion predicate, `archive_is_intact`, `restore_archive_cleared` and the receipt's two
  incomplete lines.

### Phase 1: The reorder, inert

- `StampExecution` ahead of `InspectSource`, with the inspect-source fixtures gaining `$.execution`.

### Phase 2: The conditional copy in the shared engine

- The split predicates in `cpcommon.cas`.
- `ifAbsent`, the `412` comparison, the `409` retry and `DestinationOccupied` in
  `cpcommon.transfer.copy`, with its `DISPOSITIONS` row.
- The fake S3 that honours `IfNoneMatch` and computes ETags, and the retry-meets-its-own-write test.
- The image build's botocore assertion.

### Phase 3: The restore uses it

- `ifAbsent` on every restore manifest line; the new reason passed by `archive-copy-objects`.
- `occupied` on the collector's return; `restore_incomplete_occupied`, its body and the two message
  gates.

### Phase 4: The archive id is claimed, after Phase 1 has deployed

- `claim_key` and `claim_archive_id`; inspect-source claims after the listing, with its
  `DISPOSITIONS` row.
- The concurrent-claim test with the pinned listing.

### Phase 5: The docs and the live check

- Every site FR-006 names, and the `owed.md` row.
