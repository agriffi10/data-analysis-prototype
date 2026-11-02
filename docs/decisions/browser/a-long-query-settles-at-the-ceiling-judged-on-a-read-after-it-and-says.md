---
type: Decision
title: "A long query settles at the ceiling, judged on a read after it, and says where its results go (SPEC-234)"
description: "The status watch lasts 30 minutes, then the first read after the ceiling settles the run with a \"Still running\" warning saying where the results go; nothing cancels the query, and the verdict is never cached. **A watch's ceiling is a verdict on a read after it, never on the clock**: the poll pauses while the page is hidden."
---

The status poll stopped five minutes after it started, and nothing settled a run whose every poll
had succeeded. A query still running at five minutes left the Query tab on "Running…" for good, Stop
did nothing visible because it waits for the poll to see `CANCELLED`, and the Explorer's "Running…"
never ended.

**The watch lasts 30 minutes, and then the run settles and says so** (Andrew's ruling). Thirty is
this account's Athena DML timeout, so an ordinary query succeeds or fails first, and the verdict is
for long DDL, a query that waited in Athena's queue, or a raised quota. At five, every query slower
than five minutes was unviewable in either screen, since a re-run meets the same ceiling. The
banner is a warning titled "Still running", from the `QueryStillRunning` rule in
`lib/errorMessages.ts`. It names the execution id and `system_settings/athenaresults`, because
nothing reattaches to an execution and that CSV is the one way to read the results without paying
for the query again. Stop goes with the run, nothing is sent to stop the execution, and History
reads "Unknown". *Watching to the end* and *cancelling at the ceiling* were rejected.

**The trap: the ceiling is a verdict on a read, never on the clock.** TanStack skips interval
fetches while the page is hidden, so a verdict from the clock alone settles a query that finished
in the background without looking at it again. A timer marks the ceiling, and the first read after
the mark decides. A failed read after it ends the watch too, whether or not the caller passed
`stopOnError`, so no screen polls a failing route without bound, which was the bound the old ceiling
gave the Explorer. Measured by planting a clock-only verdict: the hidden-page test and the
terminal-after-the-ceiling test went red.

**The verdict belongs to the watch, not to the execution.** It is hook state, reset when the id or
the watcher changes, and never an error in the shared cache. The watcher matters because two
Explorer tabs with one description share one cached execution, so the id alone cannot tell them
apart: the Explorer passes its tab id as the watch key, and a key must be stable, because the reset
runs during render. A cached verdict would stick: an Explorer tab
returning to a description would repeat "still running" without looking, even after the query had
finished. For the same reason the Explorer does not remember the verdict as a failed statement, and
Back onto it starts a new watch on the cached execution, with no second bill. The hook reads
`dataUpdatedAt` only once the mark is set. Read earlier, TanStack tracks it and every poll
re-renders the host; never read, the deciding `RUNNING` read changes nothing the hook tracks.

**A banner with nothing earlier to show leaves the Explorer's body empty.** It said "Running…" under
every such banner, a failed first apply's included, and would have said "No rows returned." once it
stopped loading. In the Explorer, Save query and Create view stay available for the statement,
because Athena accepted it.

**Tests drive fake timers through Testing Library with a `jest` stand-in** (`test/fakeTimers.ts`).
Without one, a full-page render hangs on its first click. The ceiling's mark is crossed in an `act`
of its own, since React applies the update only as that `act` exits. A fake-clock window that ends
exactly on a poll tick can leave the timer that tick schedules for the next window, so the counted
windows end between ticks.

**Not done:** a live check. DML times out at 30 minutes here, so a statement that outlives the
ceiling on demand is long DDL nobody has on hand (`docs/testing/owed.md`).

## History

### 2026-09-14

- **Settled:** SPEC-234.
