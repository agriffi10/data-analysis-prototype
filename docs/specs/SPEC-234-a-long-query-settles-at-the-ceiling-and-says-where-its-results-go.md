---
type: Spec
id: SPEC-234
title: "A Long Query Settles at the Ceiling, and Says Where Its Results Go"
description: "Raises the Query and Data Explorer polling ceiling to 30 minutes and ends a longer watch visibly, saying the query still runs in Athena and where its results will be saved, with Help guides updated."
spec_status: Completed
depends_on: [SPEC-078, SPEC-106, SPEC-233]
---

## Overview

A Query workspace tab follows its running statement by polling the statement's status, and the
poll stops five minutes after it starts. When a statement is still running at that point, and
every poll has succeeded, nothing settles the run. The tab keeps showing "Running…" and a ticking
elapsed timer for good, even after the query finishes in Athena. Stop does nothing visible either,
because it relies on the poll seeing `CANCELLED`, and the poll has stopped. The only way out is to
close the tab. The Data Explorer, which polls through the same hook, has the same fault: its
"Running…" never ends.

Athena lets a query run much longer than five minutes, so an ordinary long query reaches this.
This spec raises the ceiling to 30 minutes, which is Athena's DML timeout in this account, and
makes a watch that outlives it end in a visible way. The run settles, and a sentence says that the
query is still running in Athena, that its results will not appear here, and where they will be
saved when it finishes. The Data Explorer behaves the same way. The Help guides for both screens
describe the limit.

### What was checked, and how

Read from the code at `090e595f`, unless a line says it was read live.

- **The defect.** `useQueryExecution`'s `refetchInterval` returns `false` once
  `MAX_POLL_DURATION_MS` (five minutes) has passed since the id was set. `TabExecutionPoller`
  settles a run only on a terminal status (`onFinalize`) or a failed poll (`onPollFailure`).
  `handleStop` in `useTabRuns` calls `stopQuery` and leaves the rest to the poller. The Explorer's
  `isPending` stays true while the last status is non-terminal.
- **Athena's own limits, read live from Service Quotas.** The DML query timeout is 30 minutes and
  adjustable. The DDL query timeout is 600 minutes and not adjustable. Athena therefore brings every
  execution to a terminal state on its own. With a 30-minute ceiling, an ordinary query succeeds or
  fails before the browser stops watching it. The sentence is for long DDL, such as
  `MSCK REPAIR TABLE`, for a query that waited in Athena's queue, and for the case where the quota
  is raised.
- **The workgroup sets no timeout.** `infra/modules/analytics/athena.tf` sets only
  `bytes_scanned_cutoff_per_query` (10 GiB by default), so the quota is the only bound.
- **TanStack pauses the poll while the page is hidden** (query-core 5.102.8, `queryObserver.js`).
  An interval tick fetches only when `refetchIntervalInBackground` is set or the page is focused,
  and the hook sets neither. A verdict taken from the clock alone would settle a query that finished
  while the browser tab was in the background, without ever having looked at it again.
- **Nothing reattaches to an execution.** In History, Open copies the SQL into the editor and
  Re-run starts a new execution. The comment on `MAX_POLL_DURATION_MS` says "the UI can re-attach to
  the execution id later", and that is not true. After the browser stops watching, the query's
  results can be seen only by running it again, which bills it again, or by opening its CSV.
- **Where the CSV lands.** The API starts every query with `output_location(verified username)`,
  which is `system_settings/athenaresults/` in the caller's own space (`cpcommon.results`,
  `app_managed.athena_results_prefix`). That holds for the Explorer too, since it starts its queries
  through the same route. Athena names the file after the execution id. The Files guide already
  describes the folder as "where your query results are kept".
- **The Explorer shows "Running…" under a banner when it has no earlier rows.**
  `ExplorationResultsRegion` computes `loading` as `isPending || !shownExecutionId ||
  results.isPending`, and a failure sets `shownExecutionId` to the last good execution, which is
  null on a tab's first apply. So its status line reads "Running…" under the error banner. A failed
  first apply shows this today, and a first apply that outlives the ceiling would show it too.
