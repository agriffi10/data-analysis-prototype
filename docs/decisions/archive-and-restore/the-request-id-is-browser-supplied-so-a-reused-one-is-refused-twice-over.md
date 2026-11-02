---
type: Decision
title: "The request id is browser-supplied, so a reused one is refused twice over"
description: "A request id is single-use: `plan.load` refuses a plan that does not describe its request, inspect-source refuses a non-empty archive prefix, and a create-only claim decides between concurrent runs."
---

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
message to read ([the decision](../control-planes/a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is.md)).

## History

### 2026-09-20

- **Changed:** The concurrent reuse the prefix listing only narrowed is closed by a create-only claim on the id; the listing stays as the cheaper refusal for ordinary reuse.

### 2026-08-12

- **Settled:** entered the register.
