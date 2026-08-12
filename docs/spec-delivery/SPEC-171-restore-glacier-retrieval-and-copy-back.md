# SPEC-171 — Restore: Glacier Retrieval, the Wait Loop, Copy-Back & Terminals

**Completed:** 2026-08-12
**Spec:** `docs/specs/SPEC-171-restore-glacier-retrieval-and-copy-back.md`

## What shipped

The restore arm crosses the bill. SPEC-170 stopped the moment it knew a restore was legal and
unobstructed; this asks Glacier for the bytes back, waits hours for them, copies them where they
came from, sweeps the vault and rewrites the receipt.

**Lambdas — five new verbs** (the plane is now sixteen)

- `archive-build-restore-manifest` — the restore plan → **one** JSONL dataset that **both** restore
  Maps read.
- `archive-initiate-restore` — the Map child that issues `RestoreObject`. The point of no return.
- `archive-poll-restore` — the loop's body: the `Restore` header rule and the paged sweep.
- `archive-delete-archived` — the vault swept on full success only.
- `archive-update-receipt` — the two restore lines, rewritten. **Three ASL states, one function.**

`archive-copy-objects` and `archive-collect-transfer-results` are **reused** by the copy-back: the
question is identical in the opposite direction, and what differs is only what the answer
authorizes.

**`arcommon` — one new module**

- `retrieval.py` — the two tolerated `RestoreObject` answers, the three-way `Restore`-header rule,
  the paged sweep and the progress record.

**`arcommon` — extended**

- `config` — `RESTORE_STORAGE_CLASS`, `RESTORE_TIER`, `RESTORE_AVAILABILITY_DAYS`,
  `RESTORE_POLL_SECONDS`, `RESTORE_MAX_POLLS`, `RESTORE_POLL_PAGE`.
- `plan` — the restore manifest, the progress record and the two Map exports (six layouts now, one
  module).
