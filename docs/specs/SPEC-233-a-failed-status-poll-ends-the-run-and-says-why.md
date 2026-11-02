---
type: Spec
id: SPEC-233
title: "A Failed Status Poll Ends the Query Tab's Run, and Says Why"
description: "Makes a failed status poll end a Query tab's run after one retry and show the error code's wording in the tab's error banner, instead of spinning on Running for five minutes with no message."
spec_status: Completed
depends_on: [SPEC-078, SPEC-106]
---

## Overview

A Query workspace tab follows its running statement by polling the statement's status. When that
poll fails, the tab says nothing. It keeps showing "Running…" and the elapsed timer while the poll
retries silently for five minutes. Then the poll gives up and the tab stays in flight for good, with
no message and no verdict. The only way out is to close the tab. The Data Explorer, which polls
through the same hook, does not have this problem: it puts the failure in its error banner.

This matters more once SPEC-232 lands. That spec makes the status route answer 404 `NotFound` for
any execution whose recorded results location is not under the caller's own results prefix. A
user's own execution can then be refused in two ways that the user cannot see coming: the prefix
moves under an id the tab still holds (SPEC-220 moved it once), or the Athena workgroup starts
enforcing its own result location (the IdC transition, `docs/transition_plan.md`, may do this). In
either case every running tab would spin in silence.

This spec makes a failed status poll end the tab's run, after one retry, and puts the error code's
wording from `lib/errorMessages.ts` in the tab's existing error banner.

### What was checked, and how

Read from the code at `a5ef2b9c`.

- **The defect.** `TabExecutionPoller` reads `execution.data` and never `execution.error`. With no
  data, `useQueryExecution`'s `refetchInterval` returns `POLL_INTERVAL_MS` (1.5 s) until
  `MAX_POLL_DURATION_MS` (5 min) has passed, and then `false`. The run's `done` flag is set only by
  `handleFinalize`, which needs a terminal status. So nothing ever settles the run.
- **The retry today.** `useQueryExecution` sets no `retry`, so it inherits `retry: 1` from
  `lib/queryClient.ts`, and TanStack's default delay puts the retry 1 s after the first failure.
  `apiRequest` retries nothing except a 401, once, after a forced token refresh. The status route is
  declared `idempotent: true` in the generated contract, so `apiRetryPolicy('athena.status')` is 1.
  The test harness's client sets `retry: false`, so today no test can observe the retry.
- **When TanStack pauses a retry** (query-core 5.102.8, `retryer.ts` `canContinue`): while the page is
  unfocused, and while the browser reports itself offline. A retry therefore spends itself only on a
  failure the browser can actually see, such as a 5xx, a refused request, or a fetch that failed
  while the browser still reported being online.
- **Reconnect refetches an errored query.** `refetchOnReconnect` defaults to `true`. A query in
  error is stale whatever its `staleTime`, because the error reducer marks it invalidated
  (`query.ts`), so an `online` event refetches it unless `enabled` resolves `false` for it
  (`queryObserver.ts` `shouldFetchOn` and `isStale`). The poll interval is gated the same way
  (`#updateRefetchInterval`). TanStack v5 accepts `enabled` as a function of the query.
- **The error banner already renders a settled failure.** `QueryWorkspace` builds the banner text
  from `run.failure` (`batchFailureMessage`), under the title "Query failed.". The mobile results
  view gets the same text for a run it started. A run that failed to *start* already reaches the
  banner with `toUserText(error)` wording.
- **History.** `QueryHistoryRow` shows an entry with no terminal status as "Unknown".

### The decisions, made while authoring

- **One retry, for every failure code, then the run ends.** The count is
  `apiRetryPolicy('athena.status')`, set on the hook itself instead of inherited from the client
  default. That function is the one sanctioned source of a retry count for an API-backed hook. The
  value does not change in production, but the hook now states it, so a test can see it.
  - *No retry was rejected.* Until now a transient failure cost nothing, because the poll simply
    went on. Once a failure ends the run, a single dropped request would end it too, and the user's
    only recourse is to run the query again and pay for it twice.
  - *Retrying only codes that look transient was rejected.* That means a code list kept in the hook,
    which is exactly the local retry decision `apiRetryPolicy` exists to prevent. The cost of also
    retrying a `NotFound` or `AccessDenied` is one idempotent GET and about a second before the
    sentence appears.
  - *More than one retry was rejected* for the same reason as the code list: it would be a local
    count that overrides the contract's.
- **The stop is an opt-in on the shared hook, and it disables the query instead of only ending
  the interval.** `useQueryExecution(id, {stopOnError: true})` resolves `enabled` to `false` once
  the query has failed. Ending only the interval would leave the reconnect refetch in place. If the
  network came back after a failure, that refetch could land a later status on a run that has
  already settled on the failure. The Data Explorer does not pass the option, so its behaviour is
  unchanged. It keeps polling after a surfaced error, and a later successful poll clears its banner.
  Whether the Explorer should stop too is a question about that screen, and this spec does not
  change it.
