---
type: Decision
title: "The retrieval budget has deliberate headroom, and the ceiling moved for the whole plane"
description: "The poll budget is seven hours against a five-hour tier, so the one top-level `TimeoutSeconds` is 43,200 for both arms; a test keeps the archive arm's worst legal run more than 4× clear of it."
---

`RESTORE_MAX_POLLS × RESTORE_POLL_SECONDS` is **seven hours** against a tier whose documented worst
case is five. Every other timeout in this repo can be tight, because failing means re-running
something free. Here the cost is asymmetric in a way most timeouts are not: **giving up on a
retrieval that was going to finish makes the user pay for a second billed retrieval**, while waiting
two more hours costs one Lambda invocation every five minutes. AWS documents 3–5 hours as typical
rather than contractual, which is exactly the class of premise this project has been burned by
before.

That budget forced `TimeoutSeconds` from 10,800 to **43,200**, and the raise is not about data
volume: the archive arm's long pole is a copy, and the restore arm's is a *wait*. `TimeoutSeconds` is
a top-level ASL field on one machine serving two arms, so **the archive arm's backstop rose with
it** — a wedged archive is now reported after twelve hours rather than three. Accepted: it is a
backstop, not an expectation, and the alternative was killing healthy restores. A test asserts the
archive arm's own worst legal run still clears the ceiling by more than 4×, so the ceiling drifting
until it stops being a backstop for the arm that does not wait would fail the build.

## History

### 2026-08-12

- **Settled:** entered the register.