- **The Explorer's save refusal is worded for a failure.** A banner makes `failed` true, and
  `FAILED_NOT_SAVEABLE` reads "This query didn’t run, so there’s nothing to save. Fix it and try
  again." Neither half of that is true of a query that is still running. Create view takes the
  same refusal (`createViewRefusal={saveRefusal ?? …}`).
- **The Explorer remembers any error as a failed statement.** `DataExplorerWorkspace` calls
  `noteFailure(sql)` whenever `exploration.error` is set. Back or Forward onto that description
  is then held by `useExplorationQuery`, and the screen reads "This set of filters failed last time
  it ran. Nothing has been run."
- **Under a banner with no earlier result, the Explorer's body falls through to "No rows
  returned."** once it stops loading (`body()` in `ExplorationResultsRegion`). A results error
  already returns nothing there, because the banner has said it.
- **Today's ceiling also bounds a poll that keeps failing.** The interval returns `false` at five
  minutes whether or not the requests are failing. The Explorer does not pass `stopOnError`, so
  that is the only thing that stops it polling a failing route.
- **History.** `QueryHistoryRow` shows an entry with no terminal status as "Unknown".

### The decisions

Andrew made the first five, and the rest were settled while authoring.

- **The ceiling is 30 minutes, and the cadence stays at 1.5 seconds.** This matches the DML
  timeout, so the sentence is rare rather than the ordinary case, and no ordinary query is left
  unviewable. The rejected five-minute ceiling would leave every query slower than five minutes
  unviewable in both screens, because a re-run starts a new execution that meets the same ceiling.
  The cost is at most about 1,200 idempotent status calls for one long query.
- **At the ceiling, the run settles and says so.** *Watching until Athena's terminal state* was
  rejected in favour of a bound on how long the browser watches. *Cancelling at the ceiling* was
  rejected because it would stop a legitimate long query from ever finishing, while still billing
  what it had scanned.
- **Stop goes with the run.** Once the run settles, nothing is in flight, so the tab offers Run
  instead of Stop, and the portal cannot cancel that execution any more. Nothing is sent to stop
  it at the ceiling. History keeps no verdict and reads "Unknown", which is the truth.
- **The sentence says where the results go, and it names the execution id.** The CSV in
  `system_settings/athenaresults` is the only place the results can be read without paying for the
  query again, and the id is how the user finds the file.
- **The Explorer gets the same ceiling and the same sentence.** The change is in the shared hook,
  and its screen has the same fault.
- **The ceiling belongs to the watch, not to the execution.** The hook keeps its verdict in its own
  state, and a new watch of the same id looks again. A new watch starts when the hook remounts, or
  when the id changes away and back. The verdict is not written into the shared query cache as an
  error, for three reasons.
  - A cached verdict would stick. An Explorer tab that returns to a description it has already run
    reuses that execution's id, so it would repeat "still running" without looking, even after the
    query has finished.
  - The verdict is not a failed request. On the error channel, the hook's retry would fire for it,
    and `stopOnError` would be deciding something it was not written for.
  - The Query tab has to tell it apart from a failure anyway, because the banner title and the
    status bar's verdict are different.
- **The verdict is taken from a read after the ceiling, and never from the clock alone.** A timer
  marks the ceiling, and the first read after the mark decides, whether it answers or fails. A
  terminal status is delivered as usual. A `QUEUED` or `RUNNING` status ends the watch with the
  verdict. A failed read, once its retry is spent, ends the watch with that error, so no screen
  polls a failing route without bound, as today's ceiling also ensures. A tab hidden past the
  ceiling therefore decides on its first poll after it is shown again.
- **The verdict is not a failure the Explorer remembers.** Remembering it would suspend the
  description on Back or Forward with a sentence that says it failed. Going back to it instead
  starts a new watch, which looks again.
- **The stop is `enabled` resolving `false`.** The browser Fences require this, since a query
  that is only stopped by its interval is still refetched on a reconnect.
