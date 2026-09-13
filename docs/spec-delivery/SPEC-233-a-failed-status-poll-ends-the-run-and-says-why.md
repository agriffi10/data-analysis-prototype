# Completed Spec — SPEC-233: A Failed Status Poll Ends the Query Tab's Run, and Says Why

## What was completed?

- **A failed status poll ends the tab's run.** When `GET /v1/queries/{id}` fails on both attempts,
  the tab settles immediately. "Running…" goes, Run is free again, and a batch stops at that
  statement without starting the rest. The history entry keeps no verdict, so it reads "Unknown",
  and nothing is sent to stop the execution.
- **The tab says why, in the error code's wording.** The existing banner ("Query failed.") carries
  `toUserText(error)`: for example, *"That item no longer exists. Refresh and try again."* for
  `NotFound`, and *"Can’t reach the server. Check your connection and try again."* for
  `NetworkUnavailable`. A batch keeps its "Statement N of M failed. … did not run." frame. The
  mobile results view shows the same text.
- **One retry first.** `useQueryExecution` now sets `retry: apiRetryPolicy('athena.status')`
  itself. The value is 1, the same as the client default it used to inherit.
- **The poll asks nothing more once it has failed.** `useQueryExecution` gains an opt-in
  `stopOnError`, and `TabExecutionPoller` passes it. With it set, `enabled` resolves `false` once
  the query has failed, so neither the interval nor a reconnect asks again.
- Files: `features/catalog/useQueryExecution.ts`, `features/query/TabExecutionPoller.tsx` (new
  `onPollFailure` prop), and `features/query/useTabRuns.tsx` (`handlePollFailure`).

### Deliberate deviations

- **The reconnect criterion (FR-004 AC2) is tested at the workspace level, not on the hook.** A
  hook test cannot see whether the poller passes the option. Dropping `{stopOnError: true}` at the
  call site left every hook test green, and it turned only the workspace reconnect test red.
- **The fast retry lives in the shared harness.** `createTestQueryClient()` gained `retryDelay: 0`,
  instead of each suite building its own client. No other query hook sets a positive `retry`, so no
  other test moved. `react.md` §21 now says a hook's own retry is visible under the harness.

## What changed from earlier specs?

- `useQueryExecution(id)` becomes `useQueryExecution(id, {stopOnError?})`. The Data Explorer does
  not pass the option, and its behaviour is unchanged: it still polls after an error.
- `TabExecutionPoller` settles each execution id once: with its terminal status (`onFinalize`), or
  with a poll failure (`onPollFailure`). What was `finalizedRef` is now `settledRef`, and it guards
  both paths.
- The SPEC-041/078 run record's `failure` now also means "its status could not be read".

## Verification

- **Local gates, all exit 0:** `format:check`, `lint`, `build`, `check:bundle`, `test:coverage`
  (full suite), `validate_docs.py`, and ruff, mypy and pytest.
- **Mutation checks, each planted once, seen red, then reverted:**
  - An interval-only stop turns the reconnect test red (2 status requests became 4).
  - Dropping the hook's `retry` turns the retry test and every count red.
  - Dropping `stopOnError` at the poller turns the reconnect test red.
  - A history write planted in `handlePollFailure`, and a planted `stopQuery`, each turn the first
    workspace test red. This proves its two "not called" assertions can fail.
- **Live check:** the network-failure row in `docs/testing/e2e.md` §4.3 is written and has not
  been run in this PR. The organic `NotFound`, where the results prefix moves under an id a tab
  still holds, needs a deployment change and is a row in `docs/testing/owed.md`.
