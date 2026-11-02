---
type: Decision
title: "One producer, after the release, reached from BOTH of ReleaseLock's edges (SPEC-191)"
description: "**The outcome producer sits after `ReleaseLock`, and `ReleaseLock`'s `Catch` moves with its `Next`**: pointed at the terminal, that catch skips the producer, so a release whose `Retry` a throttle exhausts completes the operation and tells the user nothing. **Where a plane has an end producer, it is the ONE voice for every per-item outcome** — not each verb. Table-share has none, and its verbs each tell the outcome only they know."
---

The plane's outcome producer is the last state before `Succeeded` and it sits **after**
`ReleaseLock` — before it, the space would be held for as long as the messages take to write. The
half that is easy to miss is that `ReleaseLock`'s **`Catch`** had to move with its `Next`. That
catch exists so a failed release cannot fail a request that did its work; pointed at the terminal,
it skips the producer, and a release whose `Retry` one throttle exhausts then **completes the
operation and tells the user nothing**. The browser's per-space gate, which settles on a
notification carrying the `requestId`, would hold that space until the machine's ceiling — the exact
wedge the always-present `requestId` exists to prevent, arriving through the one path nobody looked
at. Both edges reach the producer now, and a test asserts it.

**It is also the one Task on this plane whose catch reaches a terminal rather than a release**, and
that is not an oversight to be tidied. The lock is free by the time it runs, and a release is an
**overwrite**, not a compare-and-set on the holder — so a second one would clobber whichever
execution had since acquired that space. The graph walk's not-under-the-lock set names it with the
reason, beside validate-authorize and the failure notifier.

It cannot fail the run: `ResultPath: null` on the state *and* on the catch, and **no**
`@notifies_on_failure` — by the time it runs a `move` has already deleted its sources, so a raise
would report a completed operation as a failed one. And it reads the **state and nothing else**: a
verb that loaded the plan would join the set whose smallest memory sizes `FILE_OPS_MAX_OBJECTS`,
shrinking a cap that has nothing to do with notifying. A test derives that set from the source.

**Where a plane has an end producer, it is the one voice for every per-item outcome**, not each verb. Table-share has none, and its verbs each tell the outcome only they know.

## History

### 2026-08-17

- **Settled:** SPEC-191.
