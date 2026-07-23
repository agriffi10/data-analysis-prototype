# Spec: Structured Logging — Instrument the Control-Plane DLQ Drain

**ID:** SPEC-133
**Status:** Draft
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-126 (the drain), SPEC-127/129 (the pipe)

## Overview

`control-plane-dlq-drain` is the only shared control-plane function with neither
`observability.init` nor `@traced` — it is entirely outside the structured-logging pipe. That
matters more here than anywhere else, for a reason specific to what the drain does: **consuming a
DLQ message destroys the evidence.** SPEC-126 FR-004 traded each request DLQ's 14-day retention
for a CloudWatch log group's 14-day retention, and named that as the deliberate price of the user
finding out about the failure at all.

`logs/` is in the admin bucket and is retained **forever** (SPEC-127 FR-009). So instrumenting
this function is not only about traces: writing the redacted dead-lettered body as a structured
event upgrades the forensic record of every request that never started, from a copy that expires
in fourteen days to one that does not expire. The body is request metadata — ids, locations,
space and table names, a token that is already redacted before anything logs it — and under
SPEC-130 FR-005 that is exactly what an admin-bucket store is for.

The drain also runs precisely when something has already failed invisibly, and is total by
construction on every path — which is what makes its own silence expensive. A sweep that could
not derive a recipient, could not read a queue, or found no descriptor for a queue ARN currently
says so only to CloudWatch.

## Scope

### In Scope

- `observability.init(service="dlq-drain")` and `@observability.traced("drain")`.
- A `step` child span per queue swept.
- One event per dead-lettered message, carrying its outcome and its **redacted, size-capped body**.
- Events for the sweep's own failure paths: unreadable queue, failed delete, malformed
  `DLQ_ARNS`, unrecognised queue ARN.
- The infra this needs: `LOGS_QUEUE_URL` on the function, and `sqs:SendMessage` on the logs queue
  in the drain's execution role.

### Out of Scope

- **Any change to what the drain does.** Recipient derivation from the verified token, the
  no-value-from-the-body rule for notification text, delete-regardless-of-outcome, the dedup id,
  the round caps, the long-poll interval, `UNDRAINED_QUEUES` — all unchanged. Observation only.
- **Removing or shortening the CloudWatch forensic log** (SPEC-126 FR-004). It stays as written,
  and so does the log group's 14-day retention. `logs/` becoming a permanent second copy is an
  argument for changing that retention; it is not this spec's decision to make.
- **Draining the notifications DLQ.** Still deliberately undrained — asking the queue that just
  failed to deliver to deliver the news about itself (SPEC-126 FR-006).
- **The other three control planes** — table-builder, table-share, shared-space — still
  uninstrumented.

---

## Functional Requirements

### FR-001: The drain joins the pipe

#### Description

`service="dlq-drain"`. Not a control plane and not `observability`: the drain spans all four
planes and is nobody's verb, so it gets its own queryable set at
`logs/service=dlq-drain/year=…/month=…/day=…/data.jsonl`.

The name is load-bearing in a way that is easy to miss. `service` becomes an S3 key, so the sweep
pattern-validates it against `^[a-z][a-z0-9-]{2,62}$` and routes anything failing it to
`logs/_unrouted/` (SPEC-129). A service name that does not match would not fail loudly — it would
quietly file every one of this function's events under `_unrouted`.

#### Acceptance Criteria:

- [ ] `observability.init(service="dlq-drain")` at module scope, and `@observability.traced("drain")`
      on `handler`.
- [ ] A test asserts `"dlq-drain"` matches `log_sweep.SERVICE_RE`, so the name is checked against
      the routing rule rather than against a human's reading of the pattern.
- [ ] `@traced` is the only decorator on `handler`; there is no `notifies_on_failure` here, since
      this function *is* a failure handler and has no upstream to notify through.
- [ ] `LOGS_QUEUE_URL` stays optional by construction — a drain deployed without it logs to stdout
      and still drains. No `_require`.

### FR-002: `request_id` is a field here, never baggage

#### Description

Every other instrumented function handles one request per invocation, so `traced` stamps
`request_id` into baggage once and every event inherits it. **The drain handles up to 400 messages
per invocation, each its own request.**

Baggage is per-invocation, and `_reset_baggage()` runs once at the top of `traced`'s wrapper. Set
per message, `request_id` would persist onto the *next* message's events — and a message whose
body has no `requestId` would silently inherit the previous one's. That is the fabricated
correlation key SPEC-128 FR-002 exists to forbid: it merges two unrelated requests into one query
result and nothing about the output looks wrong.

So the run's id rides as an explicit **field** on each per-message event, and the handler's own
span carries no `request_id` at all.

#### Acceptance Criteria:

- [ ] No call to `lf.set_baggage(request_id=…)` anywhere in `dlq_drain.py`.
- [ ] Each per-message event carries `request_id` as a field when the body has a usable one, and
      **omits the field entirely** when it does not — never empty string, never null.