- `receipt` — `restore_lines`, `rewrite`, `read`, `write_text`.
- `messages` — `restore_incomplete`, `restore_never_requested`, `nothing_to_restore`.
- `restore.validate` now resolves the **receipt's** location beside the vault's, so the key is
  built once (SPEC-168's rule) rather than three agreeing times.

**ASL** — twenty-three new states, the loop among them; `TimeoutSeconds` 10,800 → **43,200**.
`check-destination-clear` is now invoked **twice**, and that is the most important thing in this
spec that the spec did not ask for — see below.

**IAM** — `s3:RestoreObject` on the vault, and `SpaceDataWrite` replacing `ReceiptWrite`.

### The bounds, and what sizes each

| Constant | Value | Measured against |
|---|---|---|
| `RESTORE_TIER` | `Standard` | 3–5 h. Expedited is capacity-limited without a standing charge; Bulk is 5–12 h |
| `RESTORE_MAX_POLLS` × `RESTORE_POLL_SECONDS` | 84 × 300 s = **7 h** | the tier's own 5 h, **with headroom on purpose** |
| `RESTORE_POLL_PAGE` | 1,000 | the granularity progress is RECORDED at — not a bound on one invocation |
| `poll-restore` timeout | 600 s | the guard's arithmetic re-used: 20,000 heads, 8 at a time, at 100 ms |
| `RESTORE_AVAILABILITY_DAYS` | 7 | the copy-back that READS the temporary object, plus the run around it |
| `TimeoutSeconds` | 43,200 s | retrieval budget + polling + copy-back + both Maps + the serial verbs ≈ 35,500 s |

**The budget's headroom is the number worth reading twice.** Every other timeout in this repo can
be tight, because failing means re-running something free. Here, giving up on a retrieval that was
going to finish makes the user pay for a **second billed retrieval**. Two extra hours of waiting
costs one Lambda invocation every five minutes.

## The defect review found, and the state that closes it

**A fresh-context review found that this spec turned SPEC-170's destination guard into a promise
rather than a guarantee, and the cost was silent data loss.** SPEC-170's rule is that any occupied
destination refuses the *whole* restore, because S3 has no move and no rename, versioning is off,
and a copy over a file the user re-created destroys it with no trace. One check was sufficient
while the guard and the copy were seconds apart.

This spec put **three to five billed hours** between them — and, worse, spent them telling the user
a restore is in flight, which is precisely when they would go and work in their own space.
Re-creating a file in that window is not an exotic race; it is the ordinary case the guard was
written for, arriving late. The copy-back would have overwritten it, reported **success**, and then
swept the vault.

`ReCheckDestinationClear` runs the **same verb over the same plan** immediately before the
copy-back: one round of heads against a run that has already waited hours. The two passes are
worded differently, because they leave the user somewhere different — after the retrieval the
objects are out of Glacier and stay ready for `RESTORE_AVAILABILITY_DAYS`, so a prompt second
attempt costs neither the wait nor the bill again, and that is a fact nobody could infer.
**The stage is SEEDED by the machine**, not inferred by the verb: "the retrieval has not run" and
"the retrieval reported nothing" look identical from inside a handler, and getting it wrong tells a
user their retrieval is warm when it was never made.

The review's other findings, all fixed: the multipart copy now carries `Expires` and
`WebsiteRedirectLocation` too (**tags are still dropped above 5 GiB and that is recorded in
`copy.py` rather than fixed** — matching `CopyObject`'s `TaggingDirective` would cost a
`GetObjectTagging` per object and nothing in this portal tags one); the head's own failure path is
now exercised, since it is a *new* pre-copy failure point for two shipped planes;
`archive_object_unreadable` split out of `restore_never_requested`, because "please try again" is
the wrong next step for an object that has vanished from the vault; the `PutObject` Deny extended
to `_config/` and `_directory/`, which sit at the **bucket root** where a `*/x/*` pattern cannot
reach them; a vacuous assertion in the receipt suite replaced (it matched the destination anywhere
in the document, and `Original path` already contains it — measured: it stayed green with the
restore line blanked); and FR-004 AC4 now has the test it literally asked for, driving the real
collector over a fixtured export and walking the graph from the verdict it actually produces.

## The decisions this spec made

1. **Retrieval is a Distributed Map that tolerates NO failure — the exact inverse of the copy's
   100%.** The copy must finish whatever happens, or the commit gate cannot tell "failed" from "not
   attempted" and that gate decides whether data is deleted. The retrieval has no such gate: a
   genuine fault means nothing was copied and the archive is untouched, so failing the Map Run
   outright is the cheapest correct answer. What makes that cheap is the **two tolerated codes** —
   `RestoreAlreadyInProgress` and `InvalidObjectState` — without which a re-submission would bill
   the user twice for the objects already on their way back.

2. **Completion is the `Restore` header, and an ABSENT header is a FAILURE.** Nothing about an
   archived object changes when a retrieval finishes — it stays `GLACIER`, and what appears beside
   it is a temporary copy the header describes. So "no header" cannot mean "not ready yet"; on an
   object still in a Glacier class it means nobody ever asked. Read as pending it would burn every
   remaining iteration, wait seven hours, and report a timeout naming the wrong cause.

3. **The poll advances as far as it can per invocation, not one page per iteration.** A strict
   page-per-`Wait` reading would add twenty five-minute waits — over an hour and a half — after a
   retrieval had already completed, because every object was requested at once at one tier and they
   finish together. The page is the granularity progress is **recorded** at; the invocation's bound
   is the guard's own 600 s.

4. **The restore's gate is the commit gate's MIRROR IMAGE, not its twin.** Archiving's gate protects
   the SOURCE. This one protects the ARCHIVE, and the reason runs the other way: a partial restore
   cannot be rolled back, because the user's space already holds some of their own data and deleting
   it to make the operation atomic would destroy the very thing the restore was for. So the failure
   arm deletes **nothing** — and the archive it keeps is then the only complete copy in existence.

5. **The cleanup's failure does not fail the run; the source deletion's does.** Same algorithm,
   opposite consequence. A half-deleted source means a user told their archive completed while their
   files are still half there. A half-swept vault costs storage in a bucket the browser cannot reach
   and the 7-year expiry sweeps. So it is a `cleanupIncomplete` flag on a **successful** run, and
   the user is not told about it at all.

6. **The receipt is REWRITTEN, never re-rendered.** The archive lines record the archive run, and
   its start time is the one field no restore can recompute — so a fresh render would silently blank
   it on the only durable record the user has. The rewrite is keyed on the two LABELS and keeps every
   other line verbatim. An absent receipt (a **proven** 404, never a 403) is composed fresh; an
   ambiguous read raises rather than overwriting a document it merely failed to read, which is the
   destination guard's fail-closed discipline pointed at a write.

7. **The marker runs BEFORE the retrieval, not after.** FR-006 AC4 asks for it "when retrieval is
   initiated". Immediately before is the same guarantee and strictly safer: there a receipt-write
   failure costs nothing, where a moment later it would fail a run the user had already been billed
   for.

8. **The seed carries the STAGE and the run carries the COUNTS.** Found while writing the tests: an
   earlier version let `SeedRestoreIncomplete` supply `restored`/`expected` as well, so the sentence
   written onto the receipt and the tokens in the notification had **two sources** and could
   disagree — a receipt reading "40 of 100" beside a notification reading something else, with
   nothing to say which was right.

## What changed outside this spec

**`cpcommon.transfer.copy` now carries object metadata, and closing FR-003 AC5 honestly meant
fixing a latent bug on all three planes.** `CopyObject` has `MetadataDirective`, which defaults to
`COPY`; **`CreateMultipartUpload` has no such directive**, and `UploadPartCopy` moves bytes and
nothing else. So every object over `MULTIPART_COPY_THRESHOLD` (5 GiB) came out of a copy as
`binary/octet-stream` with its user metadata gone — silently, on table-share and file-send as well.

It surfaced here because an archive round trip is the first operation in this repo that copies an
object **twice** and hands it back to the user expecting it unchanged; a shared table is read
through Athena, which does not care. The fix is explicit `MetadataDirective: COPY` on the single
path and a `HeadObject` on the multipart path whose headers are re-stated on the create call. A
test runs the round trip at **both** copy strategies, because one fixtured at 10 bytes would pass
while the bug lived on.

**The machine's ceiling rose for the whole plane.** `TimeoutSeconds` is a top-level ASL field on one
machine serving two arms, so a wedged **archive** is now reported after twelve hours rather than
three. Accepted — it is a backstop, and the alternative was killing healthy restores — and pinned:
a test asserts the archive arm's own worst legal run still clears the ceiling by more than 4×.

**The `ReceiptWrite` grant is gone, and this is FR-007 AC2's widening stated out loud.** SPEC-169
scoped `s3:PutObject` on the space buckets to `*/archive/*`, because the only thing this plane put
into a user's space was a receipt. A restore writes wherever the data came from, so `SpaceDataWrite`
covers the whole bucket, with `AbortMultipartUpload`/`ListMultipartUploadParts` beside it (an
archived object may be 10 GiB and the copy-back part-copies above 5). The narrowing that goes with
it — a **Deny** on `PutObject` under `athenaresults/` and `user_settings/` — is defence in depth
rather than the rule: those folders can never appear in an archive (`RESERVED_SOURCE_ROOTS` refuses
them at archive time, and the destination guard's 403-is-occupied rule refuses them again at restore
time), and it deliberately does **not** cover `archive/`, which is where the receipt lives.

**Two state-machine tests were widened rather than replaced.** `test_the_transfer_is_the_only_map`
became `test_every_map_is_top_level_and_there_are_exactly_three`, and the ASL loader now preserves
each interpolation's VARIABLE NAME instead of stubbing every one to the same literal — with every
ARN rendered identically, "these three states call the same function" and "these three call three
different functions" looked the same.

**`test_no_body_promises_a_partial_outcome` gained an exemption set.** It asserted that every
refusal on this plane is a whole-request refusal, which was true until `restore_incomplete`. The
exemption is a named set with the reasoning beside it, so a second body drifting into partial
wording has to be argued for rather than merely passing.

## Not met by this spec, deliberately and not silently

- **The guard's residual TOCTOU is narrowed, not closed** — as table-share's and file-send's are.
  Two concurrent writers can still land a file between the second head and the copy. What the
  second pass removes is the *hours-long* window this spec introduced, which is a different thing
  in kind: seconds of overlap is a double-submit, and hours is the user acting on a message this
  plane sent them.
- **FR-007 AC4 — the policy simulation against the DEPLOYED role — is owed until the apply lands.**
  The pre-apply baseline was run and is recorded in the live-check script: every new grant reads
  `implicitDeny` today, each paired with an `allowed` control on the same bucket and a similar ARN,
  which is what distinguishes an ungranted action from a wrong resource ARN (SPEC-149's trap). The
  post-apply repeat is one command and is in the script.
- **FR-004's `restore_incomplete` message and FR-005's cleanup flag reach nobody yet.** SPEC-172
  owns the notification producer; this spec fixes the outcomes and their wording, and the wording is
  reachable today only through the failure path's own decorator.
- **Phase 4's live check is owed in full**, and it is the one nothing offline can stand in for. See
  `docs/testing/archive-restore-e2e.md` → *SPEC-171*.