- **The banner is a warning, not the danger banner, and its title comes from the rule.** Nothing
  failed. The Query tab's "Query failed." title, and the bar's "Failed", would each be false here.
  The title and variant follow whichever message the banner is showing, so a later failure keeps
  "Query failed." and the danger variant.
- **The status bar's verdict reads "Still running", with a neutral dot and no timer.** It is written
  in the bar beside "Succeeded", "Failed" and "Cancelled", because it is a state label and not an
  error sentence. A settled run needs a verdict on screen for Save results to sit beside
  (SPEC-233 FR-005), so a blank bar is not an option.
- **In the Explorer, Save query and Create view stay available for a statement that outlived the
  ceiling.** The refusal exists because a statement Athena rejected would not open where the save
  promises it opens. A statement that is still running has no such problem, and a refusal reason
  written for a failure would be false here.
- **Under any banner with no earlier result, the Explorer's body shows nothing, and nothing says
  "Running…".** The banner has said what happened, which is the rule the body already follows for
  a results error. This covers a failed first apply too. It is the same code, and fixing it only
  for the ceiling would take an extra branch to keep a known defect.

## Scope

### In Scope

- `MAX_POLL_DURATION_MS` becomes 30 minutes, and its comment stops claiming a reattach.
- `useQueryExecution` ends the watch at the ceiling, as decided above, and returns
  `{status, error, stillRunning}` in place of the raw TanStack result. Spreading the TanStack result
  would read every tracked property, and the Explorer would then re-render on every poll.
- `lib/errorMessages.ts` gains one rule, `QueryStillRunning`, with a title and a sentence built
  from the ceiling in minutes and the execution id. `params` widens to carry the id.
- `TabExecutionPoller` reports the verdict once per execution through `onStillRunning`, and
  `useTabRuns` settles the run on it. `QueryWorkspace` builds the banner's message from it, and
  passes `QueryResultsRegion` and `QueryResultsMobile` a title and variant that follow whichever
  message is shown.
- `QueryStatusBar` takes a `stillRunning` prop, which owns the verdict the way `batchFailed` does.
  `QueryResultsMobile` takes it as a prop for its strip, as it takes `batchFailed`.
- `useExploration` routes the verdict to its `error` and stops reporting `isPending`.
  `DataExplorerWorkspace` does not remember the verdict as a failed statement.
  `ExplorationResultsRegion` shows it as a warning, shows nothing and no "Running…" under any
  banner that has no earlier result, and does not refuse Save query or Create view for it.
- `CLIENT_MINTED` in `lib/apiContract.guard.test.ts` gains `QueryStillRunning`, which puts the new
  code under the guard that every code has a rule of its own.
- The Query and Data Explorer Help guides (FR-004).
- Hook tests on `useQueryExecution`, with the five existing ones ported to the new shape rather
  than dropped; integration tests on `QueryWorkspace` and on `DataExplorerWorkspace`; and a Help
  test.

### Out of Scope

- **Reattaching to an execution** from History or anywhere else, and showing a finished query's
  results without running it again. The CSV in Files is that path.
- **A verdict in History** for a watch that ended. It stays "Unknown".
- **Sending stop at the ceiling**, and any Stop affordance after it.
- **A slower cadence as a run ages.** Andrew kept 1.5 seconds throughout.
- **A link from the banner to the Files folder.**
- **`runStatementToCompletion`** (View DDL, Drop, Create view). It has its own bound of 90 polls,
  400 ms apart, and reports its outcome as a toast.
- **The Explorer's polling after a failed request before the ceiling.** It keeps polling, as
  SPEC-233 left it. After the ceiling, FR-001 ends the watch on a failed read, which is the bound
  today's ceiling already gave it.
- **Raising Athena's DML quota, and any infrastructure, API or contract change.**

---

## Functional Requirements

### FR-001: A watch ends at the ceiling, on a status read after it

#### Description:

`useQueryExecution` watches an execution for `MAX_POLL_DURATION_MS`, which is now 30 minutes. The
first read after that mark decides. A terminal status is delivered as `status`, as it is today. A
`QUEUED` or `RUNNING` status ends the watch, and `stillRunning` is set. A read that fails, once its
retry is spent, ends the watch with that `error`, whether or not the caller passed `stopOnError`.
Once the watch has ended, the hook asks nothing more about that execution: not on the interval,
not on a reconnect. The verdict belongs to this watch, so a new watch of the same id looks again.

#### Acceptance Criteria:

- [ ] `MAX_POLL_DURATION_MS` is `30 * 60_000`.
- [ ] With a status that stays `RUNNING`, `stillRunning` is null and polling continues just before
  the ceiling. After the ceiling, the next status read sets `stillRunning` to an object matching
  `{code: 'QueryStillRunning', params: {limit: 30, queryExecutionId: 'q-1'}}`, with `limit` taken
  from `MAX_POLL_DURATION_MS`.
- [ ] Once `stillRunning` is set, advancing the clock by at least twice `POLL_INTERVAL_MS` makes no
  further status request, and neither does going offline and back online.
- [ ] Without `stopOnError`, a status request that fails on every attempt after the ceiling ends
  the watch once its retry is spent. `error` is reported, `stillRunning` stays null, and advancing
  the clock by twice `POLL_INTERVAL_MS` makes no further request. Before the ceiling, the same
  failure keeps polling, as SPEC-233 left it.
- [ ] A status that turns `SUCCEEDED` on the first read after the ceiling is delivered as `status`,
  and `stillRunning` stays null.
- [ ] While the page is unfocused past the ceiling, no status is read and `stillRunning` stays
  null. The first read after the page is focused again decides.
- [ ] After the watch of `q-1` has ended, pointing the hook at `q-2` and back at `q-1` makes a new
  status request for `q-1`, and `stillRunning` is null until the ceiling passes again.

### FR-002: The Query tab settles at the ceiling, and says so

#### Description:

When the watch of the tab's current statement ends at the ceiling, the tab's run settles at once.
Nothing is in flight, Stop gives way to Run, and a batch stops at that statement, so the statements
after it do not start. A warning banner titled "Still running" shows the rule's sentence. In a
batch, the sentence is prefixed with "Statement N of M is still running." and followed by the
existing note about the statements that did not run. The banner's title and variant follow the
message it is showing, so a start failure that outranks the sentence keeps "Query failed." and the
danger variant. The status bar reads "Still running". Nothing is sent to stop the execution, and
its History entry keeps no verdict. The mobile results view shows the same sentence, and the same
verdict on its strip.

#### Acceptance Criteria:

- [ ] A single statement whose status stays `RUNNING` past the ceiling shows the banner "Still
  running" with "Data Quarry stopped waiting for this query after 30 minutes, so its results won’t
  appear here. When it finishes, they’re saved in your files under system_settings/athenaresults,
  in a file named after its query ID (q-1)." The banner is not "Query failed.", and it carries the
  warning variant's `bg-warning-soft` class. Both variants use `role="alert"`, so the class is what
  tells them apart.
- [ ] In the same test, after the banner is visible: "Running…" is gone, Stop is not offered,
  pressing Run starts a new execution (`runQuery` is called a second time), `stopQuery` is not
  called, and `updateQueryHistoryEntry` is never called with `q-1`. The last two are also true of
  today's code, where nothing settles, so they prove something only beside the banner.
- [ ] After the verdict, pressing Run when the new statement fails to start shows the start
  failure's sentence under "Query failed.", with the danger variant.
- [ ] In a three-statement script whose second statement stays `RUNNING` past the ceiling,
  `runQuery` is called exactly twice, and the banner reads "Statement 2 of 3 is still running."
  followed by the sentence and " Statement 3 did not run."
- [ ] The status bar reads "Still running", with no "Running…", no "Failed" and no elapsed time.
- [ ] Under "Run Multiple Queries", when statement 1 returns rows and statement 2 outlives the
  ceiling, Save results stays offered and writes statement 1's result.
- [ ] Below the `tablet` breakpoint, a run started from the mobile results view that outlives the
  ceiling shows the same sentence under the same title, and "Still running" on the strip.

### FR-003: The Data Explorer settles at the ceiling the same way

