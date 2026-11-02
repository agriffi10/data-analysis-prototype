---
type: Decision
title: "The transfer caps are three, and each is measured against a different budget (SPEC-166)"
description: "`SEND_MAX_OBJECT_BYTES` (10 GiB) is bounded by the copy verb's timeout, `SEND_MAX_TRANSFER_ITEMS` (50,000) by manifest memory and `SEND_MAX_TRANSFER_BYTES` (3 TiB) by run makespan; `inspect-source` enforces all three, counting requested recipients."
---

**Decision.** `SEND_MAX_OBJECT_BYTES` **10 GiB**, `SEND_MAX_TRANSFER_ITEMS` **50,000**,
`SEND_MAX_TRANSFER_BYTES` **3 TiB**, all enforced in `inspect-source` before the plan is written,
and the two product caps measured on the **requested** recipient count.

**Each is a different budget, and using one model for all three is how table-share's own bound came
to be wrong twice.** The per-object cap is bounded by `COPY_TIMEOUT_SECONDS`, the batch verb's own
Lambda timeout — a batch is exactly one round of the worker pool and one object is one worker, so a
batch costs its slowest object. The item cap is bounded by the **memory** the two verbs either side
of the Map hold the manifest in, read back from `locals.tf`. The byte cap is bounded by the whole
run's **makespan** against the machine's `TimeoutSeconds`, at
`MAP_MAX_CONCURRENCY × CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s and **not** the ~4 GB/s the
same constants suggest multiplied together.

**The per-object cap is the one whose absence made every other model a half-truth.** SPEC-165
recorded it as owed and kept the arithmetic: without it the worst legal case was a single 1 TiB
object on one worker — 43,980 s, four times the ceiling — while `test_a_full_size_selection_copies
_inside_the_engines_ceiling` read as satisfied. It is table-share's value exactly, deliberately:
same engine, same batch size, same timeout.

**`SEND_MAX_TRANSFER_ITEMS` deliberately diverges from table-share's 20,000.** That plane's
transfer cap equals its own object cap, so at full size it permits one recipient — fine when a
share is one table. A 2,000-file folder to a 30-person team is the ordinary case here. The computed
memory ceiling is ~150,000 items; 50,000 takes a third of it.

**Measured before the guard, on purpose.** Counting only the recipients who clear their conflict
check would let the expensive half of the work happen first, and would make a refusal depend on
what someone else's inbox happens to hold.

## History

### 2026-08-10

- **Settled:** SPEC-166.