- **The wording is the error code's own, and the banner is the existing one.** The failure's reason
  is `toUserText(error)`, the same mapping the Explorer's `ErrorBanner` uses. The banner keeps its
  title, "Query failed.", which a failed start already carries. A batch keeps its existing prefix
  and suffix ("Statement 2 of 3 failed. … Statement 3 did not run."). No new sentence is authored.
- **History is left alone.** The execution's real state is unknown, and an entry with no verdict
  already reads "Unknown", which is the truth.
- **Nothing is sent to stop the execution.** A refused status is refused by the same ownership
  proof that guards stop, a network failure would fail the stop too, and the query may well have
  succeeded. The execution runs on server-side, exactly as it does when a tab is closed mid-run.

## Scope

### In Scope

- `useQueryExecution` takes its retry count from `apiRetryPolicy('athena.status')`, and takes an
  opt-in `stopOnError` that disables the query once it has failed.
- `TabExecutionPoller` reads the poll's error and reports it once per execution. `useTabRuns`
  settles the run on it, with the error code's wording as the failure reason.
- `QueryStatusBar` takes a `batchFailed` prop, which `QueryResultsRegion` and `QueryResultsMobile`
  pass from the run's `failure` (FR-005).
- Integration tests on `QueryWorkspace`, and hook tests on `useQueryExecution`.
- The existing hook test "surfaces a service failure as an error state" is updated. The hook's own
  retry and TanStack's 1 s first-retry delay would otherwise outlast `waitFor`'s 1 s window. The
  shared test client (`createTestQueryClient`) gains `retryDelay: 0` beside its `retry: false`.
  The hook sets `retry` but not `retryDelay`, so only the hook's own retry can fire, and it fires
  at once. No other query hook sets a positive `retry`, so no other test changes.

### Out of Scope

- **The Data Explorer's polling after an error.** It already surfaces the error. Whether it should
  also stop polling is a separate change.
- **A query that outlives the five-minute poll ceiling while every poll succeeds.** The tab also
  stays in flight for good in that case, but no request fails. Fixing it means deciding how long
  the browser waits for a long query, which is a separate product question.
- **A new sentence or banner title for "the status could not be read".** Wording comes from the
  existing rules in `lib/errorMessages.ts`.
- **Stopping the execution, or recording a verdict in history,** on a poll failure. See the
  decisions above.
- **A run whose FIRST statement fails to start, over an earlier run's results.** No run is
  installed, so the earlier run's bar ("Succeeded") and rows stay on screen under the "Query
  failed." banner. FR-005's rule holds, because the bar describes the run it shows. Whether a
  failed resubmit should clear the previous results is a separate question.
- **`runStatementToCompletion`** (View DDL, Drop, Create view). It already returns a failed status
  to its caller, which shows it as a toast.
- **Any API, contract or server change.**

---

## Functional Requirements

### FR-001: A failed status poll ends the tab's run

#### Description:

When the status of a tab's current execution cannot be read, after the one retry in FR-003, the
tab's run settles at once. It is no longer in flight, and a batch stops at that statement: the
statements after it do not start. The execution's history entry keeps no verdict, and nothing is
sent to stop the execution.

#### Acceptance Criteria:

- [ ] A single-statement run whose status request fails with `NotFound` on both attempts leaves the
  tab out of flight. "Running…" is gone, and pressing Run again starts a new execution (`runQuery`
  is called a second time).
- [ ] In a three-statement script whose second statement's status request fails on both attempts,
  `runQuery` is called exactly twice.
- [ ] `updateQueryHistoryEntry` is never called with the failed execution's id.
- [ ] `stopQuery` is not called.
- [ ] The two criteria above, and FR-002's raw-message criterion, are asserted in the same test,
  after the banner is visible. Each of them is also true of today's code, where nothing settles,
  so on its own it proves nothing.

### FR-002: The tab says why, in the error code's wording

#### Description:

The tab's error banner shows the failure's reason as `toUserText(error)`, the wording
`lib/errorMessages.ts` maps from the error code. The failure's raw `message` is never rendered. In
a batch, the reason sits inside the existing "Statement N of M failed." sentence. The mobile
results view shows the same text for a run it started.

#### Acceptance Criteria:

- [ ] A `NotFound` status failure shows "That item no longer exists. Refresh and try again." in the
  banner.
- [ ] A `NetworkUnavailable` status failure shows "Can’t reach the server. Check your connection
  and try again." in the banner.
- [ ] The failure's raw `message` text does not appear anywhere on screen.
- [ ] In the three-statement case of FR-001, the banner reads "Statement 2 of 3 failed. That item
  no longer exists. Refresh and try again. Statement 3 did not run."
- [ ] Below the `tablet` breakpoint, a run started from the mobile results view whose status
  request fails shows the same sentence in that view.

### FR-003: A failed status request gets one retry before it ends the run

#### Description:

