# Completed Spec — SPEC-189: File Operations — the Transfer, the Source Deletion & the Terminals

## What was completed?

The file-operations plane now **moves and deletes data**. Five verbs replace SPEC-188's two
placeholders, and the machine runs end to end: expand → guard → guard again → manifest → Distributed
Map → attribute → commit gate → delete → finalise → release. Nothing user-visible changed; no
gesture in the browser reaches this plane until SPEC-190.

- **`cpcommon.transfer` generalised** — `copy_batch` and `_from_input` take a caller-supplied
  `echo_fields` set instead of table-share's hardcoded `recipient`/`kind`. Escalated as its own FR
  and its own commit.
- **`file-ops-build-transfer-manifest`** — one JSONL line per object of every still-`cleared` item,
  carrying `itemKey`, the plan's destination and its `size`. Also the **deletability gate**.
- **`file-ops-copy-objects`** — the Map's batch copier, `cpcommon` only.
- **`file-ops-collect-transfer-results`** — both halves of the export, per-item failure counts, and
  the `deletable` set written **by pointer**.
- **`file-ops-delete-source`** — the plan's keys for confirmed items only, per item, with the subset
  assertion at the boto boundary.
- **`file-ops-finalise-outcomes`** — the dedicated step FR-008 AC2 requires; assigns every terminal.
- **`focommon.delete`** — per-item refusal, batched deletion, both conditionality paths.
- **The second guard pass**, the top-level Distributed Map, the state-machine role's Map grants and
  the execution role's write/delete grants with SPEC-169's Deny set.

## What changed that a reader would not expect

**The byte cap moved, not the ceiling.** The joint budget was computed for the first time with a
copy in it and came to ~12,700 s against 10,800 s — and the earlier version had **no lock-give-up
term at all**, though a waiter can spend 2,080 s. `FILE_OPS_MAX_TOTAL_BYTES` came down 3 TiB → 2 TiB
rather than raising `MACHINE_TIMEOUT_SECONDS`, because the ceiling also sets `STALE_LOCK_SECONDS`
and a longer stale window on a **shared** space blocks everyone who works in it. Both constants stop
being PROVISIONAL.

**Three per-item terms could not ride the state, and the measurement is why.** The deletable list,
the per-item counts and the deletion records measure **287,532 bytes** at the selection cap against
Step Functions' 262,144 (307,083 with conflict samples). The overflow lands on the collector's
result — *after* the copy — or on delete-source's, *after* the deletion, where
`States.DataLimitExceeded` escapes every `Catch` and the user is told nothing at all. All three go
to `file-ops/{requestId}/{execName}/transfer-results.json`; only `deletableCount` rides.

**`assert_item_deletable` runs BEFORE the transfer, and that placement is load-bearing.** A personal
folder holding a nested `athenaresults/` passes the front door — the browser's rule is root-anchored
in a personal space — and expands with those objects in the plan. Refused only after the copy, it
would be fully duplicated in the destination and undeletable at the source: a state the user cannot
resolve through this plane at all. The post-copy assertion stays as defence in depth.

**A conditional delete is not replay-safe the way an unconditional one is.** `arcommon.delete` rests
its whole `Retry` story on "S3 reports an already-absent key as deleted", which is true only
*without* a condition. With one, a key the previous attempt removed comes back on the error side —
so a verb that deleted five batches of twenty and retried would report correct items as
**`duplicate`**, and SPEC-190 would invite a re-submit whose source is gone. "Gone" and "changed" are
now separated explicitly.

**409 and 412 diverge from `cpcommon.cas.is_precondition`, deliberately.** That predicate collapses
them, and is right to: a compare-and-set retries on either. A conditional delete is not a CAS — 412
means the object changed (terminal for that item; its destination holds stale bytes) and 409 means a
concurrent write won the race (retryable). The module is exempted from the fleet's precondition
sweep by full path, with an assertion that it has not become a CAS.

**The HEAD-compare path is ACTIVE and the conditional one is flag-gated.** Reading
`ObjectIdentifier`'s members proves botocore will *serialize* the ETag, not that S3 *enforces* it —
and a serialized-but-ignored condition deletes a changed source silently, with versioning off.

### Deliberate deviations

- **Five verbs, not the spec's four.** `finalise-outcomes` is required by FR-008 AC2 and no existing
  verb can stand in: `delete-source` never runs on a `copy`, so without it every successful item on
  a copy run would reach the terminal still labelled `cleared`. Spec amended.
- **FR-007 AC2's per-bucket Deny shapes are inexpressible** on a role with no principal tag — an IAM
  `Resource` wildcard matches `/`. The strict side is taken and the domain layer mirrors **the
  policy**, not the browser rule. Spec amended.
- **A `s3:PutObject` Deny was added** beyond FR-007 AC1's `DeleteObject`-only enumeration, mirroring
  the archive plane, because the blanket `NoDataObjectWrite` Deny is going away in the same edit.
