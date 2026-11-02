---
type: Decision
title: "The bound is botocore's connection pool, not the thread count"
description: "`RESTORE_HEAD_CONCURRENCY` stays at 8, inside botocore's default pool of 10, and the verb's timeout pays for the work; `RESTORE_CONFLICT_SAMPLE` is only a presentation bound."
---

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

## History

### 2026-08-12

- **Settled:** entered the register.
