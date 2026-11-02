---
type: Decision
title: "The ceiling ships with its rule, again"
description: "The top-level `TimeoutSeconds` ships together with an EventBridge rule on `TIMED_OUT` only, never `FAILED`, and a notify-failure door with the `DescribeExecution` fallback."
---

`TimeoutSeconds` 10,800 is **top-level** (SPEC-157 settled that distinction), and it arrived in one
PR with the EventBridge `TIMED_OUT` rule, `ar_notify_failure`'s second door and its 15s → 60s
raise. AWS catchers cover Task, Parallel and Map states but **not top-level execution failures**, so
without the rule the ceiling terminates the run outright and the actor is told nothing — SPEC-152
satisfied on paper and silent in practice, on the one failure where the user has been waiting three
hours. `TIMED_OUT` only, never `FAILED`, or every caught failure double-notifies.

The door needs the same `DescribeExecution` fallback file-send's does, and for the same reason:
EventBridge caps an event at 256 KB and this plane's execution input is the Pipe's record, which
`ARCHIVE_MAX_ITEM_BYTES` deliberately allows to approach 200 KB — so the biggest selections, the
ones that run for hours, are exactly the ones the event alone cannot attribute. What the timeout
message may PROMISE is decided by where a timeout can land: the deletion is downstream of the gate,
so a timed-out archive has never deleted anything, whatever else it did. **Superseded:** the ceiling
can land while `delete-source` runs, and a running invocation outlives it — the promise is now earned
by the verdict record ([entry](a-timeout-does-not-stop-a-running-verb-so-the-timeout-door-claims-the.md)).

## History

### 2026-08-12

- **Settled:** entered the register.
