---
type: Decision
title: "The expansion caps are sized by memory and makespan, and the obvious models miss both (SPEC-165)"
description: "`SEND_MAX_OBJECTS` (20,000) is bounded by the plan held in memory and `SEND_MAX_TOTAL_BYTES` (1 TiB) by makespan at 500 MB/s, not bandwidth, and the timeout bound is per item plus per page; tests compute each cap, so re-derive rather than raise."
---

**Decision.** `SEND_MAX_OBJECTS` = 20,000 and `SEND_MAX_TOTAL_BYTES` = 1 TiB, each computed by a
test. The per-object cap and the recipient product cap are **deferred to SPEC-166**, not omitted.

**What sizes the object cap is the plan in memory, not the listing.** `inspect-source` holds the
whole plan as a list of dicts, serialises it and encodes that — three live copies at the write. At
S3's worst-case 1024-byte keys an entry is ~2.4 KB, so 20,000 objects is ~45 MB and peaks near
135 MB, against the 1024 MB in `locals.tf` **which the test reads back**: raising the cap without
raising the memory fails the build.

**And the timeout half is where a page-counting model goes wrong.** Twenty `ListObjectsV2` pages is
four seconds and reads like the whole answer. The term it drops is that a `file` item costs its own
**serial** `HeadObject`, so 200 files is 200 round trips and forty. The bound is per-ITEM plus
per-PAGE, the item half dominates, and an assertion pins that so a future reader re-derives rather
than trusts it.

**The byte cap is a makespan, not a bandwidth.** `cpcommon.transfer` hands one whole object to each
worker and part-copies serially inside one, so the denominator is
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` — 500 MB/s, not the ~4 GB/s the same
constants suggest under an aggregate reading. That is the mistake SPEC-161 found twice, in review
rounds, after it read as satisfied both times.

**Why two caps are deferred rather than guessed, and why BOTH need a tripwire.** The per-object
cap and the `recipients × bytes` product are measured against the copy verb's
`COPY_TIMEOUT_SECONDS` and the machine's top-level `TimeoutSeconds`, and this machine has neither.
The copy plan already carries every object's size, so SPEC-166 enforces both with no second listing
and still before any byte moves.

**The per-object gap is the one that undermines a passing test, and it first shipped in prose
only.** 500 MB/s is reachable only when the bytes are spread across the worker pool; ONE object is
ONE worker at 25 MB/s, so the makespan test certifies the **distributed** case and a single 1 TiB
object is **43,980 s** — four times over the ceiling it compares against. That is table-share's
recorded shape word for word ("while `SHARE_MAX_TOTAL_BYTES` was 20 GiB the bound was implicit …
raising the total to 1 TiB removed it without anything replacing it"), and this plane *starts* at
1 TiB. Both gaps carried a `hasattr` tripwire that **failed the day SPEC-166 added the cap**, and
the arithmetic was kept as an assertion so 166 inherited the size of the problem rather than
re-deriving it.

> **SUPERSEDED in part by SPEC-166.** The caps arrived — `SEND_MAX_OBJECT_BYTES`,
> `SEND_MAX_TRANSFER_ITEMS`, `SEND_MAX_TRANSFER_BYTES` — with the `TimeoutSeconds` they are
> measured against, and the `hasattr` tripwires were removed by the computed bounds that replaced
> them. Full entry: *The three transfer caps are each measured against a DIFFERENT budget
> (SPEC-166)*.

## History

### 2026-08-10

- **Settled:** SPEC-165.
