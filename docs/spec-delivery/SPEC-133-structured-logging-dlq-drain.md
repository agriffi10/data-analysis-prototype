# Completed Spec — SPEC-133: Instrument the Control-Plane DLQ Drain

## What was completed?

`control-plane-dlq-drain` was the only shared control-plane function outside the pipe entirely —
no `init`, no `@traced`. It now joins as `service="dlq-drain"`, with a `sweep-queue` child span per
queue, one event per dead-lettered message, and events for the sweep's own four failure paths.
**No behaviour change.** Shipped as two PRs: infra, then code.

**Its point is not traces.** Consuming a DLQ message *destroys the evidence*: SPEC-126 FR-004
knowingly traded each queue's 14-day retention for a log group's 14-day retention as the price of
the user finding out at all. `logs/` is retained forever, so writing the redacted body here
upgrades that record from a copy that expires to one that does not.

## The two decisions worth carrying forward

**`request_id` is a field here, never baggage (FR-002).** Every other instrumented function
handles one request per invocation, so `traced` stamps it into baggage once. The drain handles up
to **400 messages per invocation** while `_reset_baggage()` runs *once*. As baggage, a message
with no `requestId` would silently inherit its predecessor's — the fabricated correlation key
SPEC-128 FR-002 forbids, which merges unrelated requests and looks entirely normal in the output.
Omitted entirely when absent, never empty.

**One event per message is correct here and prohibited in the sweep**, which only looks
inconsistent. The sweep emits into the queue it drains, so a per-message event gives that queue a
floor it can never get below. The drain emits to the *logs* queue and drains the *request DLQs* —
different queues, no feedback loop, and empty by design.

## The forensic body

Redacted (every **known** token field, not just this source's, because a malformed body may carry
the wrong one), size-capped (unbounded untrusted input, appended into a day object the sweep
rewrites in full every ten minutes), and carried as **one serialized field** — never re-parsed
into fields, or a body could shadow `request_id`, `verb` or `service`. An unparseable body is a
bounded `repr`, so newlines and control characters cannot forge a second record.

## Infrastructure

`LOGS_QUEUE_URL` + an `EmitStructuredLogEvents` statement, landed and **applied** in a separate PR
ahead of the code, per the standing deploy-perms-before-resources sequence. Without the IAM the
function starts fine and every event dies in `SQSSink`'s stderr write — instrumentation that looks
deployed and is not.

**Deploy-role finding, verified rather than assumed:** no new grant needed. The statement lands in
the drain's existing inline role policy (`iam:PutRolePolicy`, already scoped to that role), the
env var is an `UpdateFunctionConfiguration` on a function the role already manages, and both
values are `module.observability` **outputs** — attributes of an `aws_sqs_queue` already in state,
so no data source and no new read permission. The CI plan confirmed it independently:
**0 to add, 2 to change, 0 to destroy.**

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1239 passed / 2 skipped at the time of merge.

**Fourteen mutations, all observed to fail — and one survived the first round, exposing a
tautological test.** Removing `default=str` from the forensic dump makes `_forensic` raise;
`_guarded_notify` swallows it, so the message is still notified and still deleted. The test
asserted exactly those outcomes, so it passed while the permanent forensic record — the entire
point of FR-003 — was silently lost. It now asserts the **event was emitted**.

That is the same failure shape SPEC-132's harness found: the test measured an adjacent quantity
and read it as evidence for the thing it cared about.

## Still owed — Phase 5 (live)

Put a malformed message on one request DLQ, wait one 10-minute sweep, confirm three things: the
user is notified, the message is gone, and the **redacted body is in `logs/service=dlq-drain/…`**.

This also discharges the malformed-DLQ-body check **SPEC-126 has owed since it shipped** (one
notification within a ~10-minute sweep, naming no path from the body). Deferred to the user.