- [ ] A test drains a batch of three messages where the **middle one has no `requestId`** and
      asserts the middle message's event has no `request_id` field and that the third message's
      event carries its own. This is the leak, and it is the only test that would catch it.
- [ ] The handler's boundary spans carry no `request_id`. A test asserts
      `observability._extract_request_id` returns `None` for both shapes this handler receives —
      the EventBridge schedule event and `{"Records": [...]}` — neither of which is currently
      covered, since the extractor was built for the state payload and the raw Pipe envelope.

### FR-003: The dead-lettered body becomes a permanent forensic record

#### Description

The body is the one thing worth keeping and the one thing consuming the message destroys. It goes
into the event, through the same `_redacted` the CloudWatch line already uses.

Three properties are required, and each closes a specific hazard:

- **Redacted.** `_redacted` blanks *every* known token field, not just the one this source
  expects, because a malformed body may carry the wrong one. A token is a bearer credential and is
  excluded from the store regardless of provenance (SPEC-130 FR-005).
- **Size-capped.** The body is unbounded, untrusted input, and every event is appended into a day
  object the sweep rewrites **in full** on every sweep. One pathological body would be paid for
  every ten minutes for the rest of the day.
- **Never re-parsed into fields.** The redacted body is one field, serialized. Promoting
  attacker-controlled keys into the event's own field namespace would let a body shadow
  `request_id`, `verb` or `service`.

#### Acceptance Criteria:

- [ ] Each per-message event carries the redacted body as a **single** JSON-serialized field.
- [ ] A test asserts a body carrying **all four** token field names emits none of their values —
      driven from `SOURCES`, so a fifth control plane's token field cannot be added without this
      test covering it.
- [ ] The serialized body is truncated at a stated cap, and a truncated event carries an explicit
      flag plus the original length. A silently truncated forensic record is worse than a short
      one, because it reads as complete.
- [ ] An **unparseable** body — the case where there is no structure to redact and no token to
      identify a recipient — is logged as a bounded `repr`, not as raw text. `repr` escapes
      newlines and control characters, so an attacker-supplied body cannot forge a second log
      line. Same bounded-`repr` posture as `log_foundry.decorator._warn_rejected`.
- [ ] No key from the body is promoted to a top-level event field. A test feeds a body containing
      `{"verb": "x", "service": "y", "request_id": "z"}` and asserts the event's own `verb`,
      `service` and `request_id` are unaffected.

### FR-004: One event per message, and why that is right here

#### Description

Each dead-lettered message gets an event naming its outcome: notified, no verified recipient,
unparseable body, or no descriptor for the queue ARN.

This is the **opposite** of SPEC-131 FR-005, which prohibits per-message events in the log sweep,
and the difference is worth stating so the two are not read as inconsistent. The sweep emits into
the queue it drains, so a per-message event gives that queue a floor it can never drain below.
The drain emits to the **logs** queue and drains the **request DLQs** — different queues, no
feedback loop. And these DLQs are empty by design: a message on one is a rare event that a person
is going to be asked about. Bounded by the existing caps at 10 rounds × 10 messages × 4 queues,
with a normal case of zero.

#### Acceptance Criteria:

- [ ] One `info` event per successfully notified message, carrying the queue's domain segment, the
      recipient username, `ApproximateReceiveCount`, whether a dedup id was derived, and the body
      (FR-003).
- [ ] One `error` event per message that could **not** be notified about, with the reason as a
      stable token (`unparseable-body`, `no-verified-recipient`, `no-descriptor`) — these are the
      cases where a user is never told their request died, which is the exact invisibility
      SPEC-126 exists to end.
- [ ] The recipient username is logged. It is the S3 prefix, the principal tag and the Glue
      database name already (SPEC-033), and "which user was affected" is the first question asked
      about a dead-lettered request.
- [ ] `step("sweep-queue")` wraps `_sweep_one_queue`, so each of the four queues gets its own
      duration and status; a test asserts four child spans on a four-queue sweep.
- [ ] A sweep that drains nothing — the overwhelmingly common case — emits **no** per-message
      events and no per-queue narrative beyond the four step spans.

### FR-005: The sweep's own failures are events

#### Description

Four paths where the drain continues, or stops, while something is wrong. Each is a
`logger.exception` today, and one of them is a silent total failure of the entire function.

#### Acceptance Criteria:

- [ ] A malformed `DLQ_ARNS` emits `error` — the handler sweeps **nothing** and returns
      `{"drained": 0}`, which is indistinguishable from a healthy idle sweep in every field it
      reports. A deploy error that disables the drain must not look like a quiet Tuesday.
- [ ] A failed `receive_message` emits `error` naming the queue, and the sweep moves on.
- [ ] A failed `delete_message` emits `warning` naming the queue, and the event states the
      consequence: the message resurfaces on a later sweep and may notify a second time, outside
      the notifications queue's 5-minute dedup window.
