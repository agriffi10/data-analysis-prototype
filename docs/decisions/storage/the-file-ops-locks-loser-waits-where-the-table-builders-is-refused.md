---
type: Decision
title: "The file-ops lock's loser WAITS where the table-builder's is refused (SPEC-187)"
description: "The file-ops lock is per space, so its loser waits, stealing a stale lock itself, and refuses by notification at a give-up bound strictly below the machine's `TimeoutSeconds`; a cross-space operation takes two locks in digest-sorted order or neither. The **space root is refused** as an item; the collision unit is the derived destination **key**, and a protected destination is judged there as well as at the prefix, since an item's name can land in a locked folder, and every planned key is judged against the role's any-depth write Deny before the transfer, as the source keys are against its delete Deny; a **403 counts as occupied**; the deletion takes **confirmed plan keys** — a prefix listing orphans an uncopied object."
---

Both locks exist because delivery ordering is not execution ordering. They differ on what happens to
the loser, and the difference is the scope of the lock rather than a preference.

SPEC-157's lock is per **table**, and a contended refresh is a genuine conflict: two runs would
compute an identical definition from the same files, so refusing is the honest answer. This lock is
per **space** and covers all three operations — so deleting a folder in `alice/a/` and then copying
one in `alice/b/` is disjoint and entirely safe, and refusing it would produce a reliable
out-of-band refusal after the UI had already accepted the request.

So the loser **waits and retries**, with a bounded give-up that then refuses with a notification.
Three consequences that only hold together:

- **The waiter steals a stale lock itself**, on every re-acquire rather than only the first. That is
  what makes the give-up bound independent of the steal threshold.
- **The give-up bound is strictly LESS than the machine's `TimeoutSeconds`.** The naive chain is
  unsatisfiable and must not be re-derived: requiring give-up ≥ the steal threshold, with the
  threshold > the ceiling, forces give-up > the ceiling — and the waiter is a state *inside* the
  machine, so the ceiling would kill it before its refusal could fire, surfacing as a bare
  `TIMED_OUT` rather than the message the design promises.
- **Waiters are unordered, and that is accepted.** The Pipe starts executions `FIRE_AND_FORGET`, so N
  submissions against one space become N concurrent waiters polling one key with no queue discipline.
  Ordering would need a real queue; the browser's own busy gate already makes this rare from one
  session.

**A cross-space copy or move takes TWO locks, in digest-sorted order, or neither.** Keying only on
the source leaves the destination unserialized — A moves `alice/reports/` into `marketing/` while B
deletes `marketing/reports/`, different source digests, both run. Sorted order is what makes two
locks safe: unordered acquisition deadlocks when two requests cross in opposite directions. The verb
releases the first if it cannot claim the second, so a waiter never holds a lock across the `Wait`
and the give-up path has nothing left to free.

**One case can still strand a lock and is accepted rather than solved:** a fault inside the acquire
verb between the two claims returns nothing, so no tag reaches the state and the first lock is held
with nobody able to name it. The staleness steal is the recovery, and it is the same universal
recovery the top-level timeout needs — splitting the claims into two states would double the loop
and reintroduce the partial hold the design avoids.

## History

### 2026-08-17

- **Settled:** SPEC-187.
