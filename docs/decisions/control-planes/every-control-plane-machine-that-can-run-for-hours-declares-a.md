---
type: Decision
title: "Every control-plane machine that can run for hours declares a TimeoutSeconds (SPEC-161)"
description: "**`TimeoutSeconds` is TOP-LEVEL and cannot notify on its own**: catchers do not cover top-level execution failures, so a ceiling ships **with** an EventBridge `TIMED_OUT` rule (never `FAILED`, or every caught failure double-notifies). The cost, an uncaught `DataLimitExceeded` or `Runtime` telling nobody, is accepted, and a `FAILED` door has three traps (`every-plane-notifies-on-a-pre-verb-failure-and-failure-reason-is-the.md`)."
---

A Standard workflow with no `TimeoutSeconds` runs to Step Functions' default of **one year**. That was harmless while the copy was one Lambda bounded by its own 900-second timeout; once SPEC-160 made it a Distributed Map and SPEC-161 raised the byte cap to 1 TiB, "wedged" became a state a run could sit in indefinitely.

**It is a TOP-LEVEL ASL field** — beside `StartAt`, not an argument to `aws_sfn_state_machine` and not a task field (SPEC-157 settled the same distinction for the table-builder's lock). On a Task it would bound one step, which is not what a wedged *run* needs.

**And a top-level timeout CANNOT reach `NotifyFailure`, which is the trap this entry exists to record.** The state sits in the machine looking exactly like it would. It does not: AWS documents that *"Step Functions catchers are available for Task, Parallel and Map states, but not for top-level state machine execution failures"*, and the remedy it names is *"listen for `TIMED_OUT` events from Standard workflows with an EventBridge bus"*. A top-level expiry terminates the execution outright — no state runs, no `Catch` fires. **A `TimeoutSeconds` shipped alone would therefore have bounded the run and made the sender's silence permanent instead of merely long**, which is worse than it sounds: SPEC-152's guarantee would read as satisfied by a state that could never be reached.

So the field ships **with an EventBridge rule** (`stepfunction.tf`) on `Step Functions Execution Status Change`, matching **`TIMED_OUT` only** and invoking the same `notify-failure` verb through a second door. AWS classifies Step Functions execution events as **best-effort delivery**, so this closes the hole rather than sealing it — a dropped event means the old silence for that one run. That is accepted: the alternative is polling `ListExecutions`, which is a scheduled sweep and a second moving part for a failure mode measured in runs per year. `TIMED_OUT` only is load-bearing: every whole-request failure a `Catch` takes already reaches the verb and ends at `Fail`, whose status is `FAILED`, so matching both would send a second notification for every caught failure. The two doors are disjoint by construction, not by a suppression rule.

**The timeout door recovers the sender from the token, and expiry is deliberately not enforced.** The execution input is what the Pipe forwarded — the raw SQS batch — so the actor is the verified `cognito:username` claim inside the body's ID token, never the body's own assertion. By construction that token is expired: the timeout fires hours after it was minted. The relaxation is the DLQ drain's, taken through the same separately-named entry point (`verified_username_ignoring_expiry`) and safe for the same reason — this path **grants nothing**, it only addresses a message. An input EventBridge omitted (it caps an event at 256 KB) or a token that will not verify is a **logged no-op**, never a guessed inbox. Its wording is its own reason code, `share_timed_out`, rather than the generic failure sentence: a timeout is the one whole-request failure that can leave a recipient holding **part** of a dataset — the copy may have run and the create may not — so "try again" alone would be wrong advice.

> **Superseded in part by SPEC-201 (2026-08-30):** the token half only. The door recovers the sender
> from the message's `identity` block, so "by construction that token is expired" describes nothing —
> there is no token, the API verified the bearer at the edge, and the `*_ignoring_expiry` entry point
> this cited is deleted. Everything else here stands unchanged, including the degradation: an input
> EventBridge omitted, or a block that will not read, is still a **logged no-op and never a guessed
> inbox**, and the reason code is still `share_timed_out`. There are **four** such doors, not three —
> Arc A's file-ops plane added one.

**Sized from `SHARE_MAX_TRANSFER_BYTES`, NOT from the source cap — and the difference is a factor of `SHARE_MAX_RECIPIENTS`.** The manifest carries one item per (recipient, object) pair and every item is a full copy, so the Map moves the source **once per recipient**. Sized against the 1 TiB source cap alone, this number was short by 50×: 50 recipients × 1 TiB is 50 TiB, which needs 3.8 hours even at the conservative rate. That is the omission `SHARE_MAX_TRANSFER_BYTES` (3 TiB) closes. **And the rate it is divided by is a makespan, not an aggregate bandwidth** — a fourth review round's correction, and the same class of error a fourth time: `copy_batch` gives one whole object to one worker and `copy_one` part-copies serially, so a batch dominated by one large object runs at ONE stream while seven idle. The pessimistic denominator is `MAP_MAX_CONCURRENCY × rate` (500 MB/s), not `× COPY_CONCURRENCY ×` it (4 GB/s) — under which 16 TiB read as 4,400 s when the truth was 35,000. At 500 MB/s, 3 TiB is ~6,600 s, and with the finish Map (3,000 s) and the serial verbs (~720 s) the worst run is ~10,300 s inside **10,800 s (3 h)**. The margin is bought against the sender's silence, so a longer timeout is a slower failure signal rather than free safety; the cap moves before the timeout does. **A test computes it**, because the hard-coded floor that stood here first is exactly what let the mismatch survive two review rounds.

**The retention obligation inverts once a run can last hours.** Nothing new needed expiring: manifest, definition and Map Run export all sit under `table-share/`, which `expire-table-share-copy-plans` already covers. The risk was the opposite — the rule expiring a *live* run's manifest underneath it. `admin_results_retention_days` (30) clears the run ceiling by **240×**, computed by a test from both files, and **no rule and no rule id were added**.

## History

### 2026-08-30

- **Changed:** SPEC-201 replaced the timeout door's token recovery with the message's `identity` block, deleted the expiry-ignoring entry point, and counted four such doors.

### 2026-08-10

- **Settled:** SPEC-161.