#### Description:

When the watch of an exploration's statement ends at the ceiling, the Explorer stops reporting the
statement as pending. Its banner shows the same title and sentence as a warning, and "Running…"
appears nowhere. Earlier rows in the tab stay on screen under the banner, as they do under a
failure. With no earlier rows, the body under the banner shows nothing. Save query and Create view
are not refused on the statement's account. The verdict is not remembered as a failed statement,
so going back to that description looks again. Separately, no banner leaves "Running…" or "No rows
returned." on screen when the tab has no earlier rows, and this includes a failed first apply.

#### Acceptance Criteria:

- [ ] A first apply whose status stays `RUNNING` past the ceiling shows a banner titled "Still
  running", with the sentence naming that execution's id and the `bg-warning-soft` class. Neither
  "Running…" nor "No rows returned." appears.
- [ ] When an earlier apply in the tab returned rows, those rows are still on screen under the
  banner.
- [ ] After the banner is visible, the "Save as query" item is not `aria-disabled` and opens its
  dialog.
- [ ] After the verdict, applying another filter and then pressing Back makes a new status request
  for that statement's execution, and "This set of filters failed last time it ran. Nothing has
  been run." does not appear.
- [ ] A first apply that fails (`FAILED`, with a syntax-error reason) shows its danger banner, and
  neither "Running…" nor "No rows returned." appears.
- [ ] *Added during the build, from the execution-frame diff review.* Two tabs on one table with one
  description share an execution. After the first tab's verdict, switching to the second makes a
  new status read, and a query that has since finished shows its rows there. Switching tabs starts
  a new watch, because the id alone cannot tell the two tabs apart.

### FR-004: The Help guides describe the ceiling

#### Description:

The guides say what happens to a query that is still running after 30 minutes, in the words a
user sees. The tab or the Explorer stops waiting and says so. The query keeps running, and
scanning, in Athena, and Stop is no longer offered for it. Its results are saved in
`system_settings/athenaresults` under its query ID when it finishes.

#### Acceptance Criteria:

- [ ] Query › *Write and run a query* carries a warning callout that says all of the above.
- [ ] Query › *Run several statements at once*: the step about a failing statement also covers a
  statement still running after 30 minutes, which stops the script in the same way.
- [ ] Data Explorer › *Start exploring a table* gains a step that says the same about an apply.
- [ ] A Help test asserts that each of those three texts names the ceiling in minutes computed from
  `MAX_POLL_DURATION_MS`, and that the *Write and run a query* callout and the Explorer step name
  `athenaresults`.

---

## API / Interface Contract

```ts
// apps/portal/src/features/catalog/useQueryExecution.ts
/** What a watch that outlived the ceiling reports, shaped for `toUserMessage`. */
export type QueryStillRunning = {
  code: 'QueryStillRunning';
  /** Developer text for the dev-only log. Never rendered. */
  message: string;
  params: {limit: number; queryExecutionId: string};
};

export type QueryExecutionWatch = {
  /** The latest status read for the execution. Undefined until the first one arrives. */
  status: QueryStatus | undefined;
  /** A status request that failed after its retry, or null. */
  error: Error | null;
  /** Set once a status read after the ceiling was still non-terminal, or null. */
  stillRunning: QueryStillRunning | null;
};

export function useQueryExecution(
  queryExecutionId: string | null,
  /** `watchKey` names the watcher: a change starts a new watch even on the same id. Stable only. */
  options?: {stopOnError?: boolean; watchKey?: string}
): QueryExecutionWatch;

// apps/portal/src/features/data-explorer/useExploration.ts — the tab id is the watch key
export function useExploration(exploration: Exploration | null, tabId?: string): UseExplorationResult;

/** True for the verdict above, so a surface can word and colour it apart from a failure. */
export function isQueryStillRunning(value: unknown): value is QueryStillRunning;

// apps/portal/src/features/query/TabExecutionPoller.tsx — one new prop, called at most once per
// execution id, and never for an id that was already settled by a status or a failure.
onStillRunning: (tabId: string, executionId: string, notice: QueryStillRunning) => void;

// apps/portal/src/features/query/useTabRuns.tsx — TabRun gains
stillRunning?: {statementIndex: number; message: UserFacingMessage};

// apps/portal/src/features/query/QueryStatusBar.tsx — owns the verdict as batchFailed does
stillRunning?: boolean;

// QueryResultsRegion and QueryResultsMobile — the banner's title and variant, which default to
// today's "Query failed." and 'danger'
errorTitle?: string;
errorVariant?: BannerVariant;

// QueryResultsMobile — for its strip, passed like batchFailed, since it holds no run
stillRunning: boolean;
```

