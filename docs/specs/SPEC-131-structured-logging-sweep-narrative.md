# Spec: Structured Logging — Narrate the Log Sweep

**ID:** SPEC-131
**Status:** Completed
**Last Updated:** 2026-07-23
**Depends On:** SPEC-130 (the emitters and `step`), SPEC-127/129 (the sweep itself)

## Overview

The sweep is the one function in the fleet that already says everything an operator would want —
how many messages it took, how many day-groups they fell into, which keys it wrote, when a write
lost a CAS race, when it hit its cap — and says all of it to CloudWatch only. It is also the
function that *feeds* the structured store, so the asymmetry is conspicuous: `logs/` will tell you
that a sweep ran and how long it took, and nothing about whether it wrote anything or failed
trying.

This spec spends SPEC-130's primitives on `lambdas/log-sweep/log_sweep.py`, so a sweep's intake,
its destinations, and its per-destination success or failure are events in the store rather than
lines in a log group. It also fixes the one thing self-instrumentation makes genuinely dangerous
here — a sweep that emits one event per message consumed would give the logs queue a floor it can
never drain below — by making that bound an explicit, tested requirement rather than an emergent
property of how many `info` calls someone happened to add.

## Scope

### In Scope

- Narrative events for intake, grouping, per-day-group append, and the sweep's outcome.
- A `step` child span around the per-day-group append and around the receive loop.
- Warning events on every degraded-but-continuing path the function already detects.
- An explicit, tested bound on how many events one sweep may emit.
- `sweep_id` as baggage, so a CloudWatch line and a structured event can be joined.

### Out of Scope

- **Any change to what the sweep does.** No change to routing, partitioning, the CAS loop, the
  cap, the delete-after-write ordering, the schedule, or the key layout. This spec adds
  observation and nothing else; a diff that changes behavior is out of scope by definition.
- **Removing the existing `logging.getLogger()` calls** (FR-006 — they stay, deliberately).
- **A per-message event.** Prohibited, not deferred (FR-005).
- **`control-plane-dlq-drain`**, the other scheduled sweeper, which is not instrumented at all.
- **Any Athena table or query over `logs/`.** Still deferred (SPEC-129).

---

## Functional Requirements

### FR-001: The sweep narrates its intake

#### Description

What arrived, and whether that was everything. `_receive_all` already returns `truncated`
precisely so a cap is not silently reported as "swept everything"; that distinction currently only
exists in CloudWatch.

#### Acceptance Criteria:

- [ ] After `_receive_all`, one `info` event carrying the message count and the number of
      day-groups they fell into.
- [ ] A truncated round emits `warning` naming the cap and the count taken, matching the existing
      CloudWatch warning.
- [ ] `_receive_all` is wrapped in `step("receive")`, so the poll loop's duration is separable
      from the write time — the two have completely different failure modes and one is billed per
      round.
- [ ] A sweep that receives **nothing** emits no intake event; boundary spans only (FR-005).

### FR-002: Every destination is named, with its outcome

#### Description

The core of the request: for each object the sweep writes, how many events went into it, where it
went, and whether it worked. `_append_day` is the natural unit — it is already the function that
owns one destination and returns a boolean that today only steers control flow.

The destination key is logged in full — a destination you cannot name is not a destination report.

#### Acceptance Criteria:

- [ ] `_append_day` is wrapped in `step("append-day")`, so each destination gets its own
      `duration_ms` and `status` under the sweep's `trace_id`.
- [ ] On entry, one `info` event with the destination key and the number of events being appended.
- [ ] On success, one `info` event with the key, the number of events appended, and the resulting
      object size — the last of these being the number that makes the read-modify-write cost
      visible before it becomes a timeout.
- [ ] On failure, one `error` event with the key, the event count left queued, and a **stable
      reason token** (`"precondition-exhausted"`, `"write-failed"`) rather than a stringified
      exception. A reason you can filter on is worth more than a message you can read once.
- [ ] Both outcomes are covered by tests. The failure test asserts the `error` event fires on the
      path where messages stay queued — the case that matters is the one where data did not land.

### FR-003: Degraded paths are warnings, not silence

#### Description

The sweep has four paths that continue while something is wrong, and each is currently a
CloudWatch line. They are the early symptoms of the failures that eventually matter — a day
object growing past the point where rewriting it in full is affordable, or two sweeps overlapping.

#### Acceptance Criteria:

- [ ] A CAS precondition failure emits `warning` with the attempt number and the cap, once per
      retry — the retry count *is* the contention signal.
- [ ] A day object over `LARGE_OBJECT_WARN_BYTES` emits `warning` with the key and the size.
- [ ] Events with an unusable timestamp emit `warning` with the count that fell back to the sweep
      clock. A systematic producer problem shows up as a rising count rather than as events
      quietly landing in the wrong day.
- [ ] A failed `delete_message_batch` emits `warning` with the count, and the event states the
      consequence — the events are already durable, so this means duplicates next sweep, not loss.
- [ ] Unroutable bodies emit `warning` with the count routed to `_unrouted`. The **body is not
      logged** — not on sensitivity grounds but on redundancy and size: it is already preserved
      verbatim at `logs/service=_unrouted/…`, where it can be read deliberately, and it is
      unbounded input from a queue, so echoing it into a day object risks the very growth the
      read-modify-write design is careful about.

### FR-004: The outcome event is total

#### Description

One terminal `info` per sweep that answers "did this sweep do its job", including the cases where
it did nothing. The existing summary line reports `swept`, `groups` and `written` but not
`failed`, so a sweep that wrote two of three destinations and left one queued reads as a success
in every field it reports.

#### Acceptance Criteria:

- [ ] One outcome event per non-empty sweep, carrying messages received, day-groups, events
      written, and events **failed** (left queued).
