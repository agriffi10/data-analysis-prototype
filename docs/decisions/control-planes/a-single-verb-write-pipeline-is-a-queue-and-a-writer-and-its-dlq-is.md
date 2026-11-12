---
type: Decision
title: "A single-verb write pipeline is a queue and a writer, and its DLQ is undrained for a reason of its own (SPEC-211)"
description: "Feedback is one FIFO queue and one writer, with no Pipe or machine, sent on the API's own role; its DLQ is undrained because the body carries no identity, and a day file is only ever extended, keyed on the API's `submittedAt`."
---

Give feedback adds one verb: take what a user typed and append it to that day's file. It gets a
FIFO queue, one writer Lambda and nothing else — no Pipe, no state machine, no fan-out, no
validate-authorize verb. That is `notifications`' shape rather than a control plane's, and the
test for which shape a feature needs is the verb count, not whether the work is privileged.

**It is the first feature built API-first, and that is what makes a submission attributable.**
Every other enqueue in this product began as a browser call to SQS on the caller's own scoped
credentials, and Arc B is porting them. Adding a sixteenth would have been adding work to the port
in the same breath as writing it. So the browser posts to `POST /v1/feedback`, the API verifies
the bearer, and the API sends on **its own execution role** — which means the portal role holds no
statement naming this queue and never did. On the user plane it would have to, ~~and then any
signed-in caller could write a feedback record under whatever username it chose, because no SQS
condition key reaches a field inside a message body~~ **— superseded since SPEC-202 retired the
Identity Pool:** no caller holds portal-role credentials, so the grant would instead ride on every
session the API mints for every user, and no SQS condition key reaches a field inside a message
body to tie a record to its sender. The request type declares no username field,
so there is nothing for the handler to ignore.

**It is NOT one of the ten enqueue routes, and the reason is the wire rather than the plumbing.**
Those carry a nested `identity` block, echo a `requestId` the caller minted, and answer
`EnqueueAccepted`; this carries a top-level `username`, mints its own `eventId`, and answers with
the stamp. Serving it through `apicommon.enqueue` would have meant three exemptions inside a
family whose parametrized guards exist precisely to refuse exemptions —
`_stamped_values`' literal four-route table, the identity-block assertion, and the request-id echo.
For the same reason its queue is **not** in `contract.QUEUES`: that registry is guarded for set
equality with `ENQUEUE_ROUTES` in both directions, so registering it would mean loosening the
guard with a hand-maintained exemption. It reads `FEEDBACK_QUEUE_URL` through its own accessor
instead, and the one thing that costs — the swapped-pair wiring guard — is written out explicitly
in `test_queue_writers.py` rather than left as a gap. What the two DO share is what a failed
`SendMessage` means to a caller, which is why that classifier moved to `apicommon.queue_faults`
rather than being copied.

**Its DLQ is undrained for a reason that is not the notifications one**, and conflating them is
the mistake to avoid: notifications' DLQ is circular, because the drain's only delivery channel is
that very queue. Feedback's is different — the drain resolves its recipient from the verified
`identity` block in the message body, and a feedback body carries none by design. Draining it
would mean notifying whoever an untrusted body field named, which is the exact inversion the
drain's recipient rule exists to prevent. The two reasons are now a mapping in
`_UNDRAINED_BY_DESIGN` rather than a set named for one of them, because widening a set named for
one reason until it holds queues that are there for another makes the name a lie and reduces the
assertion to a transcription of the production value.

**The user's guarantee is deliberately narrow: the 200 means the submission reached the queue.**
Nothing after that point is something a user could act on, which is why nothing after that point
tells them anything — and why leaving the DLQ undrained is consistent rather than a gap. What
exists to notice a death is the writer's invocation-error metric and the messages sitting in a
14-day queue. **There is no alarm on the DLQ, by Andrew's decision (2026-09-27)**, and for the
same reason: a guarantee that ends at the queue needs nothing more than that metric and the kept
messages. An alarm would also tell nobody, because the fleet's one alarm carries no action by
decision (`infra/modules/observability/alarm.tf`), so one here would be a console state and nothing
else. Since the writer appends past a day-file line it cannot parse, a bad line no longer
dead-letters anything; a message whose every receive fails still does, and a failure that
repeats — an out-of-memory kill on a large day, sized against rather than watched
(`infra/function-feedback.tf`) — takes the rest of that day with it.

**The writer holds no `s3:ListBucket`, which inverts the fleet's usual rule and is safe for one
specific reason.** A role that cannot list a bucket cannot be told an object is absent — S3
answers `NoSuchKey` only to a caller holding it — so an `except NoSuchKey` branch normally needs a
covering grant. This writer never claims absence: **any** read failure is reported as "no object,
no tag", which makes the following write conditional on `If-None-Match: *`. A transient fault or a
denial then loses its precondition, the loop re-reads, and exhausting the attempts raises so the
message dead-letters. So there is no absence branch to authorize, and the read is dispositioned
`fail-safe-cas` rather than `list-grant`.

**A day file is never replaced, only extended — and a line it cannot parse is reported, not
refused.** The records are somebody's only copy and the admin bucket has versioning off, so a
writer that "recovered" by overwriting would lose a whole day to fix one bad byte. The file is
JSONL, and the writer keeps the bytes it read exactly and adds one line after them, so a line it
cannot parse loses nothing by being written past; a warning names the key, how many lines and the
first one's number, never the text. It was refused while the day was one JSON document the writer
re-serialised whole, following SPEC-159's reasoning for an unreadable settings document. Once the
append stopped rewriting anything, the refusal protected nothing and only dead-lettered every later
submission that day into a queue nobody drains. The days written as documents, under the two
earlier layouts, were not moved; the module README names both.

**The day comes from the submission, never from the writer's clock.** `submittedAt` is stamped by
the API, is what the `MessageGroupId` is derived from, and is what the key is built from — so the
object a submission lands in was decided when it was submitted, and every message destined for one
day serializes behind the previous one. That is the contention the compare-and-swap would
otherwise have to retry through. A writer that used its own clock would file a redelivered message
in the day somebody is currently reading rather than the day it belongs to, and an unparseable
stamp is refused rather than defaulted for the same reason.

**Rejected: a control plane.** One verb does not earn a queue, a Pipe, a state machine and a
fan-out. **Rejected: any read surface.** No list, no admin view, no notification, no reply — the
records are read with the AWS CLI by whoever wants them, and write-only from the browser's side is
what keeps feedback out of every rendering and escaping question in the app. **Rejected: a shared
DLQ.** A malformed feedback submission must not dead-letter somebody's file operation.

## History

### 2026-08-28

- **Settled:** SPEC-211.
