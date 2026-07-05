# Completed Spec — SPEC-087: Configurable Query-Results Page Size

## What was completed?

- Default query-results page size raised 20 → 100 (`DEFAULT_RESULTS_PAGE_SIZE`, with `MIN`/`MAX_RESULTS_PAGE_SIZE` = 1/1000 and a per-user sessionStorage prefix in `query.constants.ts`; `QUERY_RESULTS_PAGE_SIZE` removed).
- `useResultsPageSize` — workspace-global, per-user session-persisted "Rows per page" value (clamped, defensive storage read, degrade-safe), owned once by `QueryWorkspace`.
- `ResultsPageSizeControl` — labeled free-form integer input in the results-region header (commit on blur/Enter, Escape abandons, invalid reverts / out-of-range clamps, disabled-never-hidden with no result set).
- `useQueryResults` now takes a required `pageSize`; `queryKeys.results` is keyed by `(id, pageSize)` so a size change refetches page 1 at the new size and never mixes stale-sized pages; all executions' page positions reset on a size change.
- Help & guides: "Work with results" gained a Rows-per-page step.

Deviations (in-session technical decisions):

- Athena rejects `GetQueryResults MaxResults > 1000`, so the service clamps the first page's `pageSize + 1` header allowance to 1000 — at the 1000 maximum, page 1 nets 999 data rows.
- Because of that, `useQueryResults` numbers row ranges from actual loaded page lengths instead of `pageIndex × pageSize`.
- Control placement: the always-rendered results-region header (a hoisted "Results" heading row), not the status bar — the status bar only mounts once a run exists, which would break FR-002's "never hidden".

## What changed from earlier specs?

- SPEC-038: `useQueryResults(id, maxRows?)` → `useQueryResults(id, pageSize)` (required); `QueryResultsTable` no longer renders the "Results" `<h2>` (hoisted to `QueryWorkspace`).
- SPEC-078 result tabs and SPEC-041 query tabs all share the one global size (no per-tab override).
- SPEC-080's count walk is untouched (`ROW_COUNT_PAGE_SIZE` unchanged).

## Verification

Lint, Prettier, full Vitest suite (1003 tests incl. new hook/control/pager tests + axe), and `npm run build` green locally; rendered-state (default 100, disabled empty state) verified in the dev preview. Live paging against Athena deferred to normal use (no infra change).
