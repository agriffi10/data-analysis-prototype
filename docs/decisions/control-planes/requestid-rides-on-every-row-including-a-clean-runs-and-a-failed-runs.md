---
type: Decision
title: "`requestId` rides on every row, including a clean run's and a failed run's (SPEC-191)"
description: "**`requestId` rides on every row**, a clean run's and a failed run's included, because a reader settles its in-flight record by matching it; the validator and both doors of the failure terminal must name it, since every validate-stage refusal once landed with `payload: null` in production. **The browser's async switchover consults the routing predicate ONCE**, above every submission point, in one dispatcher. The in-flight record is **session-scoped, never persisted**, and settles on a notification carrying its request id."
---

A reader settles its in-flight record by matching it, and a clean run has nothing to re-submit — so
scoping the field to "what a re-submit needs" would leave successful operations unsettled. The same
argument applies one path over, to a run that **failed** before the producer ever ran, which settles
nothing otherwise; so the two failure emitters carry a minimal `{requestId}` payload too. That is
beyond the spec's own acceptance criteria and was built deliberately. Besides a request with no
verified actor, which has no inbox to be told in, the one refusal that writes no row is a reused
request id: the run holding the id reports under it, and its outcome row is the one the card should
settle on ([told to nobody](a-reused-request-id-is-told-to-nobody-because-the-run-holding-the-id-is.md)).

**Built into the emitters, it still never reached a failure row, and why is the lesson.** The
emitters forward whatever id their event names, and their test handed them one. The validator
builds that event by hand and left the id out, so every validate-stage refusal landed with
`payload: null` in production, and the failure terminal sent no payload on either of its doors.
Now the validator names the id, and the terminal reads it through
`observability.request_id_of`, which finds it in the forwarded request wherever the seed nulled it.
The tests drive the validator's handler and the terminal's doors, because an emitter's own test
cannot see what its caller leaves out. Results-conversion had the same two gaps: its terminal sent
no payload, and its validator named the id only once the contract passed. Both took the same fix,
though no reader tracks a conversion in flight yet: every row the plane's own Lambdas write now
carries the id, and the first reader built would otherwise miss exactly the failures nobody
exercises.

**The shared DLQ drain writes the id too, on every plane it drains whose request names one** —
all but table-share, which has no request id. That closed the last row that settled nothing: a
dead-lettered file operation held its card, and the space's submit gate, until the card's
three-hour expiry unless the user dismissed it. The drain predates the payload field, and adding
one took an argument, because the drain's rule is that no value from the untrusted body reaches
the message and this takes one into the row. The rule still governs the message. The id is
admitted to the payload, alone, on three grounds. The recipient is the actor the API stamped, and
a delegated one is refused, so the id lands only in the inbox of the caller who chose it. The
other two are particular to the id: only the API writes the block a recipient is read from, and
it also made the id the message's deduplication key, so SQS has already held it to 128 printable
ASCII characters — the operator reader's `requestId` is not its dedup key, but its messages carry
no block and notify nobody; and no reader renders the id as text — the browser keeps a payload
only when its id cannot change a URL, and matches on it. A `{requestId}`-only row reads to the
file-ops card as a refusal, the word it uses for every run that failed before an outcome, and the
notification beside it says the request never started.

The browser's async switchover consults the routing predicate once, above every submission point, in one dispatcher. The in-flight record is session-scoped, never persisted.

## History

### 2026-08-17

- **Settled:** SPEC-191.
