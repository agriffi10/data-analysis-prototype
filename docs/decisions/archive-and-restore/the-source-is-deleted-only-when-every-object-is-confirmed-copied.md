---
type: Decision
title: "The source is deleted only when EVERY object is confirmed copied"
description: "**The source is deleted only when EVERY object is confirmed copied**, and the gate is a **state** — the rollback arm cannot reach `DeleteSource`, asserted by walking the ASL graph, and an unrecognisable verdict fails closed. **And all or nothing on the ETag the plan recorded**: every copy is pinned to it, and delete-source heads every original first — one that changed refuses the whole deletion and removes the vault copy, because a partial one deletes into a vault the user holds no receipt for (`the-source-is-deleted-only-while-it-is-unchanged-since-the-plan-listed.md`). **It, not the queue, is what makes two overlapping archives of one space safe when their ids differ** — the group id orders their starts and nothing else. **One id sent twice is closed by a CLAIM**, not by the queue and not by the prefix listing, which two runs reaching it together both pass: inspect-source takes a create-only write on `archive/{requestId}/claim.json` after the listing and before anything else, so S3 decides which run proceeds. It **expires** with the admin prefix at 30 days, which is safe only while no second run of an id can start that late — a test reads the queue retentions and the machine's ceiling and fails when the margin closes."
---

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

inspect-source's create-only claim is a write on `archive/{requestId}/claim.json`, taken after the prefix listing and before anything else. It **expires** with the admin prefix at 30 days, which is safe only while no second run of an id can start that late — a test reads the queue retentions and the machine's ceiling and fails when the margin closes.

## History

### 2026-08-12

- **Settled:** entered the register.
