# Completed Spec — SPEC-038: Query Results Pagination — 20 Rows per Page

## What was completed?

- The query-results table now shows **one 20-row page at a time** with a **Prev/Next pager** that
  *replaces* the visible rows (vs. the file browser's append "Load more", SPEC-037) — only ≤20 rows
  are ever mounted in the DOM.
- `QUERY_RESULTS_PAGE_SIZE = 20` added to `query.constants.ts` (single source of truth).
- `useQueryResults` reworked from a thin `useInfiniteQuery` wrapper into a pager hook
  (`UseQueryResultsResult`): current-page `columns`/`rows`, `pageIndex` + 1-based range, `hasPrev`/
  `hasNext`, `goPrev`/`goNext`, and loaded/total counts. **Next** fetches forward via `NextToken` only
  when the next page isn't cached; **Prev** is always served from cache. Page index resets on a new
  execution id (render-phase reset, not an effect).
- `getQueryResults` first page now requests `pageSize + 1` and drops the Athena SELECT header row, so
  page 1 nets a full 20 data rows (not 19); continuation pages request exactly `pageSize`.
- `QueryResultsTable` rebuilt as a presentational pager (range indicator "Rows X–Y of N", absolute row
  numbering, loading/empty states). The full-result CSV download (SPEC-034) is unchanged.

## What changed from earlier specs?

- **SPEC-034 `useQueryResults`**: return shape changed from the raw `useInfiniteQuery` object to
  `UseQueryResultsResult`. The only consumer (`QueryWorkspace`) was updated.
- **SPEC-035 FR-006 results "Load more"**: superseded by this pager (FR-006 already pointed here). The
  file-browser "Load more" (SPEC-015/037) is untouched.
- `getQueryResults` first-page `MaxResults` is now `pageSize + 1` (was `pageSize`); the header-drop
  logic is otherwise unchanged.

## Verification

`npm run lint`, `npm run test` (347 pass — new: service first-page `+1`, hook fetch-forward / Prev-
from-cache / reset-on-new-id, table disabled-states + range indicator), and `npm run build` pass
locally. Live browser check (a >20-row SELECT paging Prev/Next) deferred to deploy — it needs a real
authenticated Athena query; page size, header net-20, and pager behavior are unit-covered. No new
dependency, no IAM change. Note: Athena gives no up-front row total, so the indicator shows "Rows X–Y"
and a definitive total only once the last page is loaded (documented, accepted in the spec).
