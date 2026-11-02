---
type: Decision
title: "A failed status poll ends the Query tab's run, and the poll is disabled rather than left to answer (SPEC-233)"
description: "A failed status poll ends the Query tab's run after one retry and shows the reason, sending no stop; the status bar takes its verdict from the batch, not from the last status. **A poll's stop is `enabled` resolving `false`**, never only an interval returning `false`: a failed query is stale whatever its `staleTime`, so a reconnect refetches it."
---

The Query tab followed its statement by polling status and read only the poll's data, so a status
request that failed left the tab on "Running…" for the hook's five-minute ceiling and then in
flight for good, with no message. The Data Explorer, on the same hook, already routed the error to
its banner. It matters more because SPEC-232 makes the status route answer 404 for an execution
whose results location is not under the caller's own prefix: a prefix moved under a held id, or a
workgroup that enforces its own result location, would spin every open tab in silence.

**A failed poll is final for the tab, after one retry.** The run settles as a failure would:
`done`, with `toUserText(error)` as the reason in the existing banner, and a batch stops at that
statement. The retry count is `apiRetryPolicy('athena.status')`, set on the hook rather than
inherited from the client default, so it is stated where it can be tested. It is the same value
production already had. *No retry* was rejected because, once a failure ends the run, one dropped
request would cost a re-run and a second bill. *Retrying only codes that look transient* was
rejected as a local retry decision, which is exactly what `apiRetryPolicy` exists to prevent; also
retrying a `NotFound` costs one idempotent GET and about a second. History keeps no verdict, and
reads "Unknown", because the execution's real state is unknown. Nothing is sent to stop it: the
same ownership proof refuses stop, a network failure would fail it too, and the query may have
succeeded.

**The trap: ending the interval is not a stop.** A failed TanStack query is stale whatever its
`staleTime`, because the error reducer marks it invalidated, and `refetchOnReconnect` defaults on.
So a poll whose interval returns `false` on error is still refetched when the network comes back,
and that answer lands on a run that has already settled. Only `enabled` resolving `false` gates
the interval, a reconnect and a remount at once. The hook's opt-in `stopOnError` does that, using
v5's function form of `enabled`. That form turns false only once the retries are spent, because
the query's status stays pending or success while a retry is in flight. Measured by planting the
interval-only stop: the workspace's reconnect test went from 2 status requests to 4, and nothing
else noticed.

**The Explorer does not pass it,** so its behaviour is unchanged: it keeps polling after an error,
and a later successful poll clears its banner. Whether it should stop too is that screen's
question. Since SPEC-234 that holds only until the watch's ceiling: a failed read after it ends the
watch for every caller.

**The status bar takes its verdict from the batch, not from the last status.** A statement whose
status could not be read has no terminal state. A bar that read only the status went blank and
withheld Save results from an earlier statement's rows, which were complete and already billed.
A later statement that failed to *start* left the earlier success as the latest status, so the bar
read "Succeeded" under a "Statement 2 of 2 failed" banner, a defect that predates this spec.
`QueryStatusBar`'s `batchFailed` makes a run that ended on a failure read "Failed" whatever the
displayed status says. The resubmit gap is unchanged: no status and no failure still means no
verdict, and so no lone button.

**The test client carries `retryDelay: 0`.** A hook's own positive `retry` fires under the harness,
and at once. TanStack's one-second backoff is exactly `waitFor`'s window, so without it a retried
failure times out in a way that looks like a flake. No other query hook sets a positive `retry`,
so no other test moved.

**Not done here, and done in SPEC-234:** a query that outlived the five-minute ceiling while every
poll succeeded still left the tab in flight. It now settles at a 30-minute ceiling with a sentence
that says where its results go ([the entry below](a-long-query-settles-at-the-ceiling-judged-on-a-read-after-it-and-says.md)).

## History

### 2026-09-13

- **Settled:** SPEC-233.
