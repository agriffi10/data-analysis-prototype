---
type: Decision
title: "Two budgets, and both were wrong before they were computed (SPEC-189)"
description: "File operations' joint budget adds the lock give-up to every serial timeout and the copy makespan against the 10,800 s ceiling, which is why the cap is 2 TiB; the deletable list, per-item counts and deletion records travel by pointer."
---

**The joint budget:** the lock give-up, two guard sweeps, every serial verb timeout, the copy's
makespan and the deletion, added. At 3 TiB it came to ~12,700 s against a 10,800 s ceiling — and the
earlier version carried **no give-up term at all**, though a waiter can spend 2,080 s. Waiting for a
busy space and *then* copying is one execution, not two scenarios. **The cap moved to 2 TiB, not the
ceiling**, because the ceiling also sets `STALE_LOCK_SECONDS` and a longer stale window on a shared
space blocks everyone who works in it, not only the person whose run wedged.

**The state budget, which no earlier spec owned:** the deletable list, the per-item counts and the
per-item deletion records measure **287,532 bytes** at the selection cap against 262,144 (307,083
with conflict samples). All three travel by pointer, on this plane's own recorded rule that
everything unbounded on the state does. Where it would have broken is the worst place available:
`States.DataLimitExceeded` on the collector's result lands **after the copy**, and on delete-source's
**after the deletion**, and that error escapes every `Catch` here (`States.ALL` does not match it and
none names it) — so the user would be told nothing at all about an operation that had already moved
their data.

## History

### 2026-08-17

- **Settled:** SPEC-189.