- [ ] It is emitted at `error` level when any destination failed, `info` otherwise — so "a sweep
      that partly failed" is reachable by level, not only by reading a field.
- [ ] The early-return paths (`LOGS_QUEUE_URL` or `ADMIN_BUCKET` unset) emit `warning` before
      returning. Configuration missing on the function that collects everyone's logs is the
      failure most likely to be discovered late.
- [ ] The handler remains total: no emitter, and no `step`, may introduce a path on which the
      sweep raises. A test drives the whole handler with a sink that raises on every emit and
      asserts the return value is unchanged.

### FR-005: One sweep's events are O(1) in the messages it consumes

#### Description

The sweep instruments itself, and that closes a loop the other control planes do not have: the
events this function emits go to the queue this function drains. If the sweep emitted one event
per message swept, then consuming M messages would produce ~M messages for the next sweep, and
the queue would have a floor it can never drain below — the pipeline would be permanently busy
carrying its own telemetry, with the day objects growing accordingly.

The bound is therefore structural: **the number of events one sweep emits must depend on the
number of day-groups, not on the number of messages.** Day-groups are bounded by the number of
control planes (plus `_unrouted`); messages are not bounded by anything.

Concretely, the design above emits **`6 + 4G`** events per sweep for `G` day-groups, and **4 on
an empty sweep** — measured, 2026-07-23. (This corrects the `6 + 3G` / floor-of-2 arithmetic
first written here, which did not count `step("receive")`'s own boundary pair or the
per-destination entry event, both required by FR-001 and FR-002 above. The bound's *shape* —
O(1) in messages, O(G) in day-groups — is unchanged, and it is the shape that matters.)

At 144 sweeps a day and the current 2–3 services that is a few thousand events a day of
self-telemetry, all of it appended into `logs/service=observability/…`, which is a few hundred
KB.

#### Acceptance Criteria:

- [ ] No emitter is called from inside a per-message loop. No `step` wraps a per-message function.
- [ ] A test sweeps a large batch (≥200 messages) across a fixed small number of day-groups with a
      capturing sink, and asserts the emitted event count is **bounded by a function of the group
      count only** — that the same event count results from 20 messages and from 200.
- [ ] That test is written so it fails if a per-message emitter is later added. This is the guard,
      not the comment.
- [ ] A comment at the sweep's emitters records the feedback loop and why the bound exists, in
      terms of the queue floor rather than of cost.

### FR-006: CloudWatch keeps everything it has

#### Description

The existing `logging.getLogger()` calls stay, all of them, alongside the new events. This looks
like duplication and is not.

The sink is SQS-only, not `MultiSink(Stdout, SQS)` — a settled decision (SPEC-127, user,
2026-07-22) whose stated cost is that if the queue or the sweep breaks, that window's structured
data is gone. For **this** function that cost is qualitatively different than for a verb: the
sweep's own structured events are delivered by the mechanism the sweep is. A sweep that cannot
write to S3 cannot report, through the structured store, that it could not write to S3. Its
CloudWatch line is the only account of the failure that exists.

#### Acceptance Criteria:

- [ ] Every existing `logger.info` / `warning` / `error` / `exception` call in `log_sweep.py` is
      still present and still reached; the diff adds lines and removes none.
- [ ] A comment above the sweep's emitters records why the duplication is deliberate here and not
      a pattern to copy into a verb.
- [ ] No `echo=True` — the console duplicate is not the mechanism providing this, and it is
      prohibited outright (SPEC-130 FR-006). The CloudWatch account comes from the existing
      `logging` calls, which are a separate pillar and stay a separate pillar.

### FR-007: `sweep_id` joins the two accounts

#### Description

`sweep_id` is already minted per invocation and appears in exactly one CloudWatch line. Promoting
it to baggage makes it a field on every structured event from that invocation, so the CloudWatch
line and the structured events for one sweep can be joined — the same role `request_id` plays for
a data-quality run, for a function that has no request.

#### Acceptance Criteria:

- [ ] `sweep_id` is set as baggage at the top of the handler, before any emitter runs, and appears
      in `fields.sweep_id` on every event from that invocation including the boundary spans.
- [ ] It is minted **once** per invocation and included in every CloudWatch line the function
      writes, not only the summary. A join key present on one side of the join is not a join key.
- [ ] The existing `_reset_baggage()` in `traced` still clears it between warm invocations; a test
      asserts two successive sweeps carry different `sweep_id` values.

---

## Data Model

No stored shape changes. Events follow SPEC-127's schema; the sweep's own events land in
`logs/service=observability/year=…/month=…/day=…/data.jsonl` as they already do, one sweep behind
(this invocation's events are collected by the *next* sweep — unchanged, and still not recursive).

Field vocabulary introduced by this spec, all operator-owned:

```
messages: int      groups: int        written: int       failed: int
key: str           events: int        bytes: int         attempt: int
truncated: bool    undated: int       unrouted: int      sweep_id: str
reason: "precondition-exhausted" | "write-failed"
```

## File & Folder Structure

```
lambdas/log-sweep/log_sweep.py
lambdas/log-sweep/test_log_sweep.py
```

No infra change, no IAM change, no new environment variable, no SPA change.

## Implementation Phases

### Phase 1: Intake, outcome, and the identity field

- `sweep_id` to baggage and onto every CloudWatch line.
- Intake and outcome events, including the early-return and empty-sweep paths.

### Phase 2: Destinations and degraded paths

- `step("receive")` and `step("append-day")`.
- Per-destination entry/success/failure events; the four warning paths.

### Phase 3: The bounds, tested

- The O(1)-in-messages test, written to fail on a per-message emitter.
- The failing-sink test over the whole handler.
- Comments recording the feedback loop and the deliberate CloudWatch duplication.
