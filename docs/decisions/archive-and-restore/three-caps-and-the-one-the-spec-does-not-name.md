---
type: Decision
title: "Three caps, and the one the spec does not name"
description: "An archive is capped at 20,000 objects, 3 TiB and 10 GiB per object, each computed by a test reading `locals.tf`; the per-object cap must stay, because nothing else bounds one object's copy time."
---

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

## History

### 2026-08-12

- **Settled:** entered the register.
