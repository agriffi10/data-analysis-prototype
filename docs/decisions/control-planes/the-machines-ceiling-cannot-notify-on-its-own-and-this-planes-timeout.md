---
type: Decision
title: "The machine's ceiling cannot notify on its own, and this plane's timeout door needs a fallback (SPEC-166)"
description: "File-send's machine has a 10,800 s top-level `TimeoutSeconds` with a `TIMED_OUT` rule, and its timeout door reads the input back with `states:DescribeExecution` because EventBridge drops an input over 256 KB; the Lambda execution role holds that grant."
---

**Decision.** A top-level `TimeoutSeconds` of 10,800, shipped together with an EventBridge rule on
`Step Functions Execution Status Change` / `TIMED_OUT`, a second door in `fs_notify_failure`, that
verb's raise to 60s, and the deploy role's `events:` grant.

**Why together.** AWS catchers cover Task, Parallel and Map states but **not top-level execution
failures**: the timeout terminates the run outright, so no state runs, no `Catch` fires, and the
machine's own `NotifyFailure` is unreachable on the one failure it most exists for. `TIMED_OUT`
only, never `FAILED`, or every caught failure notifies twice. A second
rule, matching `FAILED` only for those two error names, was SPEC-236; Andrew cancelled it on
2026-09-16.

**The budget is computed, every term of it**: copying 6,597 s + per-child overhead 939 s + guard Map
600 s + serial verbs 735 s = 8,871 s against 10,800 s. The only input without a measurement behind
it is the per-**round** child overhead — charged per round because slots pipeline — and it is
load-bearing: charged per child at even half a second the budget would blow. The test states its
own break-even (~9 s per round).

**The door needs a fallback table-share does not.** EventBridge caps an event at 256 KB and Step
Functions drops the input rather than exceed it, while `SEND_MAX_ITEM_BYTES` deliberately allows a
Pipe record approaching 200 KB — so the sends most likely to time out are exactly the ones the
event alone cannot attribute. The door reads the input back with `states:DescribeExecution`, on the
**Lambda execution role**, because EventBridge invokes the notifier outside any execution.

**And the seed that reports all of this must not carry the request twice.** `RequestFailureSeed`
supplies `$.raw` (the Pipe record, ~200 KB at the cap) and **not** `$.source`, which is the same
selection again: together they breach the 256 KB state limit for a quote-heavy legal request, on a
Pass with no `Catch`, killing the run before `NotifyFailure` at the end of a three-hour copy.
Nothing on the failure path reads the source; an operator has it inside `raw`.

## History

### 2026-09-16

- **Changed:** Andrew cancelled SPEC-236, the second rule that would have matched `FAILED` for the two uncaught error names.

### 2026-08-10

- **Settled:** SPEC-166.