`useQueryExecution` sets `retry: apiRetryPolicy('athena.status')`, which is one, instead of
inheriting the client default. The retry applies to every failure code. A retry that succeeds
leaves the run exactly as if nothing had failed.

#### Acceptance Criteria:

- [ ] Under the test client, whose default is `retry: false`, a status request that fails once and
  then succeeds lets the run reach its verdict: "Succeeded" is shown and no banner appears.
- [ ] A status request that fails on both attempts settles the run after exactly two status requests
  for that execution.

### FR-004: Once a run has settled on a failure, the poll asks nothing more

#### Description:

The tab's poller passes `stopOnError: true`, so its status query is disabled once it has failed.
Neither the poll interval nor a reconnect asks about that execution again, and no later answer can
overwrite the settled failure. Without the option, `useQueryExecution` behaves as it does today.

#### Acceptance Criteria:

- [ ] With `stopOnError: true`, once the hook reports an error, advancing the clock by at least
  twice `POLL_INTERVAL_MS` makes no further status request.
- [ ] With `stopOnError: true`, once the hook reports an error, going offline and back online
  makes no further status request.
- [ ] Without the option, once the hook reports an error (both attempts spent), another status
  request follows within `POLL_INTERVAL_MS` plus a margin. The count starts at the error, not at
  the first request, because the retry alone would supply a second request.

### FR-005: The status bar gives the batch's verdict, not the last status

#### Description:

*Added during the build, from the execution-frame diff review.* A statement whose status could not
be read has no terminal status, and the status bar used to draw its verdict only from a terminal
status. So the bar went blank, and Save results disappeared for an earlier statement's complete,
already-billed rows. Once the banner was dismissed, nothing on screen said the batch had failed.
The same root showed "Succeeded" under a "Statement 2 of 2 failed" banner when a later statement
failed to *start*: the earlier statement's success was still the latest status. The bar now takes
the verdict from the batch. A run that ended on a failure reads "Failed", whatever the displayed
status says. The mobile strip follows the same rule.

#### Acceptance Criteria:

- [ ] Under "Run Multiple Queries", when statement 1 returns rows and statement 2's status request
  fails, the bar reads "Failed", and Save results writes statement 1's result
  (`copyObject` from `q-1`'s output location).
- [ ] When a script's second statement fails to start, the bar reads "Failed" and not "Succeeded".
- [ ] Below `tablet`, a run whose status request fails shows "Failed" on the mobile strip.
- [ ] A run that ends without a failure keeps today's verdicts. The existing status-bar tests pass
  unchanged, including the resubmit gap, where no status has arrived and there is no failure.
  After a run that *failed*, the gap keeps showing that run's "Failed", which the banner is still
  showing too, until the new run is installed.

---

## API / Interface Contract

```ts
// apps/portal/src/features/catalog/useQueryExecution.ts
export function useQueryExecution(
  queryExecutionId: string | null,
  options?: {
    /** Disable the query once it has failed, so no interval, reconnect or remount asks again. */
    stopOnError?: boolean;
  }
): UseQueryResult<QueryStatus>;

// apps/portal/src/features/query/TabExecutionPoller.tsx — one new prop, called at most once per
// execution id, and never for an id that already reached a terminal status.
onPollFailure: (tabId: string, executionId: string, error: unknown) => void;
```

`useTabRuns` settles the run on `onPollFailure` the way `handleFinalize`'s `FAILED` branch patches
it, and without that function's history write. The handler applies only while the execution is
still the tab's current, unfinished one, and sets `done: true, failure: {statementIndex:
cur.currentIndex, reason: toUserText(error)}`.

## File & Folder Structure

```
apps/portal/src/features/catalog/useQueryExecution.ts        # retry + stopOnError
apps/portal/src/features/catalog/queryExecutionHooks.test.ts # FR-003 count, FR-004 interval + control
apps/portal/src/features/query/TabExecutionPoller.tsx        # reads the error, reports it once
apps/portal/src/features/query/useTabRuns.tsx                # settles the run
apps/portal/src/features/query/QueryStatusBar.tsx            # batchFailed owns the verdict (FR-005)
apps/portal/src/features/query/QueryResultsRegion.tsx        # passes the run's failure to the bar
apps/portal/src/features/query/QueryResultsMobile.tsx        # the same, on the mobile strip
apps/portal/src/features/query/QueryWorkspace.test.tsx       # FR-001–FR-003, FR-004 reconnect
apps/portal/src/features/query/queryWorkspaceMobile.test.tsx # FR-002 mobile criterion
apps/portal/src/test/renderWithProviders.tsx                 # retryDelay: 0 on the test client
apps/portal/info/best-practices/react/react.md               # §21: a hook's own retry is visible
```

## Implementation Phases

### Phase 1: The hook, the poller and the run

The hook's retry and `stopOnError` go in first, with their hook tests. Then `TabExecutionPoller`
and `useTabRuns`, with the workspace and mobile tests. It is one PR: the change is small, and none
of it is inert without the rest.
