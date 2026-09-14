# Completed Spec — SPEC-234: A Long Query Settles at the Ceiling, and Says Where Its Results Go

## What was completed?

- **A watch of a running query lasts 30 minutes, and then it ends visibly.** `MAX_POLL_DURATION_MS`
  went from five minutes to thirty, which is Athena's DML timeout in this account. The first status
  read after the ceiling decides. A terminal status is delivered as usual. One still queued or
  running ends the watch with a verdict, and a failed read ends it with its error. Nothing is asked
  about that execution again: not on the interval, and not on a reconnect.
- **The Query tab settles and says where the results go.** An amber banner titled **Still running**
  reads *"Data Quarry stopped waiting for this query after 30 minutes, so its results won’t appear
  here. When it finishes, they’re saved in your files under system_settings/athenaresults, in a file
  named after its query ID (…)."* A batch frames it as "Statement N of M is still running. … did
  not run." The bar reads **Still running**, Run replaces Stop, nothing is sent to stop the
  execution, and History keeps reading "Unknown". The mobile results view shows the same banner.
- **The Data Explorer settles the same way.** It shows the same banner, keeps the earlier rows under
  it, and still offers Save query and Create view for the statement. It does not remember the
  statement as a failure, so Back onto it looks again at the cached execution.
- **The Help guides say so**, on *Write and run a query*, *Run several statements at once* and
  *Start exploring a table*.
- Files: `features/catalog/useQueryExecution.ts` (returns `{status, error, stillRunning}`, and
  exports `isQueryStillRunning`), `catalog.constants.ts`, the `QueryStillRunning` rule in
  `lib/errorMessages.ts`, `TabExecutionPoller` (`onStillRunning`), `useTabRuns`
  (`handleStillRunning`), `QueryStatusBar` (`stillRunning`), `QueryResultsRegion` and
  `QueryResultsMobile` (`errorTitle`, `errorVariant`), `useExploration`,
  `DataExplorerWorkspace`, `ExplorationResultsRegion`, and `test/fakeTimers.ts`.

### Deliberate deviations

- **The Back criterion (FR-003 AC4) is tested in `queryHistory.test.tsx`, not in
  `expressionBar.test.tsx`,** because that file already drives Back onto a failed description. The
  spec's file list was corrected to match.
- **The live check was not run in this PR.** It needs a DevTools response override held for 30
  minutes, and the browser tools cannot set one. It is §4.3's *A query that outlives the ceiling*
  row, and a row in `docs/testing/owed.md`.

## What changed from earlier specs?

- `useQueryExecution` returns `{status, error, stillRunning}` instead of the raw TanStack result.
  Its two callers moved with it.
- SPEC-233's rule that the Explorer keeps polling after a failed request now holds only until the
  ceiling. After it, a failed read ends the watch for every caller, which is the bound the old
  ceiling used to give.
- The Explorer's status line and body no longer say "Running…" under a banner when the tab has no
  earlier rows, and the body no longer says "No rows returned." there. This changes what a failed
  first apply shows. It used to say "Running…" twice under its banner.
- The Query tab's banner title and colour now follow the message shown. They were always "Query
  failed." and danger.

## Verification

- **Local gates, all exit 0:** `format:check`, `lint`, `build`, `check:bundle`, `test:coverage` (the
  full suite, with its thresholds), `validate_docs.py` and its corpus, the contract regeneration,
  the feature-flag and app-managed-path validators with the path sweep's corpus, the PR-queue hook
  and installer corpora, and ruff. The test names collected by the runner before and after differ
  only by the eighteen added, and none vanished.
- **Mutation checks, each planted once, seen red, then reverted:**
  - A clock-only verdict turns the hidden-page and terminal-after-the-ceiling tests red.
  - An interval-only stop turns the reconnect half red, by one request.
  - Dropping the failed-read clause turns the failing-poll test red.
  - Deleting the watch reset turns the new-watch test red.
  - A no-op settle in `useTabRuns` turns all four workspace tests red.
  - Remembering the verdict as a failure turns the Explorer's Back test red on the suspension text.
  - Reading `dataUpdatedAt` on every render turns the render-count test red: 24 renders over the
    polls where the shipped hook makes 4, all before the ceiling.
  - Keeping the Explorer pending after the verdict turns its hook test red.
- **The Explorer fix was seen red first.** A failed first apply showed "Running…" twice under its
  banner on the base code.