The watch is hook state, reset during render when the id changes. The ceiling's mark is set by a
timer that the hook starts once per watch. The mark has to be state because render reads it, and
the repo's `react-hooks` preset refuses a synchronous state update in an effect body, as well as a
ref read or a `Date.now()` during render. A timer callback is none of those. The verdict is derived
during render from the mark, the latest status or error, and its `dataUpdatedAt` or
`errorUpdatedAt`. Those two fields are read only once the mark is set, and that matters in both
directions. Read before the mark, they join TanStack's tracked properties, and every poll
re-renders the hook's host, which undoes the reason for the new return shape. Never read, the
deciding `RUNNING` read changes nothing the hook tracks, because the status object is identical
while it is non-terminal, and the verdict would never render. `enabled` is the function form, so it
resolves `false` for the verdict just as it does for `stopOnError`.

## File & Folder Structure

```
apps/portal/src/features/catalog/catalog.constants.ts          # 30 minutes, the comment corrected
apps/portal/src/features/catalog/useQueryExecution.ts          # the watch, the verdict, the new shape
apps/portal/src/features/catalog/index.ts                      # exports the type and the guard
apps/portal/src/features/catalog/queryExecutionHooks.test.ts   # FR-001
apps/portal/src/test/fakeTimers.ts                             # fake timers Testing Library can drive
apps/portal/src/lib/errorMessages.ts                           # QueryStillRunning, params widened
apps/portal/src/lib/apiContract.guard.test.ts                  # CLIENT_MINTED gains the code
apps/portal/src/features/query/TabExecutionPoller.tsx          # onStillRunning
apps/portal/src/features/query/useTabRuns.tsx                  # settles the run
apps/portal/src/features/query/QueryWorkspace.tsx              # the banner's text, title, variant
apps/portal/src/features/query/QueryResultsRegion.tsx          # title and variant props
apps/portal/src/features/query/QueryResultsMobile.tsx          # the same, on mobile
apps/portal/src/features/query/QueryStatusBar.tsx              # "Still running"
apps/portal/src/features/query/QueryWorkspace.test.tsx         # FR-002
apps/portal/src/features/query/queryWorkspaceMobile.test.tsx   # FR-002 mobile criterion
apps/portal/src/features/query/queryResultsUi.test.tsx         # the mobile view's new required prop
apps/portal/src/features/data-explorer/useExploration.ts       # error and isPending
apps/portal/src/features/data-explorer/DataExplorerWorkspace.tsx    # the verdict is not a failure
apps/portal/src/features/data-explorer/ExplorationResultsRegion.tsx # banner, body, save refusal
apps/portal/src/features/data-explorer/dataExplorerUi.test.tsx      # FR-003 AC1, AC5, AC6
apps/portal/src/features/data-explorer/expressionBar.test.tsx       # FR-003 AC2
apps/portal/src/features/data-explorer/queryHistory.test.tsx        # FR-003 AC4
apps/portal/src/features/data-explorer/saveExploration.test.tsx     # FR-003 AC3
apps/portal/src/features/help/helpContent.ts                   # FR-004
apps/portal/src/features/help/help.test.tsx                    # FR-004 criterion
```

## Implementation Phases

### Phase 1: The watch, both screens, and the guides

The hook and its tests go first, because everything else reads its new shape. Then the rule, the
Query tab and its tests, the Explorer and its test, and the Help guides. It is one PR. The change
is small, and neither screen can settle without the hook.
