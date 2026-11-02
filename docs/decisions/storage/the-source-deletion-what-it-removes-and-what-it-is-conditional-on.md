---
type: Decision
title: "The source deletion: what it removes, and what it is conditional on (SPEC-189)"
description: "The source deletion works from plan keys, counting an already-gone key as success and a real mismatch as `source_changed`; the HEAD compare stays active until a live probe flips `CONDITIONAL_DELETE_ENABLED`, and only a move's deletes are conditional."
---

**It deletes the plan's keys, never a prefix listing** (SPEC-187 Premise 1). This plane's lock
serialises its own executions and nothing else — not uploads, not create-folder, not the six other
control planes — so an object written into a source folder between the expansion and the commit was
never copied, and a prefix delete would remove it silently and unrecoverably with versioning off.
The accepted cost is an **orphan**, which is visible and recoverable where the alternative is
neither. A plan **re-read** is not a prefix listing, and per-item gating makes "the plan keys of a
fully-succeeded item" and "the keys confirmed copied" the same set.

**A conditional delete is NOT replay-safe the way an unconditional one is.** `arcommon.delete` rests
its whole `Retry` story on S3 reporting an already-absent key as deleted — true only *without* a
condition. With one, a key the previous attempt removed comes back on the **error** side, so a verb
that deleted five batches of twenty, hit a throttle and retried would report every one of those five
as a failure and the user would be told a completed move half-failed. "Gone" is therefore success and
only a genuine mismatch is `source_changed`.

**409 is handled distinctly from 412, diverging from `cpcommon.cas.is_precondition` on purpose.**
That predicate collapses them and is right to: a compare-and-set retries on either. A conditional
delete is not a CAS — a **412** means the object changed, terminal for that item because its
destination copy now holds stale bytes; a **409** means a concurrent delete or put won the race,
which is retryable. One module answering "did my write lose?" and another answering "why did my
delete not happen?" are different questions, and a shared helper would have to give one answer to
both.

**The HEAD-compare path is ACTIVE and the conditional one ships behind a flag.** Reading
`ObjectIdentifier`'s members off the live service model proves botocore will *serialize* the ETag; it
does not prove S3 *enforces* it, and a serialized-but-ignored condition deletes a changed source
silently. `CONDITIONAL_DELETE_ENABLED` flips only once a live probe shows a wrong-ETag delete is
genuinely refused on these buckets.

**A `delete` operation's deletions are unconditional, and conditionality is the CALLER's explicit
flag.** A move's condition protects bytes that were just copied; a delete has no copy, and an object
modified since the expansion is still one the user asked to remove. Inferring the flag from whether
ETags happened to be supplied made a delete conditional on an empty string, which mismatched every
object and reported `source_changed` having removed nothing — found by a fixture, not by reasoning.

**`assert_item_deletable` is per item and runs BEFORE the transfer.** A whole-list refusal would be
the whole-request reversion this arc's model forbids — and on a `move` it runs after the copy, so it
would leave every item copied and nothing deleted: a full duplicate of the entire selection. The
placement matters as much as the scope: a personal folder holding a **nested** `athenaresults/`
passes the front door (the browser's rule is root-anchored in a personal space) and expands into the
plan, so a post-copy-only refusal would leave it fully duplicated and undeletable — a state the user
cannot resolve through this plane at all.

**It mirrors the IAM POLICY, not the browser rule.** IAM cannot express "at the space root only": a
`Resource` wildcard matches `/`, and this role carries no principal tag to pin one segment the way
the portal role's `${aws:PrincipalTag/username}` does. The strict side is taken — any-depth on both
buckets — and the divergence is handled per item rather than hidden.

## History

### 2026-08-17

- **Settled:** SPEC-189.