- [ ] An `eventSourceARN` matching no descriptor emits `error` with the ARN. It means a
      notification went out with the generic fallback noun — a wrong-but-honest message that the
      coverage test is supposed to make unreachable.
- [ ] Every existing `logging.getLogger()` call is still present and still reached; the diff adds
      lines and removes none.

### FR-006: The handler stays total

#### Description

The drain's defining property: a throw means redelivery, and a message that always throws is
redelivered until retention expires, burning invocations on a failure nobody is watching.
Instrumentation is exactly the kind of change that quietly adds a raise path — a field built from
`body["x"]`, a serialization of something that will not serialize.

#### Acceptance Criteria:

- [ ] A test drives the whole handler — schedule shape and `Records` shape — with a sink that
      raises on **every** emit, and asserts the return value and the notifications emitted are
      identical to the working-sink run.
- [ ] A test feeds a body containing a value that JSON cannot serialize and asserts the message is
      still notified about and still deleted.
- [ ] No emitter argument is built by unguarded subscripting of the body. Field values come from
      `.get`, or from values the handler already derived.
- [ ] `_guarded_notify`'s catch-all is unchanged and still the outermost per-message guard.

### FR-007: The infrastructure the events need

#### Description

Unlike SPEC-130/131/132, this one touches infra: the drain has neither `LOGS_QUEUE_URL` nor
permission to send to the logs queue. Without the IAM the function starts fine and every event
dies in `SQSSink`'s stderr write — instrumentation that looks deployed and is not.

#### Acceptance Criteria:

- [ ] `logs_queue_url` variable on `modules/control-plane-dlq-drain`, wired in `main.tf` from the
      observability module's existing output, and set as `LOGS_QUEUE_URL` in the function's
      environment block.
- [ ] An `EmitStructuredLogEvents` statement in `policies/drain-permissions.json.tftpl` granting
      `sqs:SendMessage` on the logs queue ARN — the same Sid and shape as the statement already in
      `modules/data-quality/policies/execution.json.tftpl`, so the two read as one pattern.
- [ ] The **deploy role** is checked against the repo's adding-a-resource-type rule before the
      code lands, and the finding is recorded either way. No new resource type appears here and
      no new deploy-role grant is expected — but "expected" is not "verified", and this is the
      trap that has cost this repo several rounds.
- [ ] The IAM and the environment variable land and **apply** before the instrumented code
      deploys, matching the standing deploy-perms-before-resources sequence.
- [ ] A live check confirms events arrive at `logs/service=dlq-drain/…` rather than in
      `_unrouted/` or nowhere.

---

## Data Model

Events follow SPEC-127's schema. Field vocabulary introduced here:

```
# per message
domain: "data-quality" | "table-builder" | "table-share" | "shared-space" | "unknown"
request_id: str        recipient: str        receives: int         dedup: bool
body: str              body_truncated: bool  body_length: int
reason: "unparseable-body" | "no-verified-recipient" | "no-descriptor"

# per sweep / per queue
queue: str             drained: int          rounds: int
reason: "receive-failed" | "delete-failed" | "malformed-dlq-arns"
```

`body` is the redacted, capped, JSON-serialized envelope — never re-parsed into fields (FR-003).

## File & Folder Structure

```
lambdas/control-plane-dlq-drain/dlq_drain.py
lambdas/control-plane-dlq-drain/test_dlq_drain.py
infra/modules/control-plane-dlq-drain/{variables,lambda}.tf
infra/modules/control-plane-dlq-drain/policies/drain-permissions.json.tftpl
infra/main.tf                                          # logs_queue_url wiring
```

No new environment variable beyond `LOGS_QUEUE_URL`, and no SPA change.

## Implementation Phases

### Phase 1: Infrastructure, applied first

- `logs_queue_url` variable, `main.tf` wiring, `LOGS_QUEUE_URL` in the environment block, and the
  `EmitStructuredLogEvents` statement.
- The deploy-role verification and its recorded finding.

### Phase 2: Into the pipe

- `init(service="dlq-drain")`, `@traced("drain")`, `step("sweep-queue")`.
- The `SERVICE_RE` test and the `_extract_request_id` tests for both event shapes.

### Phase 3: Per-message events and forensics

- Outcome events; `request_id` as a field with the three-message leak test.
- The redacted, capped body; the unparseable bounded-`repr` path; the field-shadowing test.

### Phase 4: The sweep's own failures, and totality

- The four failure events.
- The failing-sink test over both handler shapes; the unserializable-value test.

### Phase 5: Live verification

- Put a malformed message on one request DLQ, wait one 10-minute sweep, and confirm three things:
  the user is notified, the message is gone, and the **redacted body is in
  `logs/service=dlq-drain/…`**.
- This is also the malformed-DLQ-body check **SPEC-126 still owes** — one notification within a
  ~10-minute sweep naming no path from the body. Discharge it here and note it.
