# queue-consumer

One Lambda that is the **single writer** of a FIFO queue: the request queue and its own DLQ, the
execution role and its one inline policy, the function (a call to
[`../docker-lambda`](../docker-lambda/README.md)), and the event-source mapping that feeds it. The
caller passes every name, the policy already rendered, the handler, the memory and the environment.

**Every input exists because a caller's value differs.** Its inputs were sized against the two
functions built this shape — the notifications writer and the feedback writer — whose names,
memory, environment and request-queue deduplication differ. Everything else is a literal here:
batch size 1, a 30-second function under a 60-second visibility timeout, a receive count of 3, a
14-day content-deduplicated DLQ, and an inline policy named `writer`.

- **Batch size 1 plus the FIFO group is the single-writer guarantee, without a lock.** Each message
  is its own invocation and the group orders them; raising the batch size breaks it.
- **The function's timeout stays under the queue's visibility timeout**, or a slow write is
  delivered to a second invocation while the first is still making it.
- **The DLQ is the queue's own and nothing drains it here.** Whether a caller's DLQ is drained is
  the drain's decision (`dlq_drain.UNDRAINED_QUEUES`), not this module's.
- **The mapping binds to `function_arn`, never the name**, for the reason `scheduled-function`'s
  permission does: a name is known at plan and survives a replacement undiffed.
- **The policy's queue and log-group ARNs are constructed strings in the caller**, so no policy
  waits on the queue or the function it permits.