- **`delete_failed` extends FR-008 AC1's vocabulary** — see above. `MEMBERS` ratchets 7 → 13.
- **No component-inventory row.** That router covers `apps/portal/src`; this spec added no browser
  code, as SPEC-187 and SPEC-188 added none.

## What changed from earlier specs?

- **`cpcommon.transfer`** — `echo_fields` on `copy_batch` and `read_failed_items`. Table-share and
  file-send are byte-identical; **archive's records change on purpose**, losing the
  `{"recipient": null, "kind": null}` pair its manifest never carried.
- **`focommon`** gained `delete.py`, four key builders and a results document on `plan.py`, six
  outcome members, and six reason bodies.
- **The execution role** lost `NoDataObjectWrite` and gained `PutObject`/`DeleteObject` on both data
  buckets, bounded by two portal-managed Denies. Three IAM tests were **replaced, not deleted**.
- **`test_the_placeholders_carry_no_result_or_parameters`** was retired with the placeholders it
  guarded.

## What the diff review caught

Five real defects, each fixed and each with a test that would have caught it:

1. **Two reason bodies were false sentences under the `delete` prefix** — "You now have it in both
   places" on a `delete`, which is the exact confusion `delete_failed` was added to prevent. The
   bodies now say only that the original survived; a sweep over the whole table forbids any body
   claiming a copy exists.
2. **The manifest-versus-plan check was a tautology.** `itemLines` reported the plan's own
   `objectCount` back, so both sides of the comparison read the same field. It now counts the lines
   actually written — and `plan.load` validates the object count only at the top level, so the
   per-item divergence this catches is unguarded anywhere else.
3. **The marker Deny matched a suffix, not a path segment.** `*DO_NOT_DELETE.txt` also matches
   `alice/reports/backupDO_NOT_DELETE.txt` — an ordinary user file, which would have passed the
   pre-delete check, been copied, then taken an `AccessDenied` mid-batch. A new test holds IAM and
   the code rule to the same key set.
4. **The manifest builder failed OPEN on the containment root** where `delete-source` fails closed:
   an empty root makes `startswith` a no-op.
5. **The whole-request-terminal test checked one of four failure seeds** — the other three carry
   their error under `Parameters` rather than `Result` and were silently skipped.

**One finding was rejected in writing.** The reviewer suggested defaulting an absent `guardPass` to
the *second* pass, on the ground that it can only narrow. The argument is backwards: the second pass
evaluates only items already marked `cleared`, so on a state with an empty outcome list it evaluates
**nothing** — every item keeps its `cleared` and the transfer copies it having headed no key at all.
Resurrecting a conflict misreports one item; skipping the guard overwrites a user's files. Applying
the change reddened 22 existing tests, which is the codebase saying the same thing. The fallback
stays at pass one, with the reasoning in the module and a test pinning it.

## Verification

`pytest lambdas/` (4,357 passed, exit 0), `ruff`, `mypy`, `tofu validate`, `tofu fmt -check`,
`scripts/validate_docs.py` and `npm run build` green locally. Three fresh-context reviews — two of
the plan (spec-conformance and engineering-risk frames) and one of the diff; every finding fixed or
rejected in writing.

**The named mutations were executed, not described.** Removing the collector's filter, the
delete-source skip, the second pass's `cleared` filter and the shortfall check each reddens the test
named for it — and the subset guard's test fails when the guard is HOISTED above the loop, which is
the shape an "is it called?" test still passes.

**Help & guides sweep: checked and skipped.** Nothing a user can see changed — no gesture reaches
this plane until SPEC-190 — so there is no shipped, wired-end-to-end behaviour to document.

**`docs/testing/e2e.md` gains nothing, and that is stated rather than silent:** not one of this
spec's checks is runnable from a signed-in session, because nothing in the browser reaches the plane.
All six are owed.

## What is owed

Six live checks, all needing a hand-crafted envelope — `docs/testing/owed.md` §1 and
`docs/testing/fixtures/file-ops-plane.sh`:

1. a real `move` of a folder over 1,000 objects — deletion complete and conditional;
2. **the batch path's precondition-mismatch `Code` string**, which AWS does not document — and it
   must now recover **two** strings, since "gone" and "changed" are told apart;
3. a `move` whose source is modified between copy and delete → **`duplicate`**, not a silent skip;
4. a `delete` of a folder holding a nested `DO_NOT_DELETE.txt` — the marker survives, the rest goes;
5. **the conditional-delete enforcement probe** — until it passes, `CONDITIONAL_DELETE_ENABLED`
   stays `False` and the HEAD-compare path runs;
6. the IAM simulation against the **deployed** role, every denial paired with an `allowed` control.

## Notes for SPEC-191

- The terminal carries the complete outcome list, the `operation`, **both** spaces as `(kind, name)`,
  the destination prefix, each item's `targetName` and `kind`, and the per-item counts — so the
  producer reads no second source. The counts come from the transfer-results document.
- `ReleaseLock` runs **before** anything that notifies, and a test pins that ordering: insert the
  producer **after** it.
- SPEC-187 FR-009's release walk and the SPEC-152 fleet test must be **re-run** when the producer
  state is added.
